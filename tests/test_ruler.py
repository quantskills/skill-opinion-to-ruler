"""Tests for skill-opinion-to-ruler.

Coverage: normal input, boundary values, malformed input, the no-look-ahead
guarantee, the frozen policy hash, and cost accounting.
"""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import annotate  # noqa: E402
from backtest import (  # noqa: E402
    BacktestError,
    decide_verdict,
    evaluate,
    parse_expr,
    simulate_rule,
)
from build import DEFAULT_POLICY, run, validate_input  # noqa: E402
from data_loader import DataUnavailable, load_csv, load_bars  # noqa: E402

FIXTURES = os.path.join(HERE, "fixtures")


@pytest.fixture()
def opinions():
    with open(os.path.join(FIXTURES, "opinions.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def labels():
    with open(os.path.join(FIXTURES, "labels.json"), encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def bars():
    return load_csv(os.path.join(FIXTURES, "bars_RB.csv"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_validate_accepts_plain_string():
    validate_input("螺纹钢站稳3800看多")


def test_validate_rejects_empty_string():
    with pytest.raises(ValueError):
        validate_input("   ")


def test_validate_rejects_none():
    with pytest.raises(ValueError):
        validate_input(None)


def test_validate_rejects_missing_text():
    with pytest.raises(KeyError):
        validate_input({"published_at": "2024-01-01"})


def test_validate_rejects_non_string_text():
    with pytest.raises(TypeError):
        validate_input({"text": 123})


def test_validate_rejects_bad_published_at():
    with pytest.raises(ValueError):
        validate_input({"text": "螺纹钢看多", "published_at": "05/06/2024"})
    with pytest.raises(TypeError):
        validate_input({"text": "螺纹钢看多", "published_at": 20240506})


def test_validate_rejects_empty_documents():
    with pytest.raises(ValueError):
        validate_input({"documents": []})


def test_validate_rejects_empty_list():
    with pytest.raises(ValueError):
        validate_input([])


def test_validate_reports_index_for_list():
    with pytest.raises(ValueError) as exc:
        validate_input([{"text": "ok"}, {"text": ""}])
    assert "input_data[1]" in str(exc.value)


# ---------------------------------------------------------------------------
# Extraction — normal
# ---------------------------------------------------------------------------
def test_extracts_levels_and_horizon():
    res = run({"text": "螺纹钢主力站稳3850，未来两周上冲4100，跌破3780止损。",
               "published_at": "2024-01-05T08:30:00+08:00"})
    rule = res["documents"][0]["rules"][0]
    assert rule["instrument"]["symbol"] == "RB"
    assert rule["direction"] == "long"
    assert rule["entry_trigger"]["expr"] == "close > 3850"
    assert rule["stop_loss"]["expr"] == "close < 3780"
    assert rule["exit_rule"]["expr"] == "close >= 4100"
    assert rule["horizon"]["value"] == 10


def test_short_direction_and_stop_flip():
    res = run({"text": "铁矿石短线看空，跌破840，止损880。",
               "published_at": "2024-01-08T08:30:00+08:00"})
    rule = res["documents"][0]["rules"][0]
    assert rule["direction"] == "short"
    assert rule["entry_trigger"]["expr"] == "close < 840"
    assert rule["stop_loss"]["expr"] == "close > 880"


def test_negation_flips_direction():
    res = run({"text": "铁矿石不看空，站上900才算转多。",
               "published_at": "2024-01-12T08:30:00+08:00"})
    rule = res["documents"][0]["rules"][0]
    assert rule["direction"] == "long"
    assert any("negation" in a["issue"] for a in rule["ambiguity"])


def test_neutral_is_its_own_class():
    res = run({"text": "螺纹钢观望，等突破4000再说。",
               "published_at": "2024-01-15T08:30:00+08:00"})
    rule = res["documents"][0]["rules"][0]
    assert rule["testability"] == "neutral"
    assert rule["direction"] == "neutral"


def test_pullback_entry_is_conditional():
    res = run({"text": "螺纹钢中线上看4300，回踩3800附近可以买，跌破3700止损。",
               "published_at": "2024-01-10T08:30:00+08:00"})
    rule = res["documents"][0]["rules"][0]
    assert rule["entry_trigger"]["expr"] == "close <= 3800"


def test_bare_target_is_attributed_by_direction():
    long_res = run({"text": "铁矿石看多，目标950，止损860。",
                    "published_at": "2024-01-19T08:30:00+08:00"})
    short_res = run({"text": "螺纹钢短线偏空，目标3700。",
                     "published_at": "2024-01-31T08:30:00+08:00"})
    assert long_res["documents"][0]["rules"][0]["exit_rule"]["expr"] == "close >= 950"
    assert short_res["documents"][0]["rules"][0]["exit_rule"]["expr"] == "close <= 3700"


# ---------------------------------------------------------------------------
# Extraction — boundary / negative
# ---------------------------------------------------------------------------
def test_macro_sentence_is_unruleable():
    res = run({"text": "明年黑色系整体环境应该比今年好。"})
    doc = res["documents"][0]
    assert doc["counts"]["rules_total"] == 0
    assert doc["counts"]["unruleable"] == 1
    assert doc["unruleable"][0]["testability"] == "none"


def test_empty_sentence_list_falls_back_to_whole_text():
    res = run("螺纹钢看多")
    assert res["documents"][0]["counts"]["rules_total"] == 1


def test_no_instrument_means_no_rule():
    res = run({"text": "我觉得后市会涨。"})
    assert res["documents"][0]["counts"]["rules_total"] == 0


def test_missing_horizon_marked_partial_without_defaults():
    res = run({"text": "铁矿石看多，目标950，止损860。"})
    rule = res["documents"][0]["rules"][0]
    assert rule["testability"] == "partial"
    assert "horizon" in rule["missing_fields"]


def test_defaults_record_assumptions_and_reason(bars=None):
    res = run({"text": "铁矿石看多，目标950，止损860。"}, {"apply_defaults": True})
    rule = res["documents"][0]["rules"][0]
    # ``full`` is judged on the text, so an assumed horizon keeps it partial.
    assert rule["testability"] == "partial"
    assert "horizon" in rule["missing_fields"]
    assert any(a["field"] == "horizon" for a in rule["assumed"])
    assert rule["horizon"]["value"] == DEFAULT_POLICY["missing_horizon"]["value"]
    assert "horizon" in rule["reason"]


def test_document_id_is_derived_when_absent():
    res = run({"text": "螺纹钢看多"})
    assert res["documents"][0]["document_id"] == "doc001"


def test_instrument_inheritance_is_flagged():
    res = run({"text": "螺纹钢看多目标4000。突破4100则加仓。",
               "published_at": "2024-01-05T08:30:00+08:00"})
    rules = res["documents"][0]["rules"] + res["documents"][0]["unruleable"]
    assert len(rules) >= 2
    assert any(r["instrument_inherited"] for r in rules)


def test_no_invented_fields():
    """A field the text does not contain must never be filled by extraction."""
    res = run({"text": "螺纹钢看多。", "published_at": "2024-01-05T08:30:00+08:00"})
    rule = res["documents"][0]["rules"][0]
    assert rule["stop_loss"] is None
    assert rule["exit_rule"] is None
    assert rule["horizon"] is None


# ---------------------------------------------------------------------------
# Config hash / frozen policy
# ---------------------------------------------------------------------------
def test_config_hash_is_stable():
    a = run({"text": "螺纹钢看多"})
    b = run({"text": "螺纹钢看多"})
    assert a["config_hash"] == b["config_hash"]


def test_config_hash_changes_with_policy():
    text = {"text": "螺纹钢看多"}
    a = run(text)
    policy = copy.deepcopy(DEFAULT_POLICY)
    policy["missing_horizon"]["value"] = 7
    b = run(text, {"apply_defaults": True, "policy": policy})
    assert a["config_hash"] != b["config_hash"]


def test_summary_counts_are_consistent(opinions):
    res = run(opinions, {"apply_defaults": True})
    s = res["summary"]
    assert s["rules_total"] == s["rules_full"] + s["rules_partial"] + s["rules_neutral"]
    assert 0.0 <= s["ruleable_share"] <= 1.0


# ---------------------------------------------------------------------------
# Labelled accuracy
# ---------------------------------------------------------------------------
def test_labelled_sample_scores_perfectly(labels):
    report = annotate.score(labels)
    assert report["overall_exact_match"] == 1.0
    for field, m in report["fields"].items():
        assert m["exact_match_rate"] == 1.0, field


def test_annotate_detects_wrong_prediction(labels):
    broken = copy.deepcopy(labels)
    broken["samples"][0]["labels"]["direction"] = "short"
    report = annotate.score(broken)
    assert report["fields"]["direction"]["exact_match_rate"] < 1.0
    assert report["fields"]["direction"]["fp"] >= 1


def test_annotate_penalises_fabricated_field(labels):
    broken = copy.deepcopy(labels)
    broken["samples"][0]["labels"]["horizon_days"] = None
    report = annotate.score(broken)
    # Extractor reports 10 days for op-001, so a null label counts as a false positive.
    assert report["fields"]["horizon_days"]["fp"] >= 1


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def test_parse_expr_roundtrip():
    assert parse_expr("close > 3800") == ("gt", 3800.0)
    assert parse_expr("close <= 5.5") == ("le", 5.5)


def test_parse_expr_rejects_garbage():
    with pytest.raises(BacktestError):
        parse_expr("price above 3800")
    with pytest.raises(BacktestError):
        parse_expr("close >> 3800")


def test_parse_expr_empty_means_market_entry():
    assert parse_expr(None) is None
    assert parse_expr("") is None


def _rule(**over):
    base = {
        "rule_id": "t1",
        "testability": "full",
        "direction": "long",
        "instrument": {"symbol": "RB"},
        "published_at": "20240105",
        "entry_trigger": {"type": "price_condition", "expr": "close > 3800"},
        "horizon": {"value": 5, "unit": "trading_day", "expiry_action": "force_close"},
        "stop_loss": {"expr": "close < 3000"},
        "exit_rule": {"expr": "close >= 9999"},
    }
    base.update(over)
    return base


def test_no_look_ahead_requires_published_at(bars):
    from backtest import _bars_after

    rec = simulate_rule(_rule(published_at=None), bars)
    assert rec["status"] == "skipped"
    with pytest.raises(BacktestError):
        _bars_after(bars, None)


def test_trade_never_starts_before_publish_date(bars):
    rule = _rule(published_at="20240301")
    rec = simulate_rule(rule, bars)
    assert rec["status"] == "traded"
    assert rec["entry_date"] > "20240301"


def test_costs_reduce_return(bars):
    rule = _rule(published_at="20240110")
    free = simulate_rule(rule, bars, cost_bps=0.0, slippage_bps=0.0)
    paid = simulate_rule(rule, bars, cost_bps=3.0, slippage_bps=2.0)
    assert paid["net_return"] < free["net_return"]


def test_horizon_force_close(bars):
    rule = _rule(published_at="20240110", stop_loss={"expr": "close < 1"},
                 exit_rule={"expr": "close >= 99999"}, horizon={"value": 3})
    rec = simulate_rule(rule, bars)
    assert rec["exit_reason"] == "horizon"
    assert rec["held_bars"] <= 3


def test_stop_loss_takes_priority(bars):
    rule = _rule(published_at="20240110", stop_loss={"expr": "close > 0"},
                 exit_rule={"expr": "close >= 99999"}, horizon={"value": 50})
    rec = simulate_rule(rule, bars)
    assert rec["exit_reason"] == "stop_loss"


def test_untriggered_entry_is_skipped_not_faked(bars):
    rule = _rule(published_at="20240110", entry_trigger={"type": "price_condition", "expr": "close > 999999"})
    rec = simulate_rule(rule, bars)
    assert rec["status"] == "skipped"
    assert "never triggered" in rec["reason"]


def test_baseline_hold_is_paired(bars):
    rule = _rule(published_at="20240110")
    res = evaluate([rule], {"RB": bars}, baseline="hold")
    trade = res["trades"][0]
    assert trade["baseline_return"] is not None
    assert trade["edge"] == pytest.approx(trade["net_return"] - trade["baseline_return"], abs=1e-6)


def test_baseline_spans_the_horizon_not_the_actual_exit(bars):
    """Regression: a long rule that exits early must still be compared with a
    full-horizon hold. Measuring the baseline at the rule's own exit date makes
    it identical to the trade, so every long edge is exactly zero."""
    rule = _rule(published_at="20240110", stop_loss={"expr": "close > 0"},
                 exit_rule={"expr": "close >= 99999"}, horizon={"value": 20})
    res = evaluate([rule], {"RB": bars}, baseline="hold")
    trade = res["trades"][0]
    assert trade["exit_reason"] == "stop_loss"
    assert trade["horizon_end_date"] > trade["exit_date"]
    assert abs(trade["edge"]) > 1e-9


def test_cash_baseline_is_zero():
    bars = load_csv(os.path.join(FIXTURES, "bars_RB.csv"))
    res = evaluate([_rule(published_at="20240110")], {"RB": bars}, baseline="cash")
    assert res["trades"][0]["baseline_return"] == 0.0


def test_invalid_baseline_rejected(bars):
    with pytest.raises(BacktestError):
        evaluate([_rule()], {"RB": bars}, baseline="random")


def test_verdict_insufficient_trades_is_inconclusive():
    assert decide_verdict({"mean": 0.5, "lo": 0.2, "hi": 0.9}, trades=3) == "inconclusive"


def test_verdict_positive():
    assert decide_verdict({"mean": 0.01, "lo": 0.004, "hi": 0.02}, trades=20) == "positive"


def test_verdict_negative():
    assert decide_verdict({"mean": -0.01, "lo": -0.02, "hi": -0.004}, trades=20) == "negative"


def test_verdict_negative_when_ci_upper_is_zero():
    assert decide_verdict({"mean": -0.001, "lo": -0.003, "hi": 0.0}, trades=20) == "negative"


def test_verdict_straddling_ci_is_inconclusive():
    assert decide_verdict({"mean": 0.001, "lo": -0.002, "hi": 0.004}, trades=20) == "inconclusive"


# ---------------------------------------------------------------------------
# Data adapter
# ---------------------------------------------------------------------------
def test_load_csv_missing_file():
    with pytest.raises(DataUnavailable):
        load_csv(os.path.join(FIXTURES, "nope.csv"))


def test_load_csv_rejects_bad_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("date,close\n20240102,10\n", encoding="utf-8")
    with pytest.raises(DataUnavailable):
        load_csv(str(p))


def test_load_bars_prefers_csv():
    loaded = load_bars("RB", "20240101", "20241231", csv_path=os.path.join(FIXTURES, "bars_RB.csv"))
    assert loaded["source"] == "csv"
    assert loaded["bars"][0]["date"] < loaded["bars"][-1]["date"]


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------
def test_end_to_end_report_shape(opinions, labels):
    res = run(opinions, {"apply_defaults": True})
    rules = [r for d in res["documents"] for r in d["rules"]]
    bars_by_symbol = {
        "RB": load_csv(os.path.join(FIXTURES, "bars_RB.csv")),
        "I": load_csv(os.path.join(FIXTURES, "bars_I.csv")),
    }
    bt = evaluate(rules, bars_by_symbol)
    assert bt["verdict"] in ("positive", "negative", "inconclusive")
    assert bt["metrics"]["trades"] >= 1
    assert all("edge" in t for t in bt["trades"])
    report = annotate.score(labels)
    assert report["overall_exact_match"] >= 0.9

# ---------------------------------------------------------------------------
# English support
# ---------------------------------------------------------------------------
def _one(text, apply_defaults=True):
    res = run({"text": text, "published_at": "2024-01-05T08:30:00+08:00"},
              {"apply_defaults": apply_defaults})
    doc = res["documents"][0]
    return (doc["rules"] + doc["unruleable"])[0]


def test_english_full_rule():
    rule = _one("Rebar holds 3850, sees 4100 in two weeks, wrong below 3780.")
    assert rule["instrument"]["symbol"] == "RB"
    assert rule["direction"] == "long"
    assert rule["entry_trigger"]["expr"] == "close > 3850"
    assert rule["stop_loss"]["expr"] == "close < 3780"
    assert rule["exit_rule"]["expr"] == "close >= 4100"
    assert rule["horizon"]["value"] == 10
    assert rule["testability"] == "full"


def test_english_short_direction():
    rule = _one("Iron ore is bearish short-term, breaks below 840, stop at 880.")
    assert rule["instrument"]["symbol"] == "I"
    assert rule["direction"] == "short"
    assert rule["entry_trigger"]["expr"] == "close < 840"
    assert rule["stop_loss"]["expr"] == "close > 880"


def test_english_target_and_stop():
    rule = _one("Copper looks bullish, target 78000, stop loss 75000.")
    assert rule["instrument"]["symbol"] == "CU"
    assert rule["exit_rule"]["expr"] == "close >= 78000"
    assert rule["stop_loss"]["expr"] == "close < 75000"


def test_english_neutral():
    rule = _one("Crude oil neutral, wait and see.")
    assert rule["testability"] == "neutral"
    assert rule["instrument"]["symbol"] == "SC"


def test_english_macro_is_unruleable():
    rule = _one("Commodities should do better next year.")
    assert rule["testability"] == "none"


def test_english_negation_flips_direction():
    rule = _one("Rebar is not bearish, could turn bullish above 3900.")
    assert rule["direction"] == "long"
    assert any("negation" in a["issue"] for a in rule["ambiguity"])


def test_english_horizon_variants():
    assert _one("Gold targets 600 over the next month, stop below 560.")["horizon"]["value"] == 20
    assert _one("Iron ore targeting 900 in three months, stop 800.")["horizon"]["value"] == 60
    assert _one("Rebar bullish, target 4100 next week, stop 3800.")["horizon"]["value"] == 5


def test_english_pullback_entry():
    rule = _one("Rebar: expects a pullback to 3800 as a long entry, target 4300, stop 3700.")
    assert rule["entry_trigger"]["expr"] == "close <= 3800"


def test_ascii_instrument_respects_word_boundaries():
    # "longer" must not match "long"; "corn" must not match inside "corner".
    res = run({"text": "Gold is not longer a bull market.", "published_at": "2024-01-05T08:30:00+08:00"})
    doc = res["documents"][0]
    for rule in doc["rules"] + doc["unruleable"]:
        assert rule["direction"] != "long"
    assert _one("Corner shop chatter, no view.")["instrument"] is None


def test_english_decimal_not_split():
    rule = _one("Copper targets 78000.5 in two weeks, stop 75000.")
    assert rule["exit_rule"]["expr"] == "close >= 78000.5"


def test_mixed_language_sentence():
    rule = _one("Rebar bullish 看多, target 4100 in two weeks, stop 3800.")
    assert rule["instrument"]["symbol"] == "RB"
    assert rule["direction"] == "long"


def test_english_labelled_sample_scores_perfectly():
    with open(os.path.join(FIXTURES, "labels_en.json"), encoding="utf-8") as fh:
        report = annotate.score(json.load(fh))
    assert report["overall_exact_match"] == 1.0
    for field, m in report["fields"].items():
        assert m["exact_match_rate"] == 1.0, field


def test_bare_target_verb_is_recognised():
    """「未来两周看4100」— a target verb directly followed by a number."""
    rule = _one("螺纹钢主力站稳3850，未来两周看4100，跌破3780止损。")
    assert rule["exit_rule"]["expr"] == "close >= 4100"
    assert rule["direction"] == "long"
    assert rule["testability"] == "full"


def test_a_share_news_paragraph_is_not_ruleable():
    """Market-recap prose (no opinion, no condition) must fall to none, not be guessed."""
    text = ("算力芯片延续此前强势，华东重机一字涨停，旋极信息、大胜达、摩尔线程、天普股份、"
            "寒武纪涨超4%。消息面上，阿里巴巴宣布分拆旗下AI芯片公司平头哥赴港独立上市。")
    res = run({"text": text, "published_at": "2026-11-13T10:00:00+08:00"}, {"apply_defaults": True})
    assert res["summary"]["rules_total"] == 0
    assert res["summary"]["unruleable"] >= 1


def test_rise_to_and_fall_to_are_targets():
    up = _one("螺纹钢涨到4100，跌破3850止损")
    assert up["direction"] == "long"
    assert up["exit_rule"]["expr"] == "close >= 4100"
    assert up["stop_loss"]["expr"] == "close < 3850"
    down = _one("铁矿石跌到800，止损850")
    assert down["direction"] == "short"
    assert down["exit_rule"]["expr"] == "close <= 800"


def test_a_share_name_resolves_but_has_no_symbol_by_design():
    """A-share names are outside the futures alias table: rules extract, symbol is None."""
    res = run({"text": "中科星图 涨到23.7", "published_at": "2026-11-13T10:00:00+08:00"},
              {"apply_defaults": True})
    doc = res["documents"][0]
    item = (doc["rules"] + doc["unruleable"])[0]
    assert item["instrument"] is None
    assert item["direction"] == "long"
    assert item["exit_rule"]["expr"] == "close >= 23.7"
    assert item["testability"] == "none"
