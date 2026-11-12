"""Market-data adapter: panda_data first, local CSV fallback second.

Design constraints
------------------
* No look-ahead: only bars strictly after ``published_at`` are ever returned to
  the backtester; this module itself performs no filtering, it returns a sorted
  series and the backtester owns the cut-off rule.
* No silent fallback: if panda_data login fails and no CSV is supplied, the
  caller gets an explicit ``DataUnavailable`` rather than synthetic numbers.

Credentials resolution order (never written into the repo):

1. ``PANDA_DATA_USERNAME`` / ``PANDA_DATA_PASSWORD`` / ``PANDA_DATA_BASE_URL``
2. legacy ``DEFAULT_USERNAME`` / ``DEFAULT_PASSWORD`` / ``JAVA_SERVICE_BASE_URL``
3. ``~/.pandadata/pandadata.env`` (``KEY=VALUE`` per line, ``export`` prefix allowed)
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Dict, List, Optional

BAR_FIELDS = ("date", "open", "high", "low", "close", "volume")

ENV_FILE = Path.home() / ".pandadata" / "pandadata.env"


class DataUnavailable(RuntimeError):
    """Raised when neither panda_data nor a CSV fallback can serve the request."""


def _load_env_file() -> None:
    """Inject ``~/.pandadata/pandadata.env`` into the process env (setdefault)."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env(*names: str) -> Optional[str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    before = set(os.environ)
    _load_env_file()
    if set(os.environ) != before:
        for name in names:
            value = os.environ.get(name)
            if value:
                return value
    return None


def credentials() -> Dict[str, Optional[str]]:
    """Return the resolved credential triple, without logging the values."""
    return {
        "username": _env("PANDA_DATA_USERNAME", "PANDADATA_USERNAME", "DEFAULT_USERNAME"),
        "zinfoid": _env("PANDA_DATA_PASSWORD", "PANDADATA_PASSWORD", "DEFAULT_PASSWORD"),
        "base_url": _env("PANDA_DATA_BASE_URL", "PANDADATA_BASE_URL", "JAVA_SERVICE_BASE_URL"),
    }


def credentials_source() -> str:
    """Which layer supplied the credentials — useful in the acceptance report."""
    creds = credentials()
    missing = [k for k, v in creds.items() if not v]
    if missing:
        return "missing:" + ",".join(missing)
    if _env("PANDA_DATA_USERNAME", "PANDADATA_USERNAME"):
        return "env"
    if ENV_FILE.exists():
        return "env_file"
    return "legacy_env"


def load_csv(path: str) -> List[Dict[str, object]]:
    """Load bars from a CSV with a ``date,open,high,low,close[,volume]`` header."""
    if not os.path.isfile(path):
        raise DataUnavailable(f"CSV fixture not found: {path}")
    bars: List[Dict[str, object]] = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [f for f in ("date", "open", "high", "low", "close") if f not in (reader.fieldnames or [])]
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


