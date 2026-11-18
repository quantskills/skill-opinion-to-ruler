"""Tests for skill-opinion-to-ruler.

Coverage: normal input, boundary values, malformed input, the no-look-ahead
guarantee, the frozen policy hash, and cost accounting.
"""

from __future__ import annotations

import copy
import json
import math
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
    # Pinned because CHANGELOG quotes it: 10 clean samples is a 0.69 lower bound,
    # and "the English set scores 1.00" is not a claim about generalisation.
    assert report["samples_all_fields_correct_ci95_low"] == pytest.approx(0.6915, abs=1e-4)
    assert report["sufficient_sample_size"] is False


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


# ---------------------------------------------------------------------------
# Pre-run scope declaration
# ---------------------------------------------------------------------------
import scope as scope_mod  # noqa: E402


def _extracted():
    res = run({"text": "螺纹钢站稳3850，两周看4100，跌破3780止损。",
               "published_at": "2024-01-05T08:30:00+08:00"}, {"apply_defaults": True})
    return res


def test_scope_declared_from_inputs_only():
    scope = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231",
                                    "hold", 3.0, 2.0, 12)
    assert scope["declared_before_backtest"] is True
    assert scope["declared_symbols"] == ["RB"]
    assert scope["scope_hash"]
    # No trade information can leak into the declaration.
    assert "trades" not in scope


def test_scope_hash_is_stable_and_sensitive():
    a = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231", "hold", 3.0, 2.0, 12)
    b = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231", "hold", 3.0, 2.0, 12)
    c = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231", "hold", 5.0, 2.0, 12)
    assert a["scope_hash"] == b["scope_hash"]
    assert a["scope_hash"] != c["scope_hash"]


def test_unmapped_rule_is_declared_up_front():
    res = run({"text": "中科星图 涨到23.7", "published_at": "2026-11-13T10:00:00+08:00"},
              {"apply_defaults": True})
    scope = scope_mod.declare_scope(res, "panda", "20260101", "20261231", "hold", 3.0, 2.0, 12)
    assert scope["declared_symbols"] == []
    assert len(scope["unmapped_rules"]) == 1
    assert scope["unmapped_rules"][0]["direction"] == "long"


def test_verification_detects_undeclared_trade():
    scope = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231",
                                    "hold", 3.0, 2.0, 12)
    bars = {"RB": load_csv(os.path.join(FIXTURES, "bars_RB.csv"))}
    trades = [{"symbol": "I", "entry_date": "20240110"}]
    v = scope_mod.verify_scope(scope, bars, trades, [])
    assert v["honoured"] is False
    assert any("undeclared" in x for x in v["violations"])


def test_verification_detects_trade_outside_window():
    scope = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20240201",
                                    "hold", 3.0, 2.0, 12)
    bars = {"RB": load_csv(os.path.join(FIXTURES, "bars_RB.csv"))}
    trades = [{"symbol": "RB", "entry_date": "20240301"}]
    v = scope_mod.verify_scope(scope, bars, trades, [])
    assert v["honoured"] is False
    assert any("escapes declared range" in x for x in v["violations"])


def test_verification_honoured_on_clean_run():
    scope = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231",
                                    "hold", 3.0, 2.0, 12)
    bars = {"RB": load_csv(os.path.join(FIXTURES, "bars_RB.csv"))}
    trades = [{"symbol": "RB", "entry_date": "20240110"}]
    v = scope_mod.verify_scope(scope, bars, trades, [])
    assert v["honoured"] is True
    assert v["violations"] == []


def test_applicability_uses_runtime_scope():
    from backtest import applicability

    scope = scope_mod.declare_scope(_extracted(), "fixture", "20240101", "20241231",
                                    "hold", 3.0, 2.0, 12)
    verification = {"symbols_traded": ["RB"], "trade_span": {"first": "20240110", "last": "20240301"},
                    "violations": [], "honoured": True}
    app = applicability({"min_trades": 12}, {"rules_total": 1}, scope=scope, verification=verification)
    assert app["declared_before_run"] is True
    assert any("RB" in x for x in app["in_scope"])
    assert app["scope_honoured"] is True
    assert app["replay_equivalence"]["what_this_is_not"]


