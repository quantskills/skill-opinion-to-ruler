"""Tests for the landing layer: agent-landed MCP payloads -> this skill's own CSV schema.

What this file pins down, in order of how much it hurts to get wrong:

1. **The truncation guard actually fails.** A parquet-channel payload whose
   ``truncated`` flag is set, or whose ``row_count < total_rows``, must exit
   non-zero and must not leave a half-built directory behind. A guard that only
   logs is not a guard.
2. **``--allow-partial`` leaves evidence.** If truncated data is admitted, the
   provenance sidecar and the downstream report both say so.
3. **The built files are this skill's pre-existing format** (``bars_<SYMBOL>.csv``
   with ``date,open,high,low,close,volume``), readable by ``load_csv``/``--fixture``.
4. **Dominant-contract stitching attributes each date to the contract that was
   actually dominant on it** — not to whatever contract's min..max window happens
   to contain it.
5. **Self-containment**: no other skill's name, script or directory convention,
   no network egress, no hardcoded install path.

Payloads here are synthesised in the two documented response shapes; nothing in
this file talks to the network, and nothing writes inside the skill directory.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import data_loader  # noqa: E402
import mcp_landing  # noqa: E402
from data_loader import DataUnavailable, load_bars  # noqa: E402

START, END = "20240102", "20240129"
DATES = [d for d in ("20240102", "20240103", "20240104", "20240105", "20240108",
                     "20240109", "20240110", "20240111", "20240112", "20240115")
          if START <= d <= END]


# ---------------------------------------------------------------------------
# Payload synthesis
# ---------------------------------------------------------------------------
def daily_rows(symbol: str, dates: List[str], base: float = 3600.0) -> List[Dict[str, Any]]:
    return [{"symbol": symbol, "date": d, "open": base + i, "high": base + i + 1,
             "low": base + i - 1, "close": base + i + 0.5, "volume": 10000 + i}
            for i, d in enumerate(dates)]


def parquet_payload(rows: List[Dict[str, Any]], params: Dict[str, Any], *,
                    total_rows: int | None = None, truncated: bool = False) -> Dict[str, Any]:
    """The parquet channel: a *preview*, so it carries the completeness fields."""
    return {"rows": rows, "params": params, "row_count": len(rows),
            "total_rows": total_rows if total_rows is not None else len(rows),
            "truncated": truncated}


def json_payload(rows: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON channel: a complete array, and no truncation fields at all."""
    return {"data": rows, "params": params}


def land(raw_dir: str, name: str, payload: Any) -> str:
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    return path


@pytest.fixture
def complete_landing(tmp_path):
    """A minimal but real landing set: dominant mapping + two contracts + one product."""
    raw = str(tmp_path / "raw")
    landed = str(tmp_path / "landed")
    front, back = DATES[:6], DATES[6:]
    mapping = ([{"date": d, "symbol": "RB2405", "trading_code": "RB2405",
                 "underlying_symbol": "RB"} for d in front] +
               [{"date": d, "symbol": "RB2410", "trading_code": "RB2410",
                 "underlying_symbol": "RB"} for d in back])
    land(raw, "get_future_dominant__RB.json",
         json_payload(mapping, {"underlying_symbol": "RB", "start_date": DATES[0],
                               "end_date": DATES[-1]}))
    land(raw, "get_future_daily__RB2405.json",
         parquet_payload(daily_rows("RB2405", front), {"symbol": "RB2405",
                                                       "start_date": front[0],
                                                       "end_date": front[-1]}))
    land(raw, "get_future_daily__RB2410.json",
         parquet_payload(daily_rows("RB2410", back, 3700.0), {"symbol": "RB2410",
                                                              "start_date": back[0],
                                                              "end_date": back[-1]}))
    land(raw, "get_future_daily__I2501.json",
         parquet_payload(daily_rows("I2501", DATES, 800.0), {"symbol": "I2501",
                                                             "start_date": DATES[0],
                                                             "end_date": DATES[-1]}))
    land(raw, "get_future_dominant__I.json",
         json_payload([{"date": d, "symbol": "I2501", "trading_code": "I2501",
                        "underlying_symbol": "I"} for d in DATES],
                       {"underlying_symbol": "I", "start_date": DATES[0],
                        "end_date": DATES[-1]}))
    return {"raw": raw, "landed": landed, "front": front, "back": back}


