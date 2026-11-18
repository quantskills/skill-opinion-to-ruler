"""Market-data adapter: this skill's own CSV bars, from the bundled fixtures or landed payloads.

There is no online data path here, by design. MCP tools can only be called by
an *agent*, so the fetch happens outside this script and lands on disk::

    ① agent  mcp__pandadata__call_pandadata(method=get_future_daily /
                                          get_future_dominant, params=...)
    ② agent  -> tests/fixtures/raw/<method>__<label>.json   (verbatim payload)
    ③ python3 scripts/mcp_landing.py --build
              -> tests/fixtures/landed/bars_<SYMBOL>.csv        (this module reads those)
              -> tests/fixtures/landed/dominant_<PRODUCT>.csv
              -> tests/fixtures/landed/provenance.json

``scripts/mcp_landing.py`` owns payload parsing and the truncation guard; this
module owns the bar schema, the dominant-contract stitching and the coverage
policy. Nothing outside this skill directory is read.

Design constraints
------------------
* **No look-ahead**: only bars strictly after ``published_at`` reach the
  backtester. This module returns a sorted series and performs no filtering;
  the backtester owns the cut-off rule.
* **No silent fallback**: a missing file, a window the data does not span, or a
  blank price raises a structured error. Nothing here invents a price, and
  nothing here quietly shortens the window — the caller has to ask for that
  (``--coverage shrink``), and the returned metadata records that it did.
* **Provenance stays visible**: whether a series was built from a truncated
  payload is read out of ``provenance.json`` and carried into the report, so a
  partial number can never pose as a complete one.
* **No credentials, ever**: the MCP session belongs to the agent
  (Settings -> PandaData -> Login). This module only reads files.

The dominant-contract construction is unchanged in intent from the pre-MCP
version; only its input moved from an SDK call to local files. See
``_stitch_dominant``.
"""

from __future__ import annotations

import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

import mcp_landing
from mcp_landing import (
    BarRowError,
    DataUnavailable,
    LandingError,
    PayloadEmpty,
    PayloadTruncated,
    norm_date,
)

BAR_FIELDS = ("date", "open", "high", "low", "close", "volume")
PRICE_FIELDS = ("open", "high", "low", "close")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: shipped synthetic fixtures (the pre-MCP layout) and the landed real data live
#: in two clearly separate places, so a real run can never shadow a fixture run
DEFAULT_FIXTURES_DIR = os.path.join(ROOT, "tests", "fixtures")
DEFAULT_LANDED_DIR = os.path.join(DEFAULT_FIXTURES_DIR, "landed")

COVERAGE_ERROR = "error"
COVERAGE_SHRINK = "shrink"
COVERAGE_POLICIES = (COVERAGE_ERROR, COVERAGE_SHRINK)

PROVENANCE_NAME = mcp_landing.PROVENANCE_NAME

__all__ = [
    "BAR_FIELDS",
    "DEFAULT_FIXTURES_DIR",
    "DEFAULT_LANDED_DIR",
    "COVERAGE_ERROR",
    "COVERAGE_SHRINK",
    "DataUnavailable",
    "LandingError",
    "FixtureNotFound",
    "CoverageError",
    "BarRowError",
    "PayloadTruncated",
    "load_csv",
    "load_bars",
    "load_fixture_daily",
    "is_product_code",
    "data_provenance",
    "read_provenance",
]


class FixtureNotFound(LandingError):
    """The local file that should serve this symbol does not exist."""

    code = "fixture_not_found"


class CoverageError(LandingError):
    """The file exists but does not span the requested window."""

    code = "coverage_missing"