# ---------------------------------------------------------------------------
# Adversarial regressions (found by probing, not by reading the docs)
#
# Each test below names the wrong output it used to produce. They exist because
# the 164 pre-existing cases were all built from sentences the dictionary already
# handled, so every one of these defects scored 100% while broken.
# ---------------------------------------------------------------------------
def _raw(text):
    """Extraction only: no default policy, so nothing is filled in for the text."""
    return run({"text": text, "published_at": "2024-01-05T08:30:00+08:00"},
               {"apply_defaults": False})["documents"][0]


def _only_rule(text):
    d = _raw(text)
    rules = d["rules"] + d["unruleable"]
    assert rules, "sentence produced no rule at all: %r" % text
    return rules[0]


# -- 百分比价位曾被当成绝对价位 -----------------------------------------------
def test_percent_stop_is_not_read_as_an_absolute_level():
    """「止损3%」used to emit ``close < 3``: a level that triggers on day one.

    A relative stop cannot be executed against a daily-close contract, so the
    field stays empty and the percentage is reported separately instead of being
    silently converted into a price.
    """
    rule = _only_rule("螺纹钢站上3850做多，目标4100，止损3%。")
    assert rule["stop_loss"] is None, rule["stop_loss"]
    assert rule["exit_rule"]["expr"] == "close >= 4100"
    percents = rule.get("percent_levels") or []
    assert [p["field"] for p in percents] == ["stop_loss"], percents
    assert percents[0]["value"] == 3.0, percents
    assert any("percent" in a["issue"].lower() for a in rule["ambiguity"]), rule["ambiguity"]


def test_percent_target_is_not_read_as_an_absolute_level():
    rule = _only_rule("铁矿石跌破840看空，目标跌3%。")
    assert rule["direction"] == "short"
    assert rule["exit_rule"] is None, rule["exit_rule"]
    assert [p["field"] for p in rule.get("percent_levels") or []] == ["exit_rule"], \
        rule.get("percent_levels")


def test_full_width_percent_sign_is_also_caught():
    rule = _only_rule("螺纹钢站上3850做多，止损３％。")
    assert rule["stop_loss"] is None, rule["stop_loss"]


# -- 否定式曾被当成反向信号 ---------------------------------------------------
def test_withdrawn_bullishness_is_neutral_not_short():
    """「不再看多」used to come back as **long** (negation flipped the sign twice).

    The negation scan matched 不再 by its leading 不 while the level scan then read
    the sentence as bullish. Withdrawing a view is not the opposite view: the
    honest answer is stand-aside, never an invented position.
    """
    rule = _only_rule("螺纹钢不再看多，跌破3780不追。")
    assert rule["direction"] == "neutral", rule["direction"]
    assert rule["testability"] == "neutral", rule["testability"]


def test_double_negation_still_reads_the_stated_direction():
    """「不看空，站上900才算转多」states a long: the unnegated word wins."""
    rule = _only_rule("铁矿石不看空，站上900才算转多。")
    assert rule["direction"] == "long"
    assert rule["testability"] == "partial"


def test_negation_is_reported_even_when_direction_is_clear():
    rule = _only_rule("铁矿石不看空，站上900才算转多。")
    issues = " ".join(a["issue"] for a in rule["ambiguity"])
    assert "negation" in issues or "neutral" in issues.lower(), rule["ambiguity"]


# -- 裸代码与合约号 -----------------------------------------------------------
@pytest.mark.parametrize("code,symbol", [("RB", "RB"), ("I", "I"), ("HC", "HC"),
                                         ("AU", "AU"), ("SC", "SC")])
def test_bare_exchange_code_maps_to_the_product(code, symbol):
    """Codes used to be recognised only next to CJK text: 「RB看多」vanished."""
    rule = _only_rule("%s看多，站上3850，止损3780。" % code)
    assert rule["instrument"]["symbol"] == symbol, rule["instrument"]
    assert rule["instrument"]["mapping_rule"] == "code_to_symbol"


def test_contract_number_maps_to_product_and_keeps_the_contract():
    """「RB2405…」used to emit symbol ``RB2405``, which no scope can serve."""
    rule = _only_rule("RB2405站上3850看多，目标4100，止损3780。")
    inst = rule["instrument"]
    assert inst["symbol"] == "RB", inst
    assert inst["contract"] == "specific", inst
    assert inst.get("contract_code") == "RB2405", inst
    assert inst["mapping_rule"] == "contract_to_product", inst