def build(landing: Dict[str, Any], *, allow_partial: bool = False,
          start: str = "", end: str = "", symbols=None) -> Dict[str, Any]:
    return mcp_landing.build(landing["raw"], landing["landed"],
                             allow_partial=allow_partial, start=start, end=end,
                             symbols=symbols)


def read_csv_rows(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# 1. The truncation guard must really fail
# ---------------------------------------------------------------------------
def test_truncated_flag_is_detected(tmp_path):
    rows = daily_rows("RB2405", DATES[:2])
    payload = parquet_payload(rows, {"symbol": "RB2405"}, total_rows=4000, truncated=True)
    meta = mcp_landing.check_payload(payload, rows, origin="get_future_daily__RB2405.json")
    assert meta["truncated"] is True and meta["partial"] is True
    assert meta["total_rows"] == 4000 and meta["row_count"] == 2
    with pytest.raises(mcp_landing.PayloadTruncated) as exc:
        mcp_landing.require_complete(meta, allow_partial=False,
                                     method=mcp_landing.FUTURE_DAILY)
    assert exc.value.code == "payload_truncated"
    assert "2000" in exc.value.hint           # the cap is named, not alluded to


def test_row_count_below_total_rows_is_detected_even_without_the_flag(tmp_path):
    """The silent case: a preview cut without anyone setting ``truncated``."""
    rows = daily_rows("RB2405", DATES[:2])
    payload = {"rows": rows, "params": {}, "row_count": 2, "total_rows": 4000}
    meta = mcp_landing.check_payload(payload, rows, origin="p.json")
    assert any("row_count(2) < total_rows(4000)" in r for r in meta["truncation_reasons"])
    with pytest.raises(mcp_landing.PayloadTruncated):
        mcp_landing.require_complete(meta, allow_partial=False, method="get_future_daily")


def test_json_channel_without_truncation_fields_passes(tmp_path):
    """Absence of the fields is not a truncation signal: that channel is complete."""
    rows = [{"date": d, "symbol": "RB2405", "underlying_symbol": "RB"} for d in DATES]
    payload = json_payload(rows, {"underlying_symbol": "RB"})
    meta = mcp_landing.check_payload(payload, rows, origin="get_future_dominant__RB.json")
    assert meta["truncated"] is False and meta["partial"] is False
    assert meta["row_count"] is None and meta["total_rows"] is None
    mcp_landing.require_complete(meta, allow_partial=False, method="get_future_dominant")


def test_build_refuses_truncated_payload_and_writes_nothing(tmp_path, complete_landing):
    """Guard, not a warning: a truncated payload must not become a data file."""
    victim = os.path.join(complete_landing["raw"], "get_future_daily__RB2405.json")
    with open(victim, encoding="utf-8") as fh:
        payload = json.load(fh)
    payload["truncated"] = True
    payload["total_rows"] = 5000
    with open(victim, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    with pytest.raises(mcp_landing.PayloadTruncated) as exc:
        build(complete_landing)
    assert exc.value.code == "payload_truncated"
    assert not os.path.exists(complete_landing["landed"]) or \
        os.listdir(complete_landing["landed"]) == []


def test_blank_price_is_refused_not_zero_filled(tmp_path, complete_landing):
    """A 0 price would let an opinion's level "compare" against a price nobody traded."""
    path = os.path.join(complete_landing["raw"], "get_future_daily__RB2405.json")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    payload["rows"][1]["close"] = ""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    with pytest.raises(mcp_landing.BarRowError) as exc:
        build(complete_landing)
    assert exc.value.code == "bad_bar_row"
    assert "close" in json.dumps(exc.value.detail, ensure_ascii=False)


def test_row_without_symbol_cannot_be_attributed(tmp_path, complete_landing):
    path = os.path.join(complete_landing["raw"], "get_future_daily__RB2405.json")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    del payload["rows"][0]["symbol"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    with pytest.raises(mcp_landing.BarRowError):
        build(complete_landing)


# ---------------------------------------------------------------------------
# 2. allow-partial must leave evidence behind
# ---------------------------------------------------------------------------
def test_allow_partial_admits_but_marks_provenance(tmp_path, complete_landing):
    path = os.path.join(complete_landing["raw"], "get_future_daily__RB2405.json")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    payload["truncated"], payload["total_rows"] = True, 5000
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)

    summary = build(complete_landing, allow_partial=True)
    assert summary["partial"] is True
    assert "get_future_daily__RB2405.json" in summary["partial_payloads"]

    with open(os.path.join(complete_landing["landed"], mcp_landing.PROVENANCE_NAME),
              encoding="utf-8") as fh:
        prov = json.load(fh)
    assert prov["allow_partial"] is True
    entry = prov["files"]["bars_RB2405.csv"]
    assert entry["partial"] is True
    assert "get_future_daily__RB2405.json" in entry["payloads"]
    assert prov["files"]["bars_I2501.csv"]["partial"] is False    # per-file, not blanket


def test_partial_marker_reaches_the_report(tmp_path, complete_landing):
    """Nothing downstream may present truncated data as if it were complete."""
    path = os.path.join(complete_landing["raw"], "get_future_daily__I2501.json")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    payload["row_count"], payload["total_rows"] = 2, 999
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    build(complete_landing, allow_partial=True)

    loaded = load_bars("I2501", DATES[0], DATES[-1],
                       fixtures_dir=complete_landing["landed"])
    prov = data_loader.data_provenance(loaded)
    assert prov["partial"] is True
    assert prov["partial_payloads"] == ["get_future_daily__I2501.json"]


# ---------------------------------------------------------------------------
# 3. Output is this skill's own pre-existing format
# ---------------------------------------------------------------------------
def test_built_csv_matches_the_skill_bar_schema(complete_landing):
    build(complete_landing)
    path = os.path.join(complete_landing["landed"], "bars_RB2405.csv")
    rows = read_csv_rows(path)
    assert list(rows[0].keys()) == list(data_loader.BAR_FIELDS)
    assert len(rows) == len(complete_landing["front"])
    assert rows[0]["date"] == complete_landing["front"][0]
    # and it loads through the long-standing fixture reader
    bars = data_loader.load_csv(path)
    assert bars[0]["close"] == float(rows[0]["close"])


def test_dominant_csv_is_date_and_contract(complete_landing):
    build(complete_landing)
    rows = read_csv_rows(os.path.join(complete_landing["landed"], "dominant_RB.csv"))
    assert list(rows[0].keys()) == ["date", "contract"]
    assert {r["contract"] for r in rows} == {"RB2405", "RB2410"}


def test_landing_output_stays_inside_the_skill_by_default():
    """The default landing directory is this skill's own fixtures tree."""
    assert mcp_landing.DEFAULT_RAW_DIR == os.path.join(ROOT, "tests", "fixtures", "raw")
    assert mcp_landing.DEFAULT_LANDED_DIR == os.path.join(ROOT, "tests", "fixtures", "landed")
    assert os.path.commonpath([mcp_landing.DEFAULT_RAW_DIR, ROOT]) == ROOT


def test_window_and_symbol_filters_apply(complete_landing):
    summary = build(complete_landing, start="20240108", symbols=["I2501"])
    assert "bars_RB2405.csv" not in summary["files"]
    rows = read_csv_rows(os.path.join(complete_landing["landed"], "bars_I2501.csv"))
    assert rows and all(r["date"] >= "20240108" for r in rows)
    assert summary["rows_outside_window"] > 0


def test_conflicting_duplicate_rows_are_reported_not_silently_overwritten(complete_landing):
    other = os.path.join(complete_landing["raw"], "get_future_daily__RB2405_dup.json")
    rows = daily_rows("RB2405", complete_landing["front"])
    rows[0]["close"] = 1.0
    land(complete_landing["raw"], os.path.basename(other),
         parquet_payload(rows, {"symbol": "RB2405"}))
    summary = build(complete_landing)
    assert "warnings" in summary and "冲突" in summary["warnings"][0]


# ---------------------------------------------------------------------------
# 4. Dominant-contract stitching attributes by day
# ---------------------------------------------------------------------------
def test_dominant_series_uses_the_contract_dominant_on_that_day(complete_landing):
    build(complete_landing)
    loaded = load_bars("RB", DATES[0], DATES[-1], fixtures_dir=complete_landing["landed"])
    by_date = {b["date"]: b["contract"] for b in loaded["bars"]}
    assert by_date[complete_landing["front"][0]] == "RB2405"
    assert by_date[complete_landing["back"][0]] == "RB2410"
    assert loaded["data"]["roll_count"] == 1


def test_a_date_never_borrows_bars_from_the_wrong_contract(tmp_path):
    """The regression: RB2405 dominant early, RB2410 mid, RB2405 again late.

    Window-based de-duplication (the pre-MCP behaviour) would let the middle
    period pick up RB2405 bars, because its min..max span covers everything.
    """
    raw, landed = str(tmp_path / "raw"), str(tmp_path / "landed")
    early, mid, late = DATES[:3], DATES[3:6], DATES[6:]
    mapping = ([{"date": d, "symbol": "RB2405", "underlying_symbol": "RB"} for d in early] +
               [{"date": d, "symbol": "RB2410", "underlying_symbol": "RB"} for d in mid] +
               [{"date": d, "symbol": "RB2405", "underlying_symbol": "RB"} for d in late])
    land(raw, "get_future_dominant__RB.json", json_payload(mapping, {"underlying_symbol": "RB"}))
    # RB2405 ships bars for the whole span, including the days RB2410 was dominant
    land(raw, "get_future_daily__RB2405.json",
         parquet_payload(daily_rows("RB2405", DATES), {"symbol": "RB2405"}))
    land(raw, "get_future_daily__RB2410.json",
         parquet_payload(daily_rows("RB2410", mid, 3700.0), {"symbol": "RB2410"}))
    mcp_landing.build(raw, landed)

    loaded = load_bars("RB", DATES[0], DATES[-1], fixtures_dir=landed)
    by_contract = {b["date"]: b["contract"] for b in loaded["bars"]}
    assert all(by_contract[d] == "RB2410" for d in mid)
    assert all(by_contract[d] == "RB2405" for d in early + late)
    assert loaded["data"]["roll_count"] == 2         # out and back counts twice


def test_missing_leg_for_a_dominant_period_is_a_coverage_failure(complete_landing):
    os.remove(os.path.join(complete_landing["raw"], "get_future_daily__RB2410.json"))
    build(complete_landing)
    with pytest.raises(DataUnavailable) as exc:
        load_bars("RB", DATES[0], DATES[-1], fixtures_dir=complete_landing["landed"])
    assert exc.value.code == "coverage_missing"
    assert "RB2410" in exc.value.message
    assert "get_future_daily" in exc.value.hint      # the hint names the fix


def test_shrink_policy_keeps_the_covered_part_and_records_the_gap(complete_landing):
    os.remove(os.path.join(complete_landing["raw"], "get_future_daily__RB2410.json"))
    build(complete_landing)
    loaded = load_bars("RB", DATES[0], DATES[-1], fixtures_dir=complete_landing["landed"],
                       coverage=data_loader.COVERAGE_SHRINK)
    prov = data_loader.data_provenance(loaded)
    assert prov["coverage_shrunk"] is True
    assert prov["missing_contract_segments"] and \
        prov["missing_contract_segments"][0]["contract"] == "RB2410"
    assert [b["date"] for b in loaded["bars"]] == complete_landing["front"]


# ---------------------------------------------------------------------------
# 5. Files are the only source: what happens when nothing is landed
# ---------------------------------------------------------------------------
def test_missing_landing_directory_names_the_three_steps(tmp_path):
    with pytest.raises(mcp_landing.LandingError) as exc:
        mcp_landing.build(str(tmp_path / "absent"), str(tmp_path / "landed"))
    assert exc.value.code == "landing_not_found"
    assert "mcp__pandadata__call_pandadata" in exc.value.hint
    assert "tests/fixtures/raw" in exc.value.hint     # the default location is named too
    assert "mcp_landing.py --build" in exc.value.hint


def test_missing_built_file_is_fixture_not_found(complete_landing):
    os.makedirs(complete_landing["landed"], exist_ok=True)
    with pytest.raises(DataUnavailable) as exc:
        load_bars("RB2499", DATES[0], DATES[-1], fixtures_dir=complete_landing["landed"])
    assert exc.value.code == "fixture_not_found"
    assert "mcp__pandadata__call_pandadata" in exc.value.hint


def test_payload_that_is_not_a_verbatim_response_is_unreadable(tmp_path):
    raw = str(tmp_path / "raw")
    land(raw, "get_future_daily__RB2405.json", {"note": "agent 转述的结论，不是返回体"})
    with pytest.raises(mcp_landing.LandingError) as exc:
        mcp_landing.build(raw, str(tmp_path / "landed"))
    assert exc.value.code == "payload_unreadable"


def test_empty_payload_is_not_treated_as_no_data(tmp_path):
    raw = str(tmp_path / "raw")
    land(raw, "get_future_daily__RB2405.json", parquet_payload([], {"symbol": "RB2405"}))
    with pytest.raises(mcp_landing.LandingError) as exc:
        mcp_landing.build(raw, str(tmp_path / "landed"))
    assert exc.value.code == "payload_empty"
    assert "mcp__pandadata__call_pandadata" in exc.value.hint


def test_rows_listed_as_columns_get_zipped(tmp_path):
    raw = str(tmp_path / "raw")
    cols = ["symbol", "date", "open", "high", "low", "close", "volume"]
    body = [["RB2405", DATES[0], 3600, 3610, 3590, 3605, 10],
            ["RB2405", DATES[1], 3601, 3611, 3591, 3606, 11]]
    land(raw, "get_future_daily__RB2405.json",
         {"columns": cols, "rows": body, "params": {}, "row_count": 2, "total_rows": 2})
    mcp_landing.build(raw, str(tmp_path / "landed"))
    assert len(read_csv_rows(os.path.join(str(tmp_path / "landed"),
                                          "bars_RB2405.csv"))) == 2


def test_provenance_absent_for_hand_made_csvs_is_flagged(tmp_path):
    """Users may bring their own bars_*.csv; then origin cannot be verified."""
    landed = str(tmp_path / "landed")
    os.makedirs(landed)
    with open(os.path.join(landed, "bars_RB2405.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(list(data_loader.BAR_FIELDS))
        for i, d in enumerate(DATES):
            writer.writerow([d, 10 + i, 11 + i, 9 + i, 10.5 + i, 100])
    loaded = load_bars("RB2405", DATES[0], DATES[-1], fixtures_dir=landed)
    assert data_loader.data_provenance(loaded)["provenance_missing"] is True


# ---------------------------------------------------------------------------
# 6. CLI contract
# ---------------------------------------------------------------------------
def run_cli(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, argv[0]), *argv[1:]],
                          capture_output=True, text=True)


def test_cli_build_ok_and_exit_zero(complete_landing):
    proc = run_cli("mcp_landing.py", "--build", "--raw-dir", complete_landing["raw"],
                   "--out-dir", complete_landing["landed"], "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["partial"] is False


def test_cli_truncated_payload_exits_nonzero(complete_landing):
    path = os.path.join(complete_landing["raw"], "get_future_daily__RB2410.json")
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    payload["total_rows"] = 8000
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    proc = run_cli("mcp_landing.py", "--build", "--raw-dir", complete_landing["raw"],
                   "--out-dir", complete_landing["landed"])
    assert proc.returncode != 0
    assert json.loads(proc.stdout)["error"]["code"] == "payload_truncated"


def test_cli_rejects_a_removed_cache_interface():
    """The old surface (cache directories, manifest, allow-partial at eval time) is gone."""
    proc = run_cli("mcp_landing.py", "--build", "--cache-dir", "data/raw/mcp_cache")
    assert proc.returncode == 2
    assert "unrecognized" in proc.stderr or "error" in proc.stderr.lower()

    proc = run_cli("evaluate.py", "--fixture", "--cache-dir", "data/raw/mcp_cache")
    assert proc.returncode == 2

    proc = run_cli("evaluate.py", "--fixture", "--allow-partial")
    assert proc.returncode == 2

    # The audit block must not keep emitting fields from that era. A report field
    # that is always empty is worse than no field: it reads as "we checked, there
    # were none". ``shard_files`` / ``request_ids`` used to be computed from a
    # ``shards`` key the loader stopped producing.
    import evaluate

    prov = {"RB": {"files": ["bars_RB2405.csv", "dominant_RB.csv"],
                   "source_payloads": ["get_future_daily__RB.json"],
                   "partial": False, "coverage_shrunk": False}}
    block = evaluate._summarise_provenance(prov, {})
    assert "shard_files" not in block and "request_ids" not in block
    assert block["built_files"] == ["bars_RB2405.csv", "dominant_RB.csv"]
    assert block["payload_files"] == ["get_future_daily__RB.json"]
    assert block["all_complete"] is True
    # a declared symbol that could not be served makes the run incomplete too
    assert evaluate._summarise_provenance(prov, {"I": {"code": "fixture_not_found"}})[
        "all_complete"] is False


def test_cli_verify_reports_the_two_stages(complete_landing):
    build(complete_landing)
    report = mcp_landing.verify(complete_landing["raw"], complete_landing["landed"])
    assert report["ok"] is True
    assert report["built"]["files"] == 5
    assert all(p["method"] in (mcp_landing.FUTURE_DAILY, mcp_landing.FUTURE_DOMINANT)
               for p in report["payloads"])


def test_cli_inspect_shows_completeness_fields(complete_landing):
    meta = mcp_landing.inspect_payload(
        os.path.join(complete_landing["raw"], "get_future_daily__RB2405.json"))
    assert meta["method"] == mcp_landing.FUTURE_DAILY
    assert meta["rows"] == len(complete_landing["front"])
    assert meta["partial"] is False
    assert meta["dates"][0] == complete_landing["front"][0]


# ---------------------------------------------------------------------------
# 7. Self-containment: the coupling must not come back
# ---------------------------------------------------------------------------
OTHER = "skill-" + "quant" + "-data-pipeline"
WRITER = "fetch_" + "pandadata_mcp"
MANIFEST = "_manifest" + ".jsonl"
IMPOSED = os.path.join("data", "raw", "mcp") + "_cache"
HOME = "/Users" + "/"


def _sources() -> Dict[str, str]:
    return {p: open(os.path.join(SCRIPTS, p), encoding="utf-8").read()
            for p in sorted(os.listdir(SCRIPTS)) if p.endswith(".py")}


def test_the_old_cache_module_is_gone():
    assert not os.path.exists(os.path.join(SCRIPTS, "mcp_cache.py"))
    assert os.path.exists(os.path.join(SCRIPTS, "mcp_landing.py"))


def test_no_cross_skill_reference_in_code():
    for name, src in _sources().items():
        for token in (OTHER, WRITER, MANIFEST, IMPOSED):
            assert token not in src, f"{name} still mentions {token!r}"


def test_no_hardcoded_install_path_in_code():
    for name, src in _sources().items():
        assert HOME not in src, f"{name} hardcodes an install path"


def test_scripts_have_no_network_egress_or_credentials():
    banned = ("import panda" + "_data", "from panda" + "_data", "init_token",
              "PANDA" + "_DATA_", "panda-data", "urlopen", "import socket",
              "http.client", "requests.get")
    for name, src in _sources().items():
        for token in banned:
            assert token not in src, f"{name} contains egress/credential token {token!r}"


def test_truncation_guard_is_a_local_function():
    """Implemented here, on purpose: no import from another skill's package."""
    assert callable(mcp_landing.check_payload) and callable(mcp_landing.require_complete)
    src = open(os.path.join(SCRIPTS, "mcp_landing.py"), encoding="utf-8").read()
    for line in src.splitlines():
        if line.strip().startswith(("import ", "from ")):
            assert OTHER not in line and WRITER not in line


def test_preview_rows_is_not_mistaken_for_a_row_count():
    """``preview_rows`` is a request parameter; reading it as a row count would
    brand every honest payload as tampered."""
    rows = daily_rows("RB2405", DATES[:2])
    payload = {"rows": rows, "preview_rows": 2000, "params": {}}
    meta = mcp_landing.check_payload(payload, rows, origin="p.json")
    assert meta["row_count"] is None
    assert meta["declared_row_mismatch"] is None
    mcp_landing.require_complete(meta, allow_partial=False, method="get_future_daily")


def test_shipped_fixtures_still_drive_the_offline_path():
    """The synthetic bars the docs promise must remain readable with no landing."""
    bars = data_loader.load_csv(os.path.join(ROOT, "tests", "fixtures", "bars_RB.csv"))
    assert len(bars) > 200 and bars[0]["date"] < bars[-1]["date"]


def test_payload_rows_reads_the_verbatim_mcp_envelope(tmp_path):
    """网关把表包在 ``result`` 里；契约却要求「原样落盘」。

    旧读取器只在顶层找 rows/data/records，所以按文档原样写盘的载荷一律
    ``payload_unreadable`` —— 真实取数路径从未跑通过，只在形状恰好是
    顶层 rows 的测试替身上绿过。
    """
    envelope = {
        "ok": True,
        "method": "get_future_daily",
        "params": {"symbol": ["RB_DOMINANT.SHF"]},
        "result": {
            "columns": ["date", "symbol", "open", "high", "low", "close", "volume"],
            "rows": [["20240102", "RB_DOMINANT.SHF", 4005, 4058, 3983, 4047, 970394],
                     ["20240103", "RB_DOMINANT.SHF", 4048, 4072, 4040, 4055, 964192]],
        },
        "row_count": 2, "total_rows": 2, "truncated": False,
    }
    rows, cols = mcp_landing.payload_rows(envelope, origin=str(tmp_path / "x.json"))
    assert len(rows) == 2
    assert rows[0]["close"] == 4047 and rows[1]["date"] == "20240103"
    assert cols and cols[0] == "date"


# ---------------------------------------------------------------------------
# A refused write must be a report, not a stack trace
# ---------------------------------------------------------------------------
def test_build_reports_structured_error_when_out_dir_is_read_only(tmp_path,
                                                                  complete_landing):
    """An installed (read-only) skill tree must not print a bare traceback.

    Everything up to the write phase is validation, so by the time we get here
    the work is finished and legitimately successful -- which is exactly why
    losing it to ``PermissionError`` is so bad: the operator sees a Python frame,
    not "your destination is read-only, rebuild with --out-dir somewhere else".
    """
    locked = str(tmp_path / "readonly_landed")
    os.makedirs(locked, exist_ok=True)
    os.chmod(locked, 0o500)
    try:
        with pytest.raises(mcp_landing.OutputNotWritable) as excinfo:
            mcp_landing.build(complete_landing["raw"], locked)
        assert excinfo.value.code == "landing_not_writable"
        assert "--out-dir" in excinfo.value.hint, excinfo.value.hint
        # The refusal must not leave a half-built dataset behind.
        assert not [f for f in os.listdir(locked) if f.startswith("bars_")], \
            os.listdir(locked)
    finally:
        os.chmod(locked, 0o700)


def test_cli_reports_unwritable_out_dir_with_the_data_exit_code(complete_landing,
                                                                tmp_path):
    """Exit codes are part of the contract: 0 ok / 2 usage / 3 data unavailable."""
    locked = str(tmp_path / "locked_landed")
    os.makedirs(locked, exist_ok=True)
    os.chmod(locked, 0o500)
    try:
        proc = run_cli("mcp_landing.py", "--build", "--raw-dir", complete_landing["raw"],
                       "--out-dir", locked)
    finally:
        os.chmod(locked, 0o700)
    assert proc.returncode == 3, proc.stdout + proc.stderr
    body = json.loads(proc.stdout)
    assert body["ok"] is False
    assert body["error"]["code"] == "landing_not_writable"
    assert "traceback" not in (proc.stderr or "").lower(), proc.stderr


def test_every_landing_error_code_is_documented():
    """Each ``code`` a caller can receive must appear in `references/api_guide.md`.

    The tables are the only thing a downstream integrator reads when a run fails.
    A code the tool can emit and the docs do not name is an error someone has to
    reverse-engineer from source.
    """
    guide = open(os.path.join(ROOT, "references", "api_guide.md"), encoding="utf-8").read()

    # Scope to classes the code can actually *raise*. An abstract base such as
    # ``LandingError`` carries a default ``code`` nobody ever receives, and
    # demanding it in the docs would push the table toward noise. Conversely a
    # root like ``DataUnavailable``, which ``data_loader`` does raise bare, is a
    # code a caller really gets -- and was undocumented until this guard said so.
    sources = {}
    for name in ("mcp_landing.py", "data_loader.py", "evaluate.py"):
        sources[name] = open(os.path.join(SCRIPTS, name), encoding="utf-8").read()

    candidates = []
    for mod in (mcp_landing, data_loader):
        for obj in vars(mod).values():
            if isinstance(obj, type) and issubclass(obj, mcp_landing.DataUnavailable) \
                    and hasattr(obj, "code"):
                candidates.append(obj)
    raisable = {}
    for cls in candidates:
        where = [src for src in sources.values()
                 if re.search(r"\braise\s+" + re.escape(cls.__name__) + r"\b", src)]
        if where:
            raisable[cls.code] = cls.__name__
    assert len(raisable) >= 8, "too few raisable error classes found: %s" % raisable

    missing = sorted("%s (%s)" % (code, raisable[code]) for code in raisable
                     if "`%s`" % code not in guide)
    assert not missing, "api_guide.md does not document these error codes: %s" % missing