def load_panda(symbol: str, start: str, end: str,
               use_dominant: bool = True) -> List[Dict[str, object]]:
    """Fetch daily bars through ``panda_data``.

    ``symbol`` is a product code such as ``RB`` (dominant series) or a concrete
    contract such as ``RB2610``.
    """
    try:
        import panda_data  # type: ignore
    except ImportError as exc:
        raise DataUnavailable(
            "panda_data is not installed; install panda-data==1.0.6 or pass a CSV fixture"
        ) from exc

    creds = credentials()
    if not all(creds.values()):
        missing = [k for k, v in creds.items() if not v]
        raise DataUnavailable(
            "panda_data credentials missing: %s; set PANDA_DATA_USERNAME / "
            "PANDA_DATA_PASSWORD / PANDA_DATA_BASE_URL or write ~/.pandadata/pandadata.env"
            % ", ".join(missing)
        )
    try:
        panda_data.init_token(
            username=creds["username"],
            password=creds["zinfoid"],
            base_url=creds["base_url"],
            country="CN",
        )
    except Exception as exc:  # noqa: BLE001 - surface the SDK message verbatim
        raise DataUnavailable(f"panda_data login failed: {exc}") from exc

    try:
        if use_dominant:
            raw = _fetch_raw_dominant(panda_data, symbol, start, end)
        else:
            raw = panda_data.get_future_daily(symbol=symbol, start_date=start, end_date=end)
    except DataUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DataUnavailable(f"panda_data query failed for {symbol}: {exc}") from exc

    if raw is None or len(raw) == 0:
        raise DataUnavailable(f"panda_data returned no rows for {symbol} {start}..{end}")

    rows = raw.to_dict("records") if hasattr(raw, "to_dict") else list(raw)
    bars: List[Dict[str, object]] = []
    for row in rows:
        lowered = {str(k).lower(): v for k, v in row.items()}
        date = lowered.get("trade_date") or lowered.get("date")
        if date is None:
            raise DataUnavailable(f"panda_data row has no date column: {sorted(lowered)}")
        for field in ("open", "high", "low", "close"):
            if lowered.get(field) in (None, "", 0, 0.0):
                raise DataUnavailable(
                    f"panda_data row for {symbol} on {date} has empty {field}; refusing to "
                    f"simulate on zero prices"
                )
        bars.append({
            "date": str(date).replace("-", "")[:8],
            "open": float(lowered["open"]),
            "high": float(lowered["high"]),
            "low": float(lowered["low"]),
            "close": float(lowered["close"]),
            "volume": float(lowered.get("volume") or 0.0),
        })
    return sorted(bars, key=lambda b: b["date"])


def _fetch_raw_dominant(client, symbol: str, start: str, end: str):
    """Dominant-contract series at *unadjusted* prices.

    Why not ``get_future_daily_post``: its back-adjusted series shifts historical
    prices (e.g. RB 2024-01-10 reads 4776 instead of the real 3887), so a numeric
    level quoted in an opinion would compare against a price the author never saw.
    Instead we resolve the dominant contract per day and read that contract's own
    bars, stitching the segments. Level continuity across a roll is approximate by
    construction, which is stated in ``applicability``.

    Returns a pandas DataFrame with ``date`` and OHLCV columns, or raises
    ``DataUnavailable``.
    """
    mapping = client.get_future_dominant(underlying_symbol=symbol, start_date=start, end_date=end)
    if mapping is None or len(mapping) == 0:
        raise DataUnavailable(f"no dominant-contract mapping for {symbol} {start}..{end}")

    records = mapping.to_dict("records") if hasattr(mapping, "to_dict") else list(mapping)
    contract_dates: Dict[str, List[str]] = {}
    for row in records:
        lowered = {str(k).lower(): v for k, v in row.items()}
        date = str(lowered.get("date") or "").replace("-", "")[:8]
        code = lowered.get("symbol") or lowered.get("dominant_id")
        if date and code:
            contract_dates.setdefault(str(code), []).append(date)
    if not contract_dates:
        raise DataUnavailable(f"dominant mapping for {symbol} has no usable rows")

    pieces = []
    for code, dates in contract_dates.items():
        frame = client.get_future_daily(
            symbol=[code], start_date=min(dates), end_date=max(dates)
        )
        if frame is None or len(frame) == 0:
            continue
        pieces.append(frame)
    if not pieces:
        raise DataUnavailable(f"no bars returned for the dominant contracts of {symbol}")

    import pandas as pd  # panda_data already depends on it

    merged = pd.concat(pieces, ignore_index=True)
    merged = merged.drop_duplicates(subset=["date"], keep="first")
    return merged.sort_values("date")


def load_bars(symbol: str, start: str, end: str,
              csv_path: Optional[str] = None) -> Dict[str, object]:
    """Return ``{"bars": [...], "source": "panda"|"csv", "symbol": str}``."""
    if csv_path:
        return {"bars": load_csv(csv_path), "source": "csv", "symbol": symbol}
    bars = load_panda(symbol, start, end, use_dominant="." not in symbol and not any(c.isdigit() for c in symbol))
    return {"bars": bars, "source": "panda", "symbol": symbol}