def test_contract_code_survives_a_digit_suffix_that_is_not_a_code():
    """Prices must not be mistaken for contract months (RB 3850 is not a month)."""
    rule = _only_rule("RB站上3850看多，止损3780。")
    assert rule["instrument"]["symbol"] == "RB"
    assert rule["entry_trigger"]["expr"] == "close > 3850", rule["entry_trigger"]


def test_single_letter_english_word_is_not_iron_ore():
    """``I`` is iron ore only against CJK text, else 「I think…」would trade iron ore."""
    d = _raw("I think rebar looks cheap here.")
    assert not [r for r in d["rules"] if (r.get("instrument") or {}).get("symbol") == "I"], \
        d["rules"]


# -- 跨子句价格串味 -----------------------------------------------------------
def test_two_instruments_in_one_sentence_yield_two_rules_with_own_levels():
    """Used to become ONE rebar rule whose stop was iron ore's level.

    「螺纹钢多头铁矿空头」is two positions, not a contradiction. Attaching 840
    (iron ore) to rebar produced a stop that could never trigger, so the trade
    rode to horizon while looking like a risk-managed one.
    """
    d = _raw("螺纹钢多头铁矿空头，RB看3850上方，I看840下方。")
    assert len(d["rules"]) == 2, d["rules"]
    rb, i = d["rules"]
    assert rb["instrument"]["symbol"] == "RB" and rb["direction"] == "long"
    assert i["instrument"]["symbol"] == "I" and i["direction"] == "short"
    assert (rb.get("stop_loss") or {}).get("expr") != "close > 840", rb.get("stop_loss")
    assert (i.get("stop_loss") or {}).get("expr") != "close < 3780", i.get("stop_loss")
    assert rb["entry_trigger"]["expr"] == "close > 3850", rb["entry_trigger"]
    assert i["entry_trigger"]["expr"] == "close < 840", i["entry_trigger"]


def test_rule_ids_count_rules_not_sentences():
    d = _raw("螺纹钢多头铁矿空头，RB看3850上方，I看840下方。")
    ids = [r["rule_id"] for r in d["rules"]]
    assert ids == ["doc001-r01", "doc001-r02"], ids


def test_zone_word_does_not_become_a_profit_target():
    """「看3850上方」is a trigger zone. Reading it as target 3850 produced a rule
    whose exit equalled its entry: the trade settled on the same bar it opened."""
    rule = _only_rule("螺纹钢多头，RB看3850上方。")
    assert rule["entry_trigger"]["expr"] == "close > 3850", rule["entry_trigger"]
    assert rule["exit_rule"] is None, rule["exit_rule"]


# -- 价位合理性 ---------------------------------------------------------------
def test_stop_on_the_wrong_side_of_entry_is_dropped_not_emitted():
    """「螺纹钢站上3850做多，止损3900」used to emit a stop that fires on entry."""
    rule = _only_rule("螺纹钢站上3850做多，止损3900。")
    assert rule["stop_loss"] is None, rule["stop_loss"]
    assert any("wrong side" in a["issue"] for a in rule["ambiguity"]), rule["ambiguity"]


def test_level_from_a_different_price_range_is_dropped():
    """铁矿石 quoted at 3780 belongs to another market: 5x outside its window."""
    rule = _only_rule("铁矿石看多，站上840，止损3780。")
    assert rule["stop_loss"] is None, rule["stop_loss"]


# -- 不可交易条目不得带着可执行指令 -------------------------------------------
def test_unmapped_instrument_gets_no_market_order():
    """期权 in the text, no instrument mapped: entry stays empty.

    An unruleable item carrying ``market_on_next_open`` reads as a ready-to-run
    signal to anyone consuming the JSON.
    """
    d = _raw("50ETF购3月2500看多。")
    assert d["rules"] == [], d["rules"]
    assert d["unruleable"][0]["testability"] == "none"
    assert d["unruleable"][0]["entry_trigger"] is None, d["unruleable"][0]


def test_position_sizing_word_is_not_a_direction():
    """「减仓」manages an existing position; it is not a new short signal."""
    rule = _only_rule("IC主力5200下方减仓。")
    assert rule["direction"] in (None, "neutral"), rule["direction"]


def test_entry_default_is_visible_to_machines():
    """The substitution used to exist only in prose; nothing could check it."""
    rule = _only_rule("铁矿石看多，目标950，止损860。")
    assert rule["entry_trigger"]["expr"] == "market_on_next_open", rule["entry_trigger"]
    entries = [a for a in rule["assumed"] if a["field"] == "entry_trigger"]
    assert entries and entries[0]["stage"] == "extraction", rule["assumed"]


