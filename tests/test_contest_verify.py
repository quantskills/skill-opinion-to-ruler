"""`scripts/contest_verify.py` 的守卫。

这个模块最容易被写坏的方式不是算错，而是**在缺证据时仍然给一个好看的 verdict**：
把没成交说成已核验、把 ready=false 的 0 当最新价、用最后交易日顶替交割日、
或者顺手把账户号/手机号写进报告。下面每条都对着一种具体的说谎方式。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import contest_verify  # noqa: E402


def quote(latest=2985.0, bid=2983.0, ask=2985.0, ready=True, trade_date="20261119",
          code="rb2701"):
    return {
        "contractCode": code, "ready": ready, "latestPrice": latest,
        "bidPrice1": bid, "askPrice1": ask, "preclose": 2977.0,
        "tradeDate": trade_date, "quoteTime": "2026-11-18 230000",
    }


def spec(multiplier=10, ratio=0.07, last_trade="20270115", delivery=None):
    return {
        "contractMultiplier": multiplier,
        "margin": {"longMarginRatioByMoney": ratio, "shortMarginRatioByMoney": ratio,
                   "longMarginByVolume": 0, "shortMarginByVolume": 0},
        "lastTradeDate": last_trade, "deliveryDate": delivery,
    }


def resolve(enabled=True, exchange="SHF"):
    return {"status": "exact",
            "variety": {"variety": "RB", "code": "RB", "name": "螺纹钢",
                        "exchange": exchange, "enabled": enabled}}


def seed(raw: Path, *, rb_quote=None, rb_spec=None, i_quote=None, i_spec=None,
         with_account=True):
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "resolve__RB.json").write_text(json.dumps(resolve()), encoding="utf-8")
    (raw / "resolve__I.json").write_text(
        json.dumps(resolve(enabled=True, exchange="DCE")), encoding="utf-8")
    (raw / "quote__RB.json").write_text(json.dumps(rb_quote or quote()), encoding="utf-8")
    (raw / "contract_spec__RB.json").write_text(json.dumps(rb_spec or spec()), encoding="utf-8")
    (raw / "quote__I.json").write_text(json.dumps(
        i_quote or quote(latest=648.0, bid=647.5, ask=648.0, code="i2701")), encoding="utf-8")
    (raw / "contract_spec__I.json").write_text(json.dumps(
        i_spec or spec(multiplier=100, ratio=0.08)), encoding="utf-8")
    if with_account:
        (raw / "account.json").write_text(json.dumps(
            {"startCapital": 5000000, "availableFunds": 5000000, "margin": 0,
             "riskRate": 0, "tradeDate": "20261119", "ready": True}), encoding="utf-8")
    return raw


# ---------------------------------------------------------------- 缺失即不结论
def test_missing_directory_is_structured_error_not_zero(tmp_path):
    rc = contest_verify.main(["--raw", str(tmp_path / "nope")])
    assert rc == 2


def test_all_payloads_absent_refuses_to_verify(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(contest_verify.ContestError) as exc:
        contest_verify.verify(tmp_path / "empty")
    assert exc.value.code == "missing_contest_payload"


def test_malformed_payload_is_structured(tmp_path):
    seed(tmp_path / "raw")
    (tmp_path / "raw" / "quote__RB.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(contest_verify.ContestError) as exc:
        contest_verify.verify(tmp_path / "raw")
    assert exc.value.code == "invalid_contest_payload"


# ---------------------------------------------------------------- 行情与映射
def test_unready_quote_blocks_instead_of_reading_zero(tmp_path):
    raw = seed(tmp_path / "raw", rb_quote=quote(latest=0.0, bid=0.0, ask=0.0, ready=False))
    report = contest_verify.verify(raw)
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["verdict"] == "blocked"
    assert rb["checks"]["quote_ready"]["status"] == "blocked"
    assert report["verdict"] == "partially_verified"


def test_disabled_variety_is_flagged(tmp_path):
    raw = seed(tmp_path / "raw")
    (raw / "resolve__RB.json").write_text(
        json.dumps({"status": "unavailable",
                    "variety": {"variety": "RB", "enabled": False, "exchange": "SHF"}}),
        encoding="utf-8")
    report = contest_verify.verify(raw)
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["checks"]["contest_mapping"]["status"] == "blocked"
    assert rb["verdict"] == "blocked"


# ---------------------------------------------------------------- 成本口径
def test_tight_spread_confirms_cost_model(tmp_path):
    # 双边报价，半价差 (2985-2984.5)/2 ≈ 1.68bp < 2bp 假设 → 成本口径站得住
    raw = seed(tmp_path / "raw", rb_quote=quote(bid=2984.5, ask=2985.0))
    report = contest_verify.verify(raw)
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["checks"]["crossing_cost"]["status"] == "ok"
    assert rb["verdict"] == "spec_and_cost_verified"


def test_locked_board_cannot_confirm_cost(tmp_path):
    """买卖一价相同（锁死/单边）时量不出跨价成本，规格对上也不算成本已核验。"""
    raw = seed(tmp_path / "raw", rb_quote=quote(bid=2985.0, ask=2985.0))
    report = contest_verify.verify(raw)
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["checks"]["crossing_cost"]["status"] == "unavailable"
    assert rb["verdict"] == "spec_verified_cost_unmeasured"
    assert report["verdict"] == "partially_verified"


def test_wide_spread_is_called_understated_not_passing(tmp_path):
    # 半价差 (2995-2975)/2/2985 ≈ 3.35bp → 已是 2bp 假设的 1.68 倍
    raw = seed(tmp_path / "raw", rb_quote=quote(bid=2975.0, ask=2995.0))
    report = contest_verify.verify(raw)
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["checks"]["crossing_cost"]["status"] == "diverged"
    assert rb["verdict"] == "cost_model_below_market"
    assert report["verdict"] == "cost_model_below_market"
    assert any("半价差" in n for n in rb["notes"])


def test_commission_is_never_marked_verified_without_fills(tmp_path):
    report = contest_verify.verify(seed(tmp_path / "raw"))
    for product in report["spec"]["products"]:
        assert product["checks"]["commission"]["status"] == "unverified"
        assert product["checks"]["commission"]["detail"]["observed"] is None


def test_exit_code_is_nonzero_when_cost_understated(tmp_path, capsys):
    raw = seed(tmp_path / "raw", rb_quote=quote(bid=2975.0, ask=2995.0))
    assert contest_verify.main(["--raw", str(raw), "--json"]) == 1


# ---------------------------------------------------------------- 规格算式
def test_margin_per_lot_uses_multiplier_and_ratio(tmp_path):
    report = contest_verify.verify(seed(tmp_path / "raw"))
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["checks"]["contract"]["detail"]["margin_per_lot_cny"] == round(2985.0 * 10 * 0.07, 2)
    i = [p for p in report["spec"]["products"] if p["product"] == "I"][0]
    assert i["checks"]["contract"]["detail"]["margin_per_lot_cny"] == round(648.0 * 100 * 0.08, 2)


def test_missing_delivery_date_is_not_replaced_by_last_trade_date(tmp_path):
    report = contest_verify.verify(seed(tmp_path / "raw"))
    for product in report["spec"]["products"]:
        detail = product["checks"]["contract"]["detail"]
        assert detail["delivery_date"] is None
        assert detail["delivery_date_status"] == "unavailable"
        assert detail["last_trade_date"] == "20270115"


def test_near_expiry_blocks(tmp_path):
    raw = seed(tmp_path / "raw", rb_spec=spec(last_trade="20261130"))
    report = contest_verify.verify(raw)
    rb = [p for p in report["spec"]["products"] if p["product"] == "RB"][0]
    assert rb["checks"]["expiry"]["status"] == "blocked"
    assert rb["verdict"] == "blocked"


# ---------------------------------------------------------------- 执行核验
def test_no_fill_receipts_means_execution_not_verified(tmp_path):
    report = contest_verify.verify(seed(tmp_path / "raw"))
    assert report["execution"]["verdict"] == "not_verified"
    assert "不得据此声称" in report["execution"]["why"]


def test_fill_receipts_are_listed_not_judged(tmp_path):
    raw = seed(tmp_path / "raw")
    (raw / "trades__20261119.json").write_text(json.dumps({
        "trades": [{"contractCode": "rb2701", "tradeDirection": "open_long",
                    "price": 2986.0, "volume": 1, "tradeTime": "2026-11-19 09:00:01",
                    "orderId": "o1", "tradeId": "t1"}]}), encoding="utf-8")
    report = contest_verify.verify(raw)
    assert report["execution"]["verdict"] == "present_pending_review"
    assert report["execution"]["detail"]["fill_count"] == 1
    assert report["execution"]["detail"]["fills"][0]["trade_id"] == "t1"


# ---------------------------------------------------------------- 隐私与落盘
def test_identity_fields_never_reach_the_report(tmp_path, capsys):
    raw = seed(tmp_path / "raw")
    account = json.loads((raw / "account.json").read_text(encoding="utf-8"))
    account.update({"accountId": "5187", "contestId": "futures_cup_2026",
                    "username": "someone-in-the-payload", "phone": "13800000000"})
    (raw / "account.json").write_text(json.dumps(account), encoding="utf-8")

    contest_verify.main(["--raw", str(raw), "--json"])
    out = capsys.readouterr().out
    for banned in ("5187", "futures_cup_2026", "someone-in-the-payload", "13800000000"):
        assert banned not in out, "报告泄漏了身份字段：%s" % banned


def test_out_file_is_written_and_redacted(tmp_path, capsys):
    raw = seed(tmp_path / "raw")
    (raw / "account.json").write_text(
        json.dumps({"availableFunds": 5000000, "startCapital": 5000000,
                    "accountId": "5187", "username": "someone-in-the-payload"}),
        encoding="utf-8")
    out = tmp_path / "baselines" / "contest_verify.json"
    rc = contest_verify.main(["--raw", str(raw), "--out", str(out), "--json"])
    text = out.read_text(encoding="utf-8")
    assert "contract_multiplier" in text
    assert "5187" not in text and "someone-in-the-payload" not in text
    assert rc in (0, 1)
