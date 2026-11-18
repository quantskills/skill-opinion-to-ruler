"""Landing point for PandaData MCP results, in **this skill's own** file format.

Why this module exists
----------------------
MCP tools can only be called by an *agent*; a Python script cannot call them.
So there is no online path here. The data flow is one-directional and file
mediated::

    ① agent  ->  mcp__pandadata__call_pandadata(method=..., params=...)
    ② agent  ->  tests/fixtures/raw/<method>__<label>.json      (verbatim payload)
    ③ this script  ->  tests/fixtures/landed/bars_<SYMBOL>.csv  (this skill's own
                       ``date,open,high,low,close,volume`` schema, the one
                       ``load_csv``/``--fixture`` has always used)
                       tests/fixtures/landed/dominant_<PRODUCT>.csv  (date,contract)
                       tests/fixtures/landed/provenance.json
    ④ scripts/evaluate.py --landed-dir tests/fixtures/landed ...  (read-only)

Nothing outside this skill directory is read or written: no other skill's
scripts, no other skill's directory layout, no shared manifest.

What is enforced here
---------------------
Truncation is a property of the **parquet response channel**, not of MCP in
general: the preview is capped (``preview_rows`` <= 2000) and anything beyond
that is cut *silently*, so a payload is only trustworthy when it says so. The
two criteria are ``truncated: true`` and ``row_count < total_rows``. A payload
that fails them is refused with a structured error and a non-zero exit; the
escape hatch is ``--allow-partial``, which additionally leaves a ``partial``
marker in ``provenance.json`` so every downstream report can see it.

The **JSON channel** (``get_future_dominant``, ``get_trade_cal``) returns a
complete array and carries none of those fields — absence of the fields is not
a truncation signal, and this module does not invent one.

Everything here is standard library only, so a bare ``python3`` runs it.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: This skill's own data directory (shipped synthetic fixtures live at its top).
DEFAULT_FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures")
#: ② where the agent drops verbatim MCP payloads.
DEFAULT_RAW_DIR = os.path.join(DEFAULT_FIXTURES_DIR, "raw")
#: ③ where this script writes this skill's own CSV schema.
DEFAULT_LANDED_DIR = os.path.join(DEFAULT_FIXTURES_DIR, "landed")

PROVENANCE_NAME = "provenance.json"

FUTURE_DAILY = "get_future_daily"
FUTURE_DOMINANT = "get_future_dominant"

#: ``<method>__<label>.json`` — the method part must be a real MCP method name.
RAW_NAME_RE = re.compile(r"^(get_[a-z0-9_]+)__(.+)\.json$")
#: A date in a label (``get_future_daily__RB2410_20240101_20240331.json``).
DATE_IN_NAME_RE = re.compile(r"(19|20)\d{6}")

ROW_KEYS = ("rows", "data", "records", "results", "preview", "items")
#: The gateway wraps the table in an envelope: ``{"ok":…, "method":…, "result":
#: {"columns": […], "rows": […]}}``. This reader only looked one level deep, so a
#: payload landed **verbatim** as ``references/mcp-data.md`` instructs was rejected
#: with ``payload_unreadable`` — the documented real-data path had never run.
ENVELOPE_KEYS = ("result", "data", "payload", "response")
TRUNCATED_KEYS = ("truncated", "is_truncated")
ROW_COUNT_KEYS = ("row_count", "rows_returned", "returned_rows", "row_cnt")
TOTAL_ROWS_KEYS = ("total_rows", "rows_total", "total", "row_total")
PARAM_KEYS = ("params", "request", "args", "query")

DATE_COLUMNS = ("date", "trade_date", "datetime", "nature_date")
#: row-level instrument identity (daily bars)
SYMBOL_COLUMNS = ("symbol", "code", "ts_code", "instrument")
#: the contract a dominant mapping points at; ``symbol`` first so the value is
#: the same identifier ``get_future_daily`` was fetched with
CONTRACT_COLUMNS = ("symbol", "trading_code", "dominant_id", "contract", "code")
UNDERLYING_COLUMNS = ("underlying_symbol", "underlying", "product", "product_code")

#: preview cap of the parquet channel, measured (not a guess)
MAX_ROWS_PER_CALL = 2000

BAR_FIELDS = ("date", "open", "high", "low", "close", "volume")
PRICE_FIELDS = ("open", "high", "low", "close")


# ---------------------------------------------------------------------------
# Errors: structured, never a silent degradation
# ---------------------------------------------------------------------------
class DataUnavailable(RuntimeError):
    """Root "no local file can serve this request" error for the data layer.

    It lives here so the landing script can raise the structured failures
    without importing the adapter, and callers keep one catch-all.
    """

    code = "data_unavailable"

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": str(self)}


class LandingError(DataUnavailable):
    """A landed payload or built file is unusable. Carries ``code``/``hint``."""

    code = "landing_error"

    def __init__(self, message: str, *, hint: str = "", **detail: Any) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail: Dict[str, Any] = {"code": self.code, **detail}

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "hint": self.hint, "detail": self.detail}


def _open_out(out_dir: str, name: str, newline: Optional[str] = None):
    """Open one product file, turning a refused write into ``OutputNotWritable``.

    Three separate write sites each raising their own ``PermissionError`` is how
    a read-only install ends up printing a stack frame instead of telling the
    operator what to do about it. One funnel, one error, one remedy.
    """
    try:
        return open(os.path.join(out_dir, name), "w", newline=newline, encoding="utf-8")
    except OSError as exc:
        raise OutputNotWritable(
            "cannot write %s into %s (%s: %s)"
            % (name, out_dir, type(exc).__name__, exc.strerror),
            hint="an installed skill tree is read-only: rebuild with --out-dir in a "
                 "writable directory and point evaluate.py --landed-dir at that same "
                 "directory; products are never silently redirected elsewhere",
            out_dir=out_dir, file=name) from exc


class RawDirMissing(LandingError):
    """Nothing was landed yet: the agent has not written any payload."""

    code = "landing_not_found"


class PayloadUnreadable(LandingError):
    """The file is not a verbatim MCP payload (no rows, broken JSON, wrong shape)."""

    code = "payload_unreadable"


class PayloadEmpty(LandingError):
    """The payload parsed fine but contains zero rows: nothing to build from."""

    code = "payload_empty"


class PayloadTruncated(LandingError):
    """The parquet preview was cut; the request must be re-issued in smaller pieces."""

    code = "payload_truncated"


class BarRowError(LandingError):
    """A row cannot become a bar (no date, or a blank/zero price)."""

    code = "bad_bar_row"


class OutputNotWritable(LandingError):
    """The build was valid but the destination refuses writes (read-only install).

    Raised instead of letting a bare ``PermissionError`` traceback escape: the
    work is already done and *legitimately* finished, so the operator needs the
    destination and the remedy, not a stack frame. Refusing to redirect silently
    is deliberate -- ``evaluate.py --landed-dir`` has to be able to find these
    files, so guessing a writable spot would build a dataset nobody can locate.
    """

    code = "landing_not_writable"


class BadArguments(LandingError):
    """The command line itself is wrong (exit code 2)."""

    code = "invalid_arguments"
    exit_code = 2                     # 0 ok / 2 usage / 3 data unavailable


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------
def norm_date(value: Any) -> str:
    """Normalise any date stamp to ``YYYYMMDD`` (``2024-01-02``/``2024/01/02``/...)."""
    s = str(value if value is not None else "").strip()
    if not s:
        return ""
    s = s.replace("-", "").replace("/", "").replace(".", "")
    if " " in s:
        s = s.split(" ", 1)[0]
    if "T" in s:
        s = s.split("T", 1)[0]
    return s[:8]


def find_column(row: Dict[str, Any], candidates: Sequence[str]) -> Optional[str]:
    """Case-insensitive lookup of the first candidate column present in ``row``."""
    lowered = {str(k).lower(): v for k, v in row.items()}
    for cand in candidates:
        if cand in lowered:
            return cand
    return None


def _lower(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in row.items()}


def row_date(row: Dict[str, Any]) -> str:
    lowered = _lower(row)
    key = find_column(lowered, DATE_COLUMNS)
    return norm_date(lowered[key]) if key else ""


def row_value(row: Dict[str, Any], candidates: Sequence[str]) -> str:
    lowered = _lower(row)
    key = find_column(lowered, candidates)
    value = lowered.get(key) if key else None
    return str(value).strip() if value not in (None, "") else ""


# ---------------------------------------------------------------------------
# Payload reading + the truncation guard (local to this skill, on purpose)
# ---------------------------------------------------------------------------
def load_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise PayloadUnreadable(f"cannot read landed payload {path}: {exc}",
                                hint="重新落盘该载荷，或检查文件权限。", file=path) from exc
    except ValueError as exc:
        raise PayloadUnreadable(
            f"{os.path.basename(path)} is not valid JSON: {exc}",
            hint="这里存的必须是 mcp__pandadata__call_pandadata 返回的**原样**载荷，"
                 "不是转述、不是摘要、不是手抄的几行。",
            file=path) from exc


def _first_key(mapping: Any, keys: Sequence[str]) -> Optional[str]:
    if not isinstance(mapping, dict):
        return None
    lowered = {str(k).lower(): k for k in mapping}
    for key in keys:
        if key in lowered:
            return lowered[key]
    return None


def payload_rows(payload: Any, *, origin: str) -> Tuple[List[Dict[str, Any]], Optional[List[str]]]:
    """Extract row dicts from either response channel, tolerating column zips.

    Returns ``(rows, columns)``. A list payload (JSON channel) is rows as-is; a
    dict payload (parquet preview) hides them under one of :data:`ROW_KEYS`, and
    may hold list-of-lists that need ``columns`` to zip against.
    """
    columns: Optional[List[str]] = None
    container: Any = payload
    if isinstance(container, dict) and _first_key(container, ROW_KEYS) is None:
        for _env in ENVELOPE_KEYS:
            _inner = container.get(_env)
            if isinstance(_inner, dict) and _first_key(_inner, ROW_KEYS) is not None:
                container = _inner
                break
    if isinstance(container, dict):
        columns_key = _first_key(container, ("columns", "fields", "header"))
        if columns_key is not None:
            raw_cols = container[columns_key]
            if isinstance(raw_cols, list):
                columns = [str(c) for c in raw_cols]
        key = _first_key(container, ROW_KEYS)
        if key is None:
            raise PayloadUnreadable(
                f"{os.path.basename(origin)} 里没有行数据（找不到 "
                f"{'/'.join(ROW_KEYS)} 任一字段）",
                hint="载荷必须是 MCP 返回的原样内容；裸对象/转述文本都读不出行记录。",
                file=origin, keys=sorted(str(k) for k in container))
        container = container[key]
    if isinstance(container, dict):
        # {"20240102": {...}} style maps are not a table; refuse rather than guess.
        raise PayloadUnreadable(
            f"{os.path.basename(origin)} 的行数据是对象而不是列表，读不出表",
            hint="重新调 mcp__pandadata__call_pandadata 并把返回原样落盘。", file=origin)
    if not isinstance(container, list):
        raise PayloadUnreadable(f"{os.path.basename(origin)} 的行数据不是列表",
                                hint="重新落盘 MCP 返回的原样载荷。", file=origin)
    rows: List[Dict[str, Any]] = []
    for item in container:
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, (list, tuple)) and columns:
            rows.append(dict(zip(columns, item)))
        else:
            raise PayloadUnreadable(
                f"{os.path.basename(origin)} 里有既非对象也非列表的行",
                hint="列式形态需要和 columns 一起才能拉成对象；重新原样落盘。",
                file=origin)
    return rows, columns


def declared_number(mapping: Any, keys: Sequence[str]) -> Optional[int]:
    if not isinstance(mapping, dict):
        return None
    key = _first_key(mapping, keys)
    if key is None:
        return None
    try:
        return int(str(mapping[key]).strip())
    except (TypeError, ValueError):
        return None


def check_payload(payload: Any, rows: List[Dict[str, Any]], *, origin: str) -> Dict[str, Any]:
    """Inspect one payload for completeness. Pure inspection: raises nothing.

    The result is the input to :func:`require_complete`. Note what is *not*
    looked at: ``preview_rows`` is a **request** parameter, and reading it as a
    row count would brand every honest payload as tampered.
    """
    row_count = declared_number(payload, ROW_COUNT_KEYS)
    total_rows = declared_number(payload, TOTAL_ROWS_KEYS)
    truncated: Optional[bool] = None
    if isinstance(payload, dict):
        key = _first_key(payload, TRUNCATED_KEYS)
        if key is not None:
            value = payload[key]
            truncated = str(value).strip().lower() in ("true", "1", "yes")

    reasons: List[str] = []
    if truncated:
        reasons.append("truncated=True")
    if row_count is not None and total_rows is not None and row_count < total_rows:
        reasons.append(f"row_count({row_count}) < total_rows({total_rows})")
    if row_count is not None and total_rows is None and row_count > MAX_ROWS_PER_CALL:
        reasons.append(f"row_count({row_count}) 超过 parquet 通道单次上限 {MAX_ROWS_PER_CALL}")

    mismatch = None
    if row_count is not None and row_count != len(rows):
        mismatch = f"声明 row_count={row_count}，文件里实际有 {len(rows)} 行"

    return {
        "file": os.path.basename(origin),
        "rows": len(rows),
        "row_count": row_count,
        "total_rows": total_rows,
        "truncated": bool(truncated),
        "truncation_reasons": reasons,
        "declared_row_mismatch": mismatch,
        "partial": bool(reasons),
    }


def require_complete(meta: Dict[str, Any], *, allow_partial: bool, method: str,
                     context: str = "") -> None:
    """Refuse an incomplete payload unless the caller explicitly allows partial.

    Order matters: truncation is the real cause and must be reported as such,
    not masked by the row-bookkeeping check afterwards.
    """
    if meta["truncation_reasons"]:
        if allow_partial:
            return
        where = f"（{context}）" if context else ""
        raise PayloadTruncated(
            f"{method} 的载荷 {meta['file']} 不完整"
            f"（{'; '.join(meta['truncation_reasons'])}）{where}",
            hint=(f"parquet 通道单次最多返回 {MAX_ROWS_PER_CALL} 行预览，超出部分是"
                  f"静默截断而不是报错。请把请求切小（更短的日期区间 / 更少标的 / 更少 "
                  f"fields）重取并原样覆盖该文件；"
                  f"确实要在残缺数据上试跑，才加 --allow-partial（产物会留下 partial 标记）。"
                  f"\n取数调用：mcp__pandadata__call_pandadata method={method} "
                  f"params={{...}}"),
            file=meta["file"], truncation_reasons=meta["truncation_reasons"],
            row_count=meta["row_count"], total_rows=meta["total_rows"])
    if meta["declared_row_mismatch"]:
        raise PayloadUnreadable(
            f"{method} 的载荷 {meta['file']} 与自身声明不符："
            f"{meta['declared_row_mismatch']}",
            hint="载荷被改过或复制不全。重新原样落盘，别手工编辑行数据。",
            file=meta["file"])


def read_payload(path: str, *, method: Optional[str] = None,
                 allow_partial: bool = False
                 ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Any]:
    """Read one landed payload, guarding completeness; returns ``(rows, meta, payload)``."""
    payload = load_json(path)
    rows, _columns = payload_rows(payload, origin=path)
    name = RAW_NAME_RE.match(os.path.basename(path))
    resolved_method = method or (name.group(1) if name else "payload")
    if not rows:
        raise PayloadEmpty(
            f"{resolved_method} 的载荷 {os.path.basename(path)} 是空的",
            hint=(f"空结果不等于『没有数据』，也可能是区间落在非交易日或参数写错。"
                  f"重新调 mcp__pandadata__call_pandadata method={resolved_method} 核对参数。"),
            file=path)
    meta = check_payload(payload, rows, origin=path)
    require_complete(meta, allow_partial=allow_partial, method=resolved_method)
    return rows, meta, payload


def discover_payloads(raw_dir: str, method: str) -> List[str]:
    """All ``<method>__*.json`` payloads in the landing directory, sorted."""
    if not os.path.isdir(raw_dir):
        return []
    out = []
    for entry in sorted(os.listdir(raw_dir)):
        match = RAW_NAME_RE.match(entry)
        if match and match.group(1) == method:
            out.append(os.path.join(raw_dir, entry))
    return out


# ---------------------------------------------------------------------------
# Payload -> this skill's own bar schema
# ---------------------------------------------------------------------------
def bar_from_row(row: Dict[str, Any], *, symbol: str, origin: str) -> Dict[str, object]:
    """Map one daily-bar row onto the internal schema, refusing bad prices.

    A blank price is refused rather than turned into a zero: a zero would let a
    numeric level quoted in an opinion "compare" against a price nobody traded.
    """
    lowered = _lower(row)
    date = row_date(lowered)
    if len(date) != 8:
        raise BarRowError(
            f"{symbol} 在 {os.path.basename(origin)} 里有一行没有可用日期列"
            f"（可识别的日期列：{'/'.join(DATE_COLUMNS)}）",
            hint="确认取数时把日期列取全了：get_future_daily 的 fields 需含 date。",
            symbol=symbol, file=os.path.basename(origin),
            columns=sorted(str(k) for k in lowered))
    for field in PRICE_FIELDS:
        if lowered.get(field) in (None, "", 0, 0.0, "0", "0.0"):
            raise BarRowError(
                f"{symbol} {date} 的 {field} 是空值或 0，拒绝在虚构价格上回测",
                hint="重新取数把该字段取全（fields 至少含 open/high/low/close）。",
                symbol=symbol, date=date, field=field)
    try:
        bar: Dict[str, object] = {
            "date": date,
            "open": float(lowered["open"]),
            "high": float(lowered["high"]),
            "low": float(lowered["low"]),
            "close": float(lowered["close"]),
            "volume": float(lowered.get("volume") or 0.0),
        }
    except (TypeError, ValueError) as exc:
        raise BarRowError(f"{symbol} {date} 的价格列不是数值：{exc}",
                          hint="检查落盘载荷是否被手工改写。",
                          symbol=symbol, date=date) from exc
    return bar


def params_of(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    key = _first_key(payload, PARAM_KEYS)
    return payload[key] if isinstance(payload.get(key), dict) else {}


def build(raw_dir: str = DEFAULT_RAW_DIR, out_dir: str = DEFAULT_LANDED_DIR,
          *, allow_partial: bool = False, start: str = "", end: str = "",
          symbols: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Convert landed payloads into this skill's own CSV files. Never fetches.

    Validation happens entirely before writing: a refusal leaves no half-built
    directory behind. The provenance sidecar records which payload each file
    came from, and whether any of them was admitted while partial.
    """
    if not os.path.isdir(raw_dir):
        raise RawDirMissing(
            f"取数落点目录不存在：{raw_dir}",
            hint=("数据先由 agent 落盘，本脚本不联网。步骤：\n"
                  "① mcp__pandadata__call_pandadata method=get_future_daily "
                  'params={"start_date": "<YYYYMMDD>", "end_date": "<YYYYMMDD>", '
                  '"symbol": "<CONTRACT>"}\n'
                  "② 把返回载荷原样写成 "
                  f"{raw_dir}/get_future_daily__<label>.json\n"
                  f"   （默认落点 {os.path.relpath(DEFAULT_RAW_DIR, ROOT)}；"
                  f"写在别处时用 --raw-dir 指过来）\n"
                  "③ python3 scripts/mcp_landing.py --build"
                  f" --raw-dir {raw_dir}"),
            raw_dir=raw_dir)

    wanted = {str(s).strip() for s in (symbols or []) if str(s).strip()}
    start_d, end_d = norm_date(start), norm_date(end)
    bars_index: Dict[str, Dict[str, Any]] = {}
    dominant_index: Dict[str, Dict[str, Any]] = {}
    partial_payloads: List[str] = []
    conflicts: List[Dict[str, Any]] = []
    outside_window = 0

    daily_payloads = discover_payloads(raw_dir, FUTURE_DAILY)
    dominant_payloads = discover_payloads(raw_dir, FUTURE_DOMINANT)
    if not daily_payloads and not dominant_payloads:
        raise RawDirMissing(
            f"{raw_dir} 里没有任何 <method>__<label>.json 载荷",
            hint=("命名约定：<method>__<label>.json，例如 "
                  "get_future_daily__RB2410_20240101_20240331.json、"
                  "get_future_dominant__RB.json。"
                  "先由 agent 调 mcp__pandadata__call_pandadata 取数并原样落盘。"),
            raw_dir=raw_dir)

    for path in daily_payloads:
        rows, meta, payload = read_payload(path, method=FUTURE_DAILY,
                                           allow_partial=allow_partial)
        if meta["partial"]:
            partial_payloads.append(meta["file"])
        window = _params_window(payload)
        for row in rows:
            symbol = row_value(row, SYMBOL_COLUMNS)
            if not symbol:
                raise BarRowError(
                    f"{meta['file']} 里有一行没有标的代码列"
                    f"（可识别：{'/'.join(SYMBOL_COLUMNS)}）",
                    hint="fields 里带上 symbol，否则无法把行归到具体合约。",
                    file=meta["file"])
            if wanted and symbol not in wanted:
                continue
            entry = bars_index.setdefault(
                symbol, {"by_date": {}, "payloads": [], "partial": False,
                         "requested_window": window})
            if meta["file"] not in entry["payloads"]:
                entry["payloads"].append(meta["file"])
            if meta["partial"]:
                entry["partial"] = True
            date = row_date(row)
            if (start_d and date < start_d) or (end_d and date > end_d):
                outside_window += 1
                continue
            bar = bar_from_row(row, symbol=symbol, origin=path)
            previous = entry["by_date"].get(date)
            if previous is not None and previous != bar:
                # Same (symbol, date) from two payloads with different values:
                # keep the first and say so, never average or silently overwrite.
                conflicts.append({"file": meta["file"], "symbol": symbol, "date": date,
                                  "kept": previous, "ignored": bar})
                continue
            entry["by_date"][date] = bar

    for path in dominant_payloads:
        rows, meta, payload = read_payload(path, method=FUTURE_DOMINANT,
                                           allow_partial=allow_partial)
        if meta["partial"]:
            partial_payloads.append(meta["file"])
        window = _params_window(payload)
        for row in rows:
            lowered = _lower(row)
            date = row_date(lowered)
            contract = row_value(lowered, CONTRACT_COLUMNS)
            if len(date) != 8 or not contract:
                raise BarRowError(
                    f"{meta['file']} 里有一行凑不出 date + contract"
                    f"（可识别的合约列：{'/'.join(CONTRACT_COLUMNS)}）",
                    hint="get_future_dominant 返回 date,symbol,trading_code,"
                         "underlying_symbol；落盘时别裁掉 symbol 列。",
                    date=date, file=meta["file"])
            if (start_d and date < start_d) or (end_d and date > end_d):
                outside_window += 1
                continue
            product = row_value(lowered, UNDERLYING_COLUMNS) or _product_of(contract)
            entry = dominant_index.setdefault(
                product, {"by_date": {}, "payloads": [], "partial": False,
                          "requested_window": window})
            if meta["file"] not in entry["payloads"]:
                entry["payloads"].append(meta["file"])
            if meta["partial"]:
                entry["partial"] = True
            previous = entry["by_date"].get(date)
            if previous is not None and previous != contract:
                conflicts.append({"file": meta["file"], "symbol": product, "date": date,
                                  "kept": previous, "ignored": contract})
                continue
            entry["by_date"][date] = contract

    if not bars_index and not dominant_index:
        raise PayloadEmpty(
            f"落盘的载荷过滤后没有任何可用行（start={start or '不限'} "
            f"end={end or '不限'} symbol={sorted(wanted) if wanted else '不限'}）",
            hint="放宽 --start/--end 或去掉 --symbol 重建；空数据不能出结论。",
            raw_dir=raw_dir)

    # Everything above validated; only now write. A refusal never gets here.
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError as exc:
        raise OutputNotWritable(
            "cannot create the output directory %s (%s: %s)"
            % (out_dir, type(exc).__name__, exc.strerror),
            hint="an installed skill tree is read-only: pass --out-dir to a writable "
                 "directory and point evaluate.py --landed-dir at the same place",
            out_dir=out_dir) from exc
    written: List[str] = []
    files_meta: Dict[str, Dict[str, Any]] = {}

    for symbol in sorted(bars_index):
        entry = bars_index[symbol]
        by_date = entry["by_date"]
        if not by_date:
            continue
        name = f"bars_{safe_name(symbol)}.csv"
        with _open_out(out_dir, name, newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(list(BAR_FIELDS))
            for date in sorted(by_date):
                writer.writerow([by_date[date][f] for f in BAR_FIELDS])
        written.append(name)
        files_meta[name] = {"method": FUTURE_DAILY, "symbol": symbol, "rows": len(by_date),
                            "first_date": min(by_date), "last_date": max(by_date),
                            "payloads": entry["payloads"], "partial": entry["partial"],
                            "requested_window": entry["requested_window"]}

    for product in sorted(dominant_index):
        entry = dominant_index[product]
        by_date = entry["by_date"]
        if not by_date:
            continue
        name = f"dominant_{safe_name(product)}.csv"
        with _open_out(out_dir, name, newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["date", "contract"])
            for date in sorted(by_date):
                writer.writerow([date, by_date[date]])
        written.append(name)
        ordered = [by_date[d] for d in sorted(by_date)]
        files_meta[name] = {"method": FUTURE_DOMINANT, "product": product,
                            "rows": len(by_date), "first_date": min(by_date),
                            "last_date": max(by_date),
                            "contracts": sorted(set(ordered)),
                            "rolls": sum(1 for a, b in zip(ordered, ordered[1:]) if a != b),
                            "payloads": entry["payloads"], "partial": entry["partial"],
                            "requested_window": entry["requested_window"]}

    provenance = {
        "generated_by": os.path.relpath(os.path.abspath(__file__), ROOT),
        "raw_dir": os.path.relpath(os.path.abspath(raw_dir), ROOT),
        "window": {"start": start_d or None, "end": end_d or None},
        "allow_partial": bool(allow_partial),
        "partial": bool(partial_payloads),
        "partial_payloads": sorted(set(partial_payloads)),
        "rows_outside_window": outside_window,
        "conflicting_rows": len(conflicts),
        "files": files_meta,
    }
    with _open_out(out_dir, PROVENANCE_NAME) as fh:
        json.dump(provenance, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    written.append(PROVENANCE_NAME)

    summary: Dict[str, Any] = {"ok": True, "out_dir": out_dir, "raw_dir": raw_dir,
                               "built": len(written), "files": written,
                               "partial": provenance["partial"],
                               "partial_payloads": provenance["partial_payloads"],
                               "rows_outside_window": outside_window}
    if conflicts:
        summary["warnings"] = [
            f"{len(conflicts)} 行与同一 (标的,日期) 上已保留的取值冲突，保留先出现的一份：" +
            "; ".join(f"{c['symbol']} {c['date']}" for c in conflicts[:5]) +
            "（重复取数请删掉多余载荷，别靠覆盖顺序碰运气）"]
    return summary


def _product_of(contract: str) -> str:
    """RB2410 / RB2410.SH -> RB. Only a fallback: payloads carry underlying_symbol."""
    head = re.match(r"[A-Za-z]+", contract.strip())
    return head.group(0).upper() if head else contract.strip()


def _params_window(payload: Any) -> Dict[str, Any]:
    params = params_of(payload)
    out: Dict[str, Any] = {}
    for key, field in (("start_date", "start"), ("end_date", "end"), ("date", "date")):
        if key in params:
            out[field] = norm_date(params[key])
    if "symbol" in params:
        raw = params["symbol"]
        out["symbol"] = raw if isinstance(raw, list) else [raw]
    return out


def safe_name(text: str) -> str:
    """Filesystem-safe form of an instrument id (``RB2410.SH`` -> ``RB2410_SH``)."""
    return re.sub(r"[^A-Za-z0-9_.\-]+", "_", text).strip("_") or "UNKNOWN"


# ---------------------------------------------------------------------------
# Inspection helpers (used by --verify and by the tests)
# ---------------------------------------------------------------------------
def inspect_payload(path: str) -> Dict[str, Any]:
    """Report what one landed payload holds, without refusing anything."""
    payload = load_json(path)
    rows, _ = payload_rows(payload, origin=path)
    match = RAW_NAME_RE.match(os.path.basename(path))
    meta = check_payload(payload, rows, origin=path)
    meta["method"] = match.group(1) if match else None
    meta["symbols"] = sorted({row_value(r, SYMBOL_COLUMNS) for r in rows} - {""})[:20]
    meta["dates"] = [d for d in sorted({row_date(r) for r in rows}) if len(d) == 8]
    meta["params"] = params_of(payload)
    return meta


def verify(raw_dir: str = DEFAULT_RAW_DIR, out_dir: str = DEFAULT_LANDED_DIR) -> Dict[str, Any]:
    """Structured status of the two stages: payloads landed, files built, partial?"""
    report: Dict[str, Any] = {"ok": True, "raw_dir": raw_dir, "out_dir": out_dir,
                              "payloads": [], "problems": []}
    if not os.path.isdir(raw_dir):
        report["ok"] = False
        report["problems"].append({
            "code": RawDirMissing.code,
            "message": f"取数落点不存在：{raw_dir}",
            "hint": "由 agent 调 mcp__pandadata__call_pandadata 后原样落盘，再跑 --build。"})
    else:
        for entry in sorted(os.listdir(raw_dir)):
            match = RAW_NAME_RE.match(entry)
            if not match:
                continue
            path = os.path.join(raw_dir, entry)
            try:
                report["payloads"].append(inspect_payload(path))
            except LandingError as exc:
                report["problems"].append(exc.as_dict())
    if not os.path.isfile(os.path.join(out_dir, PROVENANCE_NAME)):
        report["problems"].append({
            "code": "provenance_missing",
            "message": f"{out_dir} 里没有 {PROVENANCE_NAME}（还没 --build，或目录不是本脚本写的）",
            "hint": f"python3 scripts/mcp_landing.py --build --out-dir {out_dir}"})
    else:
        with open(os.path.join(out_dir, PROVENANCE_NAME), encoding="utf-8") as fh:
            provenance = json.load(fh)
        report["built"] = {"files": len(provenance.get("files", {})),
                           "partial": bool(provenance.get("partial")),
                           "partial_payloads": provenance.get("partial_payloads", [])}
        if provenance.get("partial"):
            report["problems"].append({
                "code": PayloadTruncated.code,
                "message": "已构建的产物里带有 partial 标记的载荷：" +
                           ", ".join(provenance.get("partial_payloads", [])),
                "hint": "这些数字不足以支撑结论：切小请求重取后重新 --build。"})
    report["ok"] = report["ok"] and not report["problems"]
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mcp_landing.py",
        description="Convert agent-landed PandaData MCP payloads into this skill's own "
                    "CSV schema (tests/fixtures/landed/). Read files only: never fetches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  python3 scripts/mcp_landing.py --build\n"
               "  python3 scripts/mcp_landing.py --build --start 20240101 --end 20240331\n"
               "  python3 scripts/mcp_landing.py --verify\n"
               "  python3 scripts/mcp_landing.py --inspect "
               "tests/fixtures/raw/get_future_daily__RB2410.json\n")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true",
                      help="landed payloads -> tests/fixtures/landed/*.csv (+ provenance.json)")
    mode.add_argument("--verify", action="store_true",
                      help="report payload/built-file status without writing anything")
    mode.add_argument("--inspect", metavar="PAYLOAD.json",
                      help="print what one landed payload contains (rows, dates, flags)")
    ap.add_argument("--raw-dir", default=DEFAULT_RAW_DIR,
                    help="landing directory written by the agent (default: %(default)s)")
    ap.add_argument("--out-dir", default=DEFAULT_LANDED_DIR,
                    help="where this skill's own CSV files are written (default: %(default)s)")
    ap.add_argument("--start", default="", help="keep rows on/after this date (YYYYMMDD)")
    ap.add_argument("--end", default="", help="keep rows on/before this date (YYYYMMDD)")
    ap.add_argument("--symbol", action="append", default=[], metavar="SYMBOL",
                    help="only build bars for this instrument (repeatable)")
    ap.add_argument("--allow-partial", action="store_true",
                    help="admit truncated payloads; provenance then marks them partial")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    return ap


def _emit(payload: Dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def run(args: argparse.Namespace) -> Dict[str, Any]:
    raw_dir = os.path.abspath(os.path.expanduser(args.raw_dir))
    out_dir = os.path.abspath(os.path.expanduser(args.out_dir))
    for label, value in (("start", args.start), ("end", args.end)):
        if value and len(norm_date(value)) != 8:
            raise BadArguments(f"--{label}={value} 不是 YYYYMMDD",
                               hint="日期一律写成 20240101 这种 8 位形式。")
    if args.inspect:
        return inspect_payload(os.path.abspath(os.path.expanduser(args.inspect)))
    if args.verify:
        return verify(raw_dir, out_dir)
    return build(raw_dir, out_dir, allow_partial=args.allow_partial,
                 start=args.start, end=args.end, symbols=args.symbol)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args)
    except LandingError as exc:
        print(json.dumps({"ok": False, "error": exc.as_dict()}, ensure_ascii=False, indent=2))
        return getattr(exc, "exit_code", 3)   # same 2/3 scheme as data_loader.py
    _emit(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