def test_unruleable_reason_names_the_missing_field():
    """「no instrument or no direction」was true but useless for an A-share name."""
    stock = _only_rule("中科星图看多，站上60，止损55。")
    assert "instrument" in stock["reason"] and "direction" not in stock["reason"], stock["reason"]
    macro = _only_rule("明年黑色系整体环境应该比今年好。")
    assert "instrument" in macro["reason"] and "direction" in macro["reason"], macro["reason"]


def test_every_rule_keeps_the_sentence_it_came_from():
    rule = _only_rule("螺纹钢主力站上3900看多，目标4150，止损3830。")
    assert "螺纹钢" in rule["source_text"], rule
    assert "source_span" not in rule, \
        "duplicate of source_text; a second field for one fact invites drift"


def test_percent_levels_are_a_separate_channel_from_price_levels():
    """Relative levels must not pollute the absolute-price vocabulary.

    They are reported so a human can act on them, and kept out of every ``expr``
    because the matcher only executes absolute daily-close conditions.
    """
    rule = _only_rule("螺纹钢站上3850做多，目标4100，止损3%。")
    exprs = [r["expr"] for r in (rule["entry_trigger"], rule["stop_loss"], rule["exit_rule"]) if r]
    assert exprs == ["close > 3850", "close >= 4100"], exprs
    first = rule["percent_levels"][0]
    assert first["phrase"] == "3%", first
    assert first["value"] == 3.0 and first["field"] == "stop_loss", first


# ---------------------------------------------------------------------------
# Metric honesty: Sharpe must describe per-trade returns
# ---------------------------------------------------------------------------
def _trades(nets, held):
    return [{"net_return": n, "held_bars": h} for n, h in zip(nets, held)]


def test_sharpe_is_not_annualised_by_the_daily_constant():
    """Per-trade returns scaled by ``sqrt(244)`` read 15x too high.

    The fixture anchor published Sharpe 11.85 for a strategy whose per-trade
    mean/sd was 0.76. 244 is bars per year; the returns being scaled arrive once
    per round trip, not once per bar.
    """
    import backtest

    nets = [0.02, -0.01, 0.03, 0.01, -0.02]
    held = [5, 5, 5, 5, 5]
    m = backtest.sharpe_metrics(_trades(nets, held))
    mean = sum(nets) / len(nets)
    sd = (sum((r - mean) ** 2 for r in nets) / (len(nets) - 1)) ** 0.5
    ratio = mean / sd
    assert m["sharpe_per_trade"] == pytest.approx(round(ratio, 3), abs=1e-9), m
    assert m["sharpe"] == pytest.approx(round(ratio * (244 / 5.0) ** 0.5, 3), abs=1e-9), m
    assert abs(m["sharpe"]) < abs(ratio) * (244 ** 0.5) * 0.5, (
        "the annualised figure must not sit anywhere near the sqrt(244) scaling")


def test_sharpe_reports_the_basis_it_used():
    import backtest

    m = backtest.sharpe_metrics(_trades([0.01, 0.02], [4, 6]))
    assert "trades_per_year" in m["sharpe_basis"], m
    assert m["sharpe_held_bars_coverage"] == "2/2", m
    assert m["sharpe_trades_per_year"] == round(244 / 5.0, 3), m


def test_sharpe_refuses_to_annualise_without_holding_periods():
    import backtest

    trades = [{"net_return": 0.01}, {"net_return": 0.02}]
    m = backtest.sharpe_metrics(trades)
    assert m["sharpe"] is None, m
    assert m["sharpe_per_trade"] is not None, m
    assert "cannot annualise" in m["sharpe_basis"], m


def test_sharpe_needs_two_trades():
    import backtest

    m = backtest.sharpe_metrics([{"net_return": 0.01, "held_bars": 5}])
    assert m["sharpe"] is None and m["sharpe_per_trade"] is None, m