# ---------------------------------------------------------------------------
# CSV reading
# ---------------------------------------------------------------------------
def _rows_of(path: str) -> List[Dict[str, object]]:
    if not os.path.isfile(path):
        raise FixtureNotFound(
            f"找不到行情文件：{path}",
            hint=("本技能不联网取数。需要这个标的的日线时：\n"
                  "① agent 调 mcp__pandadata__call_pandadata method=get_future_daily\n"
                  '   params={"start_date": "<YYYYMMDD>", "end_date": "<YYYYMMDD>", '
                  '"symbol": "<CONTRACT>"}\n'
                  "② 把返回载荷原样写成 tests/fixtures/raw/get_future_daily__<label>.json\n"
                  "③ python3 scripts/mcp_landing.py --build\n"
                  "（离线跑内置样例请用 --fixture / --csv，不需要上面三步）"),
            path=os.path.relpath(path, ROOT))
    bars: List[Dict[str, object]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [f for f in ("date", "open", "high", "low", "close")
                   if f not in (reader.fieldnames or [])]
        if missing:
            raise DataUnavailable(f"CSV missing columns: {missing}")
        for row in reader:
            try:
                bars.append({
                    "date": str(row["date"]).replace("-", "")[:8],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0.0),
                })
            except (TypeError, ValueError) as exc:
                raise DataUnavailable(f"bad CSV row {row!r}: {exc}") from exc
    if not bars:
        raise DataUnavailable(f"CSV has no rows: {path}")
    return sorted(bars, key=lambda b: b["date"])


def load_csv(path: str) -> List[Dict[str, object]]:
    """Load bars from a CSV with a ``date,open,high,low,close[,volume]`` header."""
    return _rows_of(path)


def _rel(path: str) -> str:
    """Record files relative to the skill root: an install path is not provenance.

    Paths outside the skill (an explicit ``--landed-dir`` elsewhere) keep their
    absolute form rather than a ``../../..`` crawl, which would leak the layout
    of the caller without identifying the file.

    This is for **diagnostics**: a person reading an error needs a path they can
    open. Anything that goes *into a shipped report* must use
    :func:`portable_path` instead.
    """
    absolute = os.path.abspath(path)
    if not absolute.startswith(ROOT + os.sep):
        return absolute.replace(os.sep, "/")
    return os.path.relpath(absolute, ROOT).replace(os.sep, "/")


_ABSOLUTE_MARKERS = ("/Use" + "rs/", "/ho" + "me/", "/tm" + "p/", "/pr" + "ivate/",
                     "/va" + "r/")


def portable_path(path: str, base: Optional[str] = None) -> str:
    """A file identity that still means something on someone else's machine.

    The shipped real-data anchor used to record paths under a one-off temporary
    landing directory in ``data.symbols.*.files`` and ``data.built_files``: a
    directory that exists on nobody's machine but the one that produced it, so
    nobody could re-run the acceptance numbers the anchor publishes. Those paths
    never tripped a check either, because the install-path guard watched only
    documents, and only the home-directory prefixes — never a temp prefix, and
    never ``baselines/`` at all.

    Normalisation order: inside the skill -> root-relative; inside ``base`` (the
    landing directory) -> base-relative, which is exactly the name a rebuild
    produces; anything else -> the bare file name.
    """
    absolute = os.path.abspath(path)
    if absolute.startswith(ROOT + os.sep):
        out = os.path.relpath(absolute, ROOT).replace(os.sep, "/")
    elif base and absolute.startswith(os.path.abspath(base) + os.sep):
        out = os.path.relpath(absolute, os.path.abspath(base)).replace(os.sep, "/")
    else:
        out = os.path.basename(absolute)
    # Belt and braces: a shipped report must not carry a machine path, so if
    # normalisation ever hands one back, degrade to the file name.
    if out.startswith("/") or any(m in out for m in _ABSOLUTE_MARKERS):
        return os.path.basename(absolute)
    return out


def portable_dir(path: str) -> Dict[str, Any]:
    """How to describe a data directory in a report: a name, plus where it lives.

    The directory itself is provenance the reader needs (which landing dir was
    used), but an absolute one is not reproducible by anyone else, so it is
    reported as a name with an explicit flag rather than as a path.
    """
    absolute = os.path.abspath(path)
    if absolute.startswith(ROOT + os.sep):
        return {"landed_dir": os.path.relpath(absolute, ROOT).replace(os.sep, "/"),
                "landed_dir_outside_skill": False}
    return {"landed_dir": os.path.basename(absolute.rstrip(os.sep)),
            "landed_dir_outside_skill": True}