# ---------------------------------------------------------------------------
# Annotation: a perfect score must not read as proof
# ---------------------------------------------------------------------------
def test_policy_filled_field_is_not_scored_as_a_prediction():
    """Gold says "the text states nothing"; a policy default must not win a TP.

    Three bundled labels used to carry ``market_on_next_open`` as gold even
    though the sentences state no entry condition, so the policy was grading its
    own homework and ``accuracy 1.0`` partly measured the default, not the reading.
    """
    sample = {"samples": [{"id": "x1", "text": "铁矿石看多，目标950，止损860。",
                           "published_at": "2024-01-05T08:30:00+08:00",
                           "labels": {"entry_expr": None, "instrument_symbol": "I",
                                      "direction": "long", "stop_expr": "close < 860",
                                      "exit_expr": "close >= 950", "horizon_days": None,
                                      "testability": "partial"}}]}
    report = annotate.score(sample)
    entry = report["fields"]["entry_expr"]
    assert entry["policy_default"] == 1, entry
    assert entry["tp"] == 0, entry
    assert entry["fp"] == 0, "a documented default must not be punished either"
    assert entry["exact_match_text_only"] is None, entry


def test_real_fabrication_is_still_a_false_positive():
    """The policy-default carve-out must stay narrow: text-derived values count.

    A value the sentence *did* state, labelled as absent, is the extractor
    inventing something the author never said. That has to stay a false positive,
    or the ``policy_default`` escape hatch would become a general pardon.
    """
    sample = {"samples": [{"id": "x1", "text": "螺纹钢站上3850看多，目标4100，止损3780。",
                           "published_at": "2024-01-05T08:30:00+08:00",
                           "labels": {"instrument_symbol": "RB", "direction": "long",
                                      "entry_expr": "close > 3850",
                                      "stop_expr": None,          # gold claims: unstated
                                      "exit_expr": "close >= 4100",
                                      "horizon_days": None, "testability": "partial"}}]}
    report = annotate.score(sample)
    stop = report["fields"]["stop_expr"]
    assert stop["fp"] == 1, stop
    assert stop["policy_default"] == 0, stop
    assert stop["exact_match_text_only"] is not None, stop


def test_clopper_pearson_bound_is_published_and_below_one():
    """16/16 correct is compatible with a true rate near 0.79, and must say so."""
    report = annotate.score({"samples": [
        {"id": "s%d" % i, "text": "螺纹钢站上3850看多，止损3800。",
         "published_at": "2024-01-05T08:30:00+08:00",
         "labels": {"instrument_symbol": "RB", "direction": "long",
                    "entry_expr": "close > 3850", "stop_expr": "close < 3800",
                    "exit_expr": None, "horizon_days": None, "testability": "partial"}}
        for i in range(16)]})
    field = report["fields"]["direction"]
    assert field["exact_match_rate"] == 1.0
    assert field["exact_match_ci95_low"] == pytest.approx(0.025 ** (1 / 16.0), abs=2e-4), field
    assert report["samples_all_fields_correct_ci95_low"] < 0.9, report
    assert report["sufficient_sample_size"] is False
    assert "lower bound" in report["sample_size_note"]


def test_clopper_pearson_matches_a_known_value():
    """Cross-check against the binomial definition, not a remembered table number.

    ``L`` is the value where ``P(X >= k | p = L) = alpha/2``, so the beta
    inversion in ``annotate`` is verifiable by solving the same equation directly
    with integer binomials. Two independent routes agreeing is worth more than a
    quoted constant: the first version of this test cited ``0.2026`` for 8/20
    from memory, while the definition gives ``0.1912``.
    """
    def tail(k, n, p):
        if p <= 0.0:
            return 0.0
        if p >= 1.0:
            return 1.0
        return sum(math.comb(n, j) * p ** j * (1 - p) ** (n - j)
                   for j in range(k, n + 1))

    def solve(k, n, alpha=0.025):
        lo, hi = 0.0, 1.0
        for _ in range(300):
            mid = (lo + hi) / 2.0
            if tail(k, n, mid) > alpha:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2.0

    for k, n in [(8, 20), (5, 10), (20, 26), (1, 20), (3, 7)]:
        assert annotate.clopper_pearson_lower(k, n) == pytest.approx(solve(k, n), abs=2e-4), \
            (k, n)
    assert annotate.clopper_pearson_lower(0, 10) == 0.0
    assert annotate.clopper_pearson_lower(10, 10) == pytest.approx(0.025 ** 0.1, abs=2e-4)
    assert annotate.clopper_pearson_lower(5, 0) is None


def test_list_labels_score_every_rule_of_a_multi_instrument_sentence():
    """A sentence with two products must be checkable as two rules, not one."""
    sample = {"samples": [{"id": "x2", "text": "螺纹钢多头铁矿空头，RB看3850上方，I看840下方。",
                           "published_at": "2024-01-05T08:30:00+08:00",
                           "labels": [
                               {"instrument_symbol": "RB", "direction": "long",
                                "entry_expr": "close > 3850", "stop_expr": None,
                                "exit_expr": None, "horizon_days": None,
                                "testability": "partial"},
                               {"instrument_symbol": "I", "direction": "short",
                                "entry_expr": "close < 840", "stop_expr": None,
                                "exit_expr": None, "horizon_days": None,
                                "testability": "partial"}]}]}
    report = annotate.score(sample)
    assert report["rule_count_mismatches"] == 0, report["rule_count_mismatches"]
    assert report["fields"]["instrument_symbol"]["judgements"] == 2
    assert report["fields"]["instrument_symbol"]["exact_match_rate"] == 1.0


def test_missing_second_rule_is_counted_as_a_mismatch():
    sample = {"samples": [{"id": "x3", "text": "螺纹钢站上3850看多。",
                           "published_at": "2024-01-05T08:30:00+08:00",
                           "labels": [{"instrument_symbol": "RB", "direction": "long",
                                       "entry_expr": "close > 3850", "stop_expr": None,
                                       "exit_expr": None, "horizon_days": None,
                                       "testability": "partial"},
                                      {"instrument_symbol": "I", "direction": "short",
                                       "entry_expr": None, "stop_expr": None,
                                       "exit_expr": None, "horizon_days": None,
                                       "testability": "partial"}]}]}
    report = annotate.score(sample)
    assert report["rule_count_mismatches"] == 1, report
    assert report["fields"]["instrument_symbol"]["fn"] >= 1


def test_bundled_labels_cover_the_probed_forms(labels):
    """The fixture must keep containing the wording that used to break things."""
    texts = " ".join(s["text"] for s in labels["samples"])
    required = {
        "百分比止损": "止损3%",
        "撤回看多": "不再看多",
        "裸代码": "RB看多",
        "单字母裸代码": "I看空",
        "合约号": "RB2405",
        "一句两标的": "螺纹钢多头铁矿空头",
        "仓位管理": "减仓",
        "观望口语": "不建议参与",
    }
    for name, needle in required.items():
        assert needle in texts, "labels no longer cover %s (%r)" % (name, needle)
    multi = [s for s in labels["samples"] if isinstance(s.get("labels"), list)]
    assert multi, "no list-labelled multi-rule sample remains in the fixture"


def test_bundled_labels_do_not_copy_the_entry_default_as_gold(labels):
    """Gold must stay independent of what the extractor happens to emit."""
    offenders = [s["id"] for s in labels["samples"]
                 if (s["labels"] == {} or isinstance(s["labels"], dict))
                 and s["labels"].get("entry_expr") == "market_on_next_open"]
    assert not offenders, "%s claim a market order the text never stated" % offenders
    stated = sum(1 for s in labels["samples"]
                 if isinstance(s["labels"], dict) and s["labels"].get("entry_expr") is None)
    assert stated >= 3, "the fixture must keep examples where the text states no trigger"


# -- 进场俚语"上车"曾被整句丢弃 -------------------------------------------------
def test_entry_colloquialism_yields_a_long_rule():
    """"上车" is the commonest informal way of saying "go long" in Chinese chatter.

    A whitelist that misses it does not fail safe, it fails *silent*: the sentence
    carries an instrument, an entry condition and a stop, and all three were thrown
    away as "no direction wording". The cost of the miss is asymmetric with the risk
    of admitting it, because negation still overrides it (see the next test).
    """
    rule = _only_rule(u"螺纹钢突破3900就上车，止损3800。")
    assert rule["direction"] == "long", rule
    assert rule["instrument"]["symbol"] == "RB", rule["instrument"]
    assert rule["entry_trigger"]["expr"] == "close > 3900", rule["entry_trigger"]
    assert rule["stop_loss"]["expr"] == "close < 3800", rule["stop_loss"]
    # No horizon in the text: partial, and it stays partial under extraction-only.
    assert rule["testability"] == "partial", rule["testability"]


def test_negation_still_overrides_the_colloquialism():
    """Adding a long word must not weaken the negation rule: 别上车 == stay out."""
    rule = _only_rule(u"螺纹钢突破3900也别上车，止损3800。")
    assert rule["direction"] == "neutral", rule
    assert rule["testability"] == "neutral", rule