# ---------------------------------------------------------------------------
# Provenance sidecar (written by scripts/mcp_landing.py --build)
# ---------------------------------------------------------------------------
def read_provenance(fixtures_dir: str) -> Dict[str, Any]:
    """``provenance.json`` for this directory, or ``{}`` for hand-made fixtures."""
    path = os.path.join(fixtures_dir, PROVENANCE_NAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise FixtureNotFound(f"{_rel(path)} 不是合法 JSON：{exc}",
                              hint="删掉它再跑 python3 scripts/mcp_landing.py --build。",
                              path=_rel(path)) from exc
    return data if isinstance(data, dict) else {}


def _gap_hint(symbol: str, method: str) -> str:
    """The fix for a coverage gap, spelled as the MCP call that produces it."""
    if "+" in method:      # dominant series: the mapping *and* the legs can be stale
        call = ('mcp__pandadata__call_pandadata method=get_future_dominant '
                'params={"underlying_symbol": "' + symbol + '", ...} 以及每个主力合约的 '
                'method=get_future_daily params={"symbol": "<CONTRACT>", ...}')
    else:
        call = ('mcp__pandadata__call_pandadata method=get_future_daily '
                'params={"symbol": "' + symbol + '", "start_date": ..., "end_date": ...}')
    return ("按缺口区间补取数后重新构建：" + call +
            " → 原样落盘 tests/fixtures/raw/ → python3 scripts/mcp_landing.py --build；"
            "只想用已覆盖的子区间出结论，就加 --coverage shrink（报告会记录降级）。")


def _file_provenance(provenance: Dict[str, Any], name: str) -> Dict[str, Any]:
    entry = (provenance.get("files") or {}).get(name)
    return entry if isinstance(entry, dict) else {}


def _window_of(bars: List[Dict[str, object]]) -> Dict[str, Any]:
    dates = [b["date"] for b in bars]
    return {"first": dates[0], "last": dates[-1], "dates": len(dates)}


def _coverage_meta(symbol: str, start: str, end: str, bars: List[Dict[str, object]],
                   *, coverage: str, source_files: Sequence[str],
                   provenance_entry: Dict[str, Any], method: str) -> Dict[str, Any]:
    """Build the metadata block every consumer reads, including the shrink record."""
    covered = [b["date"] for b in bars]
    available = _window_of(bars) if bars else {}
    gaps: List[str] = []
    if covered:
        if start and covered[0] > norm_date(start):
            gaps.append(f"{start}..{covered[0]}")
        if end and covered[-1] < norm_date(end):
            gaps.append(f"{covered[-1]}..{end}")
    shrunk = bool(gaps) and coverage == COVERAGE_SHRINK
    if gaps and coverage == COVERAGE_ERROR:
        raise CoverageError(
            f"{symbol} 的本地行情只覆盖 {available.get('first')}..{available.get('last')}，"
            f"不满足请求窗口 {start}..{end}（缺口 {', '.join(gaps)}）",
            hint=_gap_hint(symbol, method),
            symbol=symbol, missing=gaps, files=list(source_files),
            available=available, requested={"start": start, "end": end})
    meta: Dict[str, Any] = {
        "method": method,
        "symbol": symbol,
        "requested": {"start": start or None, "end": end or None},
        "available": available,
        "effective": {"start": (max(norm_date(start), covered[0]) if start and covered else covered[0])
                      if covered else None,
                      "end": (min(norm_date(end), covered[-1]) if end and covered else covered[-1])
                      if covered else None},
        "coverage_missing": gaps,
        "coverage_shrunk": shrunk,
        "coverage_policy": coverage,
        "files": list(source_files),
        "partial": bool(provenance_entry.get("partial")),
        "partial_payloads": (provenance_entry.get("payloads") or [])
        if provenance_entry.get("partial") else [],
        "source_payloads": provenance_entry.get("payloads") or [],
        "requested_window": provenance_entry.get("requested_window") or {},
    }
    if not provenance_entry:
        meta["provenance_missing"] = True      # hand-made CSVs: origin unverifiable
    return meta


# ---------------------------------------------------------------------------
# Single-instrument daily series
# ---------------------------------------------------------------------------
def load_fixture_daily(symbol: str, start: str, end: str,
                       fixtures_dir: str = DEFAULT_LANDED_DIR, *,
                       coverage: str = COVERAGE_ERROR) -> Tuple[List[Dict[str, object]],
                                                                 Dict[str, Any]]:
    """Bars for one instrument from ``bars_<SYMBOL>.csv`` in this skill's layout."""
    name = f"bars_{mcp_landing.safe_name(symbol)}.csv"
    path = os.path.join(fixtures_dir, name)
    provenance = read_provenance(fixtures_dir)
    bars = [b for b in _rows_of(path)
            if (not start or b["date"] >= norm_date(start))
            and (not end or b["date"] <= norm_date(end))]
    if not bars:
        raise PayloadEmpty(
            f"{_rel(path)} 在 {start}..{end} 区间内没有任何行",
            hint="换个区间，或按该区间的缺口重新取数后 --build。",
            symbol=symbol, file=name)
    return bars, _coverage_meta(symbol, start, end, bars, coverage=coverage,
                                source_files=[_rel(path)],
                                provenance_entry=_file_provenance(provenance, name),
                                method=mcp_landing.FUTURE_DAILY)


# ---------------------------------------------------------------------------
# Dominant-contract stitching
# ---------------------------------------------------------------------------
def _dominant_map(product: str, start: str, end: str, fixtures_dir: str
                  ) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """``({date: contract}, provenance entry)`` from ``dominant_<PRODUCT>.csv``."""
    name = f"dominant_{mcp_landing.safe_name(product)}.csv"
    path = os.path.join(fixtures_dir, name)
    if not os.path.isfile(path):
        raise FixtureNotFound(
            f"找不到主力合约映射文件：{_rel(path)}",
            hint=("① agent 调 mcp__pandadata__call_pandadata method=get_future_dominant\n"
                  '   params={"underlying_symbol": "' + product + '", '
                  '"start_date": "<YYYYMMDD>", "end_date": "<YYYYMMDD>"}\n'
                  "   （JSON 通道，返回完整数组：date,symbol,trading_code,underlying_symbol）\n"
                  "② 原样落盘 tests/fixtures/raw/get_future_dominant__" + product + ".json\n"
                  "③ python3 scripts/mcp_landing.py --build"),
            path=_rel(path))
    by_date: Dict[str, str] = {}
    conflicts: List[Dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        columns = {str(c).lower(): c for c in (reader.fieldnames or [])}
        date_key = columns.get("date") or columns.get("trade_date") or columns.get("nature_date")
        contract_key = next((columns[c] for c in ("contract", "symbol", "trading_code",
                                                  "dominant_id", "code") if c in columns), None)
        if not date_key or not contract_key:
            raise BarRowError(
                f"{_rel(path)} 缺少 date 或 contract 列（实际列：{sorted(columns)}）",
                hint="用 python3 scripts/mcp_landing.py --build 重建该文件（列名 date,contract）。",
                symbol=product, file=_rel(path))
        for row in reader:
            date = norm_date(row.get(date_key))
            contract = str(row.get(contract_key) or "").strip()
            if len(date) != 8 or not contract:
                continue
            if date in by_date and by_date[date] != contract:
                conflicts.append({"date": date, "kept": by_date[date], "ignored": contract})
                continue
            by_date.setdefault(date, contract)
    if not by_date:
        raise PayloadEmpty(f"{_rel(path)} 里没有可用的主力合约映射行",
                           hint="重新取 get_future_dominant 并 --build。",
                           symbol=product, file=_rel(path))
    window = {d: c for d, c in by_date.items()
              if (not start or d >= norm_date(start)) and (not end or d <= norm_date(end))}
    if not window:
        raise CoverageError(
            f"{product} 的主力合约映射不覆盖 {start}..{end}"
            f"（本地有 {min(by_date)}..{max(by_date)}）",
            hint="按该区间重新取 get_future_dominant 后 --build，或缩小请求区间。",
            symbol=product, missing=[f"{start}..{end}"], file=_rel(path))
    entry = _file_provenance(read_provenance(fixtures_dir), name)
    return window, {"entry": entry, "file": _rel(path), "full_span": [min(by_date), max(by_date)],
                    "conflicts": conflicts}


def _stitch_dominant(product: str, start: str, end: str, fixtures_dir: str,
                     coverage: str) -> Tuple[List[Dict[str, object]], Dict[str, Any]]:
    """Dominant-contract series at *unadjusted* prices, built from local files.

    Why not a back-adjusted series: it shifts historical prices (e.g. an RB bar
    reading 4776 instead of the 3887 actually traded), so a numeric level quoted
    in an opinion would compare against a price the author never saw. Instead
    the dominant contract is resolved **per day** from the mapping file, each
    contract's own bars are read from ``bars_<CONTRACT>.csv``, and the segments
    are stitched. Level continuity across a roll is approximate by construction,
    which is stated in ``applicability``.

    The mapping owns the date->contract decision: a date never takes a bar from a
    contract that was not dominant on it. (The pre-MCP code de-duplicated by the
    contract's ``min..max`` window, which mis-attributed a date whenever a
    contract was dominant in two separate periods.) A missing segment is a
    coverage failure, not a silently dropped leg — unless ``--coverage shrink``.
    """
    by_date, map_info = _dominant_map(product, start, end, fixtures_dir)
    dates_by_contract: Dict[str, List[str]] = {}
    for date, contract in by_date.items():
        dates_by_contract.setdefault(contract, []).append(date)

    bars_by_date: Dict[str, Dict[str, object]] = {}
    contracts: List[Dict[str, Any]] = []
    missing: List[Dict[str, Any]] = []
    files: List[str] = [map_info["file"]]
    source_payloads: List[str] = list(map_info["entry"].get("payloads") or [])
    partial_payloads: List[str] = (list(map_info["entry"].get("payloads") or [])
                                   if map_info["entry"].get("partial") else [])

    for contract in sorted(dates_by_contract):
        dates = sorted(dates_by_contract[contract])
        try:
            piece, piece_meta = load_fixture_daily(contract, dates[0], dates[-1],
                                                  fixtures_dir, coverage=coverage)
        except (FixtureNotFound, CoverageError) as exc:
            if coverage == COVERAGE_SHRINK:
                missing.append({"contract": contract,
                                "window": {"start": dates[0], "end": dates[-1]},
                                "dominant_dates": len(dates), "reason": exc.code,
                                "detail": exc.message})
                continue
            raise CoverageError(
                f"{product} 的主力序列需要合约 {contract} 在 {dates[0]}..{dates[-1]} 的日线，"
                f"本地没有（{exc.code}）。",
                hint=("① agent 调 mcp__pandadata__call_pandadata method=get_future_daily "
                      'params={"symbol": "' + contract + '", "start_date": "' + dates[0] +
                      '", "end_date": "' + dates[-1] + '"}\n'
                      "② 原样落盘 tests/fixtures/raw/get_future_daily__" + contract + ".json\n"
                      "③ python3 scripts/mcp_landing.py --build\n"
                      "确实只想用已有片段拼，就加 --coverage shrink（缺口会记录在案）。"),
                symbol=product, contract=contract, cause=exc.code,
                missing_dates=[dates[0], dates[-1]]) from exc
        wanted = set(dates)
        taken = 0
        for bar in piece:
            if bar["date"] in wanted:
                stamped = dict(bar)
                stamped["contract"] = contract
                bars_by_date[bar["date"]] = stamped
                taken += 1
        files.extend(piece_meta["files"])
        source_payloads.extend(piece_meta.get("source_payloads") or [])
        if piece_meta.get("partial"):
            partial_payloads.extend(piece_meta["partial_payloads"])
        contracts.append({"contract": contract, "dominant_from": dates[0],
                          "dominant_to": dates[-1], "dominant_dates": len(dates),
                          "bars_used": taken, "partial": bool(piece_meta.get("partial"))})

    window = set(by_date)
    absent = sorted(window - set(bars_by_date))
    if absent and coverage == COVERAGE_ERROR:
        raise CoverageError(
            f"{product} 在 {start}..{end} 内有 {len(absent)} 个主力日没有对应日线"
            f"（首 {absent[0]}，末 {absent[-1]}）",
            hint="按缺失日期补取对应合约的 get_future_daily 后 --build；"
                 "或加 --coverage shrink 明确放弃这些日期（会记录在 missing_dates）。",
            symbol=product, missing_dates=absent[:10])

    if not bars_by_date:
        raise PayloadEmpty(
            f"{product} 的主力序列在 {start}..{end} 一段日线都没有",
            hint="先取映射再取各合约日线：get_future_dominant → get_future_daily → --build。",
            symbol=product)

    bars = [bars_by_date[d] for d in sorted(bars_by_date)]
    ordered = [b["contract"] for b in bars]
    rolls = sum(1 for a, b in zip(ordered, ordered[1:]) if a != b)
    meta = _coverage_meta(product, start, end, bars, coverage=coverage,
                          source_files=sorted(set(files)),
                          provenance_entry=map_info["entry"],
                          method=f"{mcp_landing.FUTURE_DOMINANT}+{mcp_landing.FUTURE_DAILY}")
    meta.update({
        "contracts": contracts,
        "roll_count": rolls,
        "missing_dates": absent,
        "missing_contract_segments": missing,
        "dominant_conflicts": map_info["conflicts"],
        "partial": bool(map_info["entry"].get("partial")) or any(c["partial"] for c in contracts),
        "partial_payloads": sorted(set(partial_payloads)),
        "source_payloads": sorted(set(source_payloads)),
        "coverage_shrunk": bool(absent or missing or map_info["conflicts"]
                                or meta["coverage_shrunk"]),
    })
    return bars, meta


def is_product_code(symbol: str) -> bool:
    """``RB`` / ``I`` look like products (resolve the dominant series); ``RB2610`` does not."""
    return "." not in symbol and not any(c.isdigit() for c in symbol)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def load_bars(symbol: str, start: str, end: str, csv_path: Optional[str] = None,
              fixtures_dir: str = DEFAULT_LANDED_DIR,
              coverage: str = COVERAGE_ERROR) -> Dict[str, object]:
    """Return ``{"bars", "source", "symbol", "data"}``.

    ``source`` is ``"csv"`` for a caller-supplied file (what ``--fixture`` and
    ``--csv`` do) and ``"landed"`` for bars built from landed MCP payloads;
    ``data["method"]`` says whether the dominant series or one contract was
    used. ``data`` always carries the provenance the report needs: which files,
    which payloads behind them, whether anything was partial or shrunk.
    """
    if csv_path:
        bars = load_csv(csv_path)
        return {"bars": bars,
                "source": "csv",
                "symbol": symbol,
                "data": {"method": None, "files": [_rel(csv_path)], "partial": False,
                         "partial_payloads": [], "coverage_missing": [],
                         "coverage_shrunk": False, "coverage_policy": coverage}}
    if is_product_code(symbol):
        bars, meta = _stitch_dominant(symbol, start, end, fixtures_dir, coverage)
    else:
        bars, meta = load_fixture_daily(symbol, start, end, fixtures_dir, coverage=coverage)
    # Where the landed files came from, so provenance can name them relative to
    # that directory instead of quoting a path that only existed on this machine.
    meta["base_dir"] = fixtures_dir
    return {"bars": bars, "source": "landed", "symbol": symbol, "data": meta}


def _portable_files(values: Any, base: Optional[str] = None) -> List[str]:
    """Normalise only genuinely absolute entries.

    ``_rel`` already returns root-relative names for in-skill files, and
    re-resolving those with ``abspath`` would depend on the current directory
    and silently turn ``tests/fixtures/bars_I.csv`` into ``bars_I.csv``.
    """
    out: List[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        out.append(portable_path(value, base) if os.path.isabs(value)
                   else value.replace(os.sep, "/"))
    return out


def data_provenance(result: Dict[str, object]) -> Dict[str, Any]:
    """Flatten ``load_bars`` output into the lines worth printing or reporting."""
    meta = result.get("data") or {}
    out: Dict[str, Any] = {"source": result.get("source"), "symbol": result.get("symbol"),
                           "bars": len(result.get("bars") or [])}
    out.update({
        "method": meta.get("method"),
        "files": _portable_files(meta.get("files", []), meta.get("base_dir")),
        "requested": meta.get("requested"),
        "available": meta.get("available"),
        "effective": meta.get("effective"),
        "partial": bool(meta.get("partial")),
        "partial_payloads": meta.get("partial_payloads", []),
        "source_payloads": meta.get("source_payloads", []),
        "coverage_missing": meta.get("coverage_missing", []),
        "coverage_shrunk": bool(meta.get("coverage_shrunk")),
        "coverage_policy": meta.get("coverage_policy"),
    })
    for key in ("contracts", "roll_count", "missing_dates", "missing_contract_segments",
                "dominant_conflicts", "provenance_missing"):
        if meta.get(key):
            out[key] = meta[key]
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _emit_error(exc: BaseException) -> int:
    if isinstance(exc, LandingError):
        payload = exc.as_dict()
    else:
        payload = {"code": getattr(type(exc), "code", "data_unavailable"), "message": str(exc)}
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
    return 3


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Read daily / dominant futures bars from this skill's own CSV files "
                    "(bundled fixtures, or bars built by scripts/mcp_landing.py). "
                    "Never touches the network.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True, help="product code (RB) or contract (RB2610)")
    ap.add_argument("--start", default="20240101")
    ap.add_argument("--end", default="20241231")
    ap.add_argument("--csv", help="read this CSV instead of the fixtures directory")
    ap.add_argument("--fixtures-dir", default=DEFAULT_LANDED_DIR,
                    help="directory holding bars_<SYMBOL>.csv / dominant_<PRODUCT>.csv "
                         "(default: %(default)s)")
    ap.add_argument("--coverage", choices=COVERAGE_POLICIES, default=COVERAGE_ERROR,
                    help="policy when the files do not span the requested window "
                         "(default: error; shrink uses the covered sub-range and records it)")
    ap.add_argument("--out", help="write the resulting bars as CSV here")
    ap.add_argument("--provenance", action="store_true",
                    help="print only the provenance JSON")
    args = ap.parse_args(argv)

    try:
        loaded = load_bars(args.symbol, args.start, args.end, csv_path=args.csv,
                           fixtures_dir=os.path.abspath(os.path.expanduser(args.fixtures_dir)),
                           coverage=args.coverage)
    except DataUnavailable as exc:            # covers every LandingError too
        return _emit_error(exc)

    bars = loaded["bars"]
    prov = data_provenance(loaded)
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(list(BAR_FIELDS))
            for b in bars:
                writer.writerow([b[f] for f in BAR_FIELDS])
    if args.provenance:
        print(json.dumps(prov, ensure_ascii=False, indent=2))
    else:
        flag = " [PARTIAL]" if prov.get("partial") else ""
        shrunk = " [COVERAGE SHRUNK]" if prov.get("coverage_shrunk") else ""
        print(f"{args.symbol}: {len(bars)} bars {bars[0]['date']}..{bars[-1]['date']} "
              f"via {loaded['source']} (method={prov.get('method')}){flag}{shrunk}")
        print(json.dumps(prov, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
