"""期货仿真大赛核验 —— 把「等价回放」的假设拿到真实撮合环境里逐条对账。

为什么需要这个文件
------------------
任务原文要求「交易执行部分用期货模拟赛核验；品种或接口不支持时事先明确等价回放范围」。
0.7.x 走的是后半句：范围由 `scope.py` 在开跑前冻结，回放代替撮合。这没问题，但它让
一件事永远停留在假设上 —— 回测用的**成交与成本口径**（次日开盘成交、单边 3bp 手续费
+ 2bp 滑点）到底和真实盘口的执行成本差多少。单边 5bp 是个写死的常数，不是量出来的。

本文件把那个常数拿到真实数据下面对账：盘口半价差、合约乘数、保证金率、每手保证金、
最后交易日、账户可用资金，全部来自 agent 经 `panda` CLI 取回的载荷。

三条硬规矩
----------
1. **脚本不联网、不调 MCP、不读凭证**。`panda` 只能由 agent 调用；载荷由 agent 原样
   落到 `tests/fixtures/contest/raw/`（该目录 git-ignored），本脚本只读这些文件。
2. **缺证据就说不成立。** 载荷缺失、`ready=false`、没有成交回执 —— 对应的 verdict
   一律是 `not_verified` / `unavailable`，绝不因为「别的地方对上了」就顺带打个勾。
   特别是**执行核验**：没有真实成交回执时永远输出 `execution: not_verified`，
   任何人都不许把规格核验的结果读成「模拟赛已核验执行」。
3. **不含 PII**。报告只留规格与成本数字；账号、手机号、用户名一律不写入输出。

规格核验为什么也算「模拟赛核验」的一部分
------------------------------------------
它核验的是三件会改变结论的事：品种在撮合系统里**是否真的可交易**、回测假设的**单边
成本是否低估**、以及**到期与资金可行性**是否允许按 1 手执行。这三条中的任何一条偏离，
「成本后 edge」就不再是同一个意思。它不等于撮合核验，所以执行一栏必须单独为空。

用法
----
    python3 scripts/contest_verify.py                       # 默认读 tests/fixtures/contest/raw
    python3 scripts/contest_verify.py --raw <dir> --out baselines/contest_verify.json
    python3 scripts/contest_verify.py --json                # 只往 stdout 打一个 JSON 对象

退出码：0 已核验（规格与成本可下结论） / 1 结论为不成立或成本口径偏离 / 2 缺参数或缺载荷。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_RAW = HERE.parent / "tests" / "fixtures" / "contest" / "raw"

# 与 backtest.simulate_rule 的默认值同源：单边 cost_bps + slippage_bps
ASSUMED_COST_BPS = 3.0
ASSUMED_SLIPPAGE_BPS = 2.0
ASSUMED_PER_SIDE_BP = ASSUMED_COST_BPS + ASSUMED_SLIPPAGE_BPS

# 半价差超过假设单边成本的这个倍率，就认定「假设低估了真实执行成本」
COST_UNDERSTATE_RATIO = 1.5

# 到期与资金下限：回放窗口是 5 个交易日，这里用保守的日历日下限，
# 并在输出里写明它是日历日口径，不假装精确的交易日推算。
MIN_DAYS_TO_LAST_TRADE = 30

# 撮合系统里已核验过的品种；其余 SUPPORTED_PRODUCTS 一律标 not_checked，不猜。
CHECKED_PRODUCTS = ("RB", "I")

PII_KEYS = ("accountId", "contestId", "userId", "username", "phone", "name", "intro", "image")


class ContestError(Exception):
    """结构化错误：code / message / hint，与其他脚本同一形态。"""

    def __init__(self, code: str, message: str, hint: str = "", **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details


def _load(raw: Path, name: str) -> Optional[Dict[str, Any]]:
    path = raw / name
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContestError(
            "invalid_contest_payload",
            f"{name} 不是合法 JSON：{exc}",
            "重新用 agent 调 panda CLI 落盘，命令输出必须原样保存",
        ) from exc
    if not isinstance(payload, dict):
        raise ContestError("invalid_contest_payload", f"{name} 顶层必须是对象",
                           "落盘时只取信封的 data 段")
    return payload


def _bp(part: float, whole: float) -> Optional[float]:
    if not whole:
        return None
    return round(part / whole * 10_000.0, 4)


def _date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _check_product(raw: Path, product: str) -> Dict[str, Any]:
    """单个品种的规格 + 成本对账。缺件即 unavailable，不合并成「大概没问题」。"""
    quote = _load(raw, f"quote__{product}.json")
    spec = _load(raw, f"contract_spec__{product}.json")
    resolved = _load(raw, f"resolve__{product}.json")

    item: Dict[str, Any] = {
        "product": product,
        "verdict": "not_verified",
        "checks": {},
        "notes": [],
    }

    if quote is None or spec is None:
        item["notes"].append("缺 quote__%s.json 或 contract_spec__%s.json，规格无法对账" % (product, product))
        return item

    if quote.get("ready") is not True:
        item["checks"]["quote_ready"] = {"status": "blocked", "detail": "ready=false"}
        item["checks"]["contract"] = {"status": "blocked", "detail": {}}
        item["checks"]["crossing_cost"] = {"status": "blocked", "detail": {}}
        item["checks"]["commission"] = {"status": "blocked", "detail": {}}
        item["checks"]["expiry"] = {"status": "blocked", "detail": {}}
        item["verdict"] = "blocked"
        item["notes"].append("行情 ready=false：不得把 0 当最新价，本品种本次不下结论")
        return item
    item["checks"]["quote_ready"] = {"status": "ok", "detail": quote.get("quoteTime")}

    variety = (resolved or {}).get("variety") or {}
    item["checks"]["contest_mapping"] = {
        "status": "ok" if variety.get("enabled") else "blocked",
        "detail": {
            "exchange": variety.get("exchange"),
            "enabled": variety.get("enabled"),
            "resolve_status": (resolved or {}).get("status", "payload_absent"),
        },
    }

    price = float(quote.get("latestPrice") or 0.0)
    multiplier = spec.get("contractMultiplier")
    margin = spec.get("margin") or {}
    ratio = margin.get("longMarginRatioByMoney")
    per_lot_margin = (
        round(price * float(multiplier) * float(ratio), 2)
        if price and multiplier and ratio else None
    )
    item["checks"]["contract"] = {
        "status": "ok",
        "detail": {
            "contract_code": quote.get("contractCode"),
            "latest_price": price,
            "contract_multiplier": multiplier,
            "margin_ratio_pct": round(float(ratio) * 100, 4) if ratio is not None else None,
            "margin_per_lot_cny": per_lot_margin,
            # 交割日与最后交易日是两件事：缺就是暂无数据，绝不拿 lastTradeDate 顶替。
            "last_trade_date": spec.get("lastTradeDate"),
            "delivery_date": spec.get("deliveryDate"),
            "delivery_date_status": "ok" if spec.get("deliveryDate") else "unavailable",
        },
    }

    # --- 执行成本对账：本文件的核心 ---
    # 配对口径要挑对：滑点（slippage_bps）对应的是**跨价成交**的那一项，
    # 手续费（cost_bps）只能由成交/结算回执量出来。拿半价差去比「滑点+手续费」合计，
    # 会把一个已被证伪的假设算成通过 —— 这正是要防的那种错。
    bid, ask = quote.get("bidPrice1"), quote.get("askPrice1")
    spread_bp = None
    half_spread_bp = None
    if bid and ask and float(ask) >= float(bid) > 0:
        mid = (float(ask) + float(bid)) / 2.0
        spread_bp = _bp(float(ask) - float(bid), mid)
        half_spread_bp = _bp((float(ask) - float(bid)) / 2.0, mid)
    slip_ratio = (
        round(float(half_spread_bp) / ASSUMED_SLIPPAGE_BPS, 3)
        if half_spread_bp else None
    )
    crossing = {
        "status": "ok" if half_spread_bp else "unavailable",
        "detail": {
            "assumed_slippage_bp_per_side": ASSUMED_SLIPPAGE_BPS,
            "bid_price1": bid,
            "ask_price1": ask,
            "quoted_spread_bp": spread_bp,
            "half_spread_bp_per_side": half_spread_bp,
            "half_spread_over_assumed_slippage": slip_ratio,
        },
    }
    if slip_ratio is not None and slip_ratio > COST_UNDERSTATE_RATIO:
        crossing["status"] = "diverged"
        item["notes"].append(
            "回测单边滑点假设 %gbp，盘口半价差实测 %.2fgbp（%.2fx）：市价 IOC 至少要吃掉这一层，"
            "「成本后 edge」比报告更薄" % (ASSUMED_SLIPPAGE_BPS, float(half_spread_bp), slip_ratio)
        )
    item["checks"]["crossing_cost"] = crossing

    # 手续费：没有回执就没有观测值。settlements.commission 为 0 只说明还没成交，
    # 不能读成「手续费为 0」。
    item["checks"]["commission"] = {
        "status": "unverified",
        "detail": {
            "assumed_fee_bp_per_side": ASSUMED_COST_BPS,
            "assumed_round_trip_bp": round(ASSUMED_PER_SIDE_BP * 2, 4),
            "observed": None,
            "why": "手续费只能由成交/结算回执量出；当前无成交回执，0 不等于免费",
        },
    }


    # --- 到期与资金可行性 ---
    last_trade = _date(spec.get("lastTradeDate"))
    trade_day = _date(quote.get("tradeDate"))
    if last_trade and trade_day:
        days_left = (last_trade - trade_day).days
        item["checks"]["expiry"] = {
            "status": "ok" if days_left >= MIN_DAYS_TO_LAST_TRADE else "blocked",
            "detail": {"calendar_days_to_last_trade": days_left,
                       "floor_days": MIN_DAYS_TO_LAST_TRADE,
                       "basis": "日历日下限，不是精确交易日推算"},
        }
    else:
        item["checks"]["expiry"] = {"status": "unavailable", "detail": {}}

    diverged = any(c["status"] == "diverged" for c in item["checks"].values())
    blocked = any(c["status"] == "blocked" for c in item["checks"].values())
    unmeasured = item["checks"]["crossing_cost"]["status"] == "unavailable"
    if blocked:
        item["verdict"] = "blocked"
    elif diverged:
        item["verdict"] = "cost_model_below_market"
    elif unmeasured:
        # 盘口同价（锁死或单边）量不出跨价成本。规格对上了也不能叫「成本已核验」，
        # 否则一个涨跌停板就能把这条闸门骗过去。
        item["verdict"] = "spec_verified_cost_unmeasured"
        item["notes"].append("买卖一价相同：半价差量不出真实跨价成本，本品种只算规格核验")
    else:
        item["verdict"] = "spec_and_cost_verified"
    return item


def _check_fills(raw: Path) -> Dict[str, Any]:
    """执行核验：只有真实成交回执存在时才可能下结论，否则永远是 not_verified。"""
    trades = sorted(raw.glob("trades__*.json"))
    orders = sorted(raw.glob("orders__*.json"))
    if not trades:
        return {
            "verdict": "not_verified",
            "detail": {
                "orders_payloads": [p.name for p in orders],
                "trades_payloads": [p.name for p in trades],
            },
            "why": "没有真实成交回执。规格与成本对账不等于撮合核验，"
                   "不得据此声称「模拟赛已核验执行口径」。",
        }
    fills: List[Dict[str, Any]] = []
    for path in trades:
        payload = _load(raw, path.name) or {}
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else payload.get("trades", [])
        for row in rows or []:
            fills.append({
                "source": path.name,
                "contract_code": row.get("contractCode"),
                "direction": row.get("tradeDirection"),
                "price": row.get("price"),
                "volume": row.get("volume"),
                "trade_time": row.get("tradeTime"),
                "order_id": row.get("orderId"),
                "trade_id": row.get("tradeId"),
            })
    return {
        "verdict": "present_pending_review" if fills else "empty",
        "detail": {"fills": fills, "fill_count": len(fills)},
        "why": "已落盘成交回执；逐笔与「次日开盘成交 + 单边 5bp」的对照需要对应交易日的"
               "日线与委托回执，由 --fills 之后的复算步骤给出，本步不预判结论。",
    }


def _check_capital(raw: Path) -> Dict[str, Any]:
    account = _load(raw, "account.json")
    if account is None:
        return {"verdict": "unavailable", "detail": {}, "why": "缺 account.json"}
    available = account.get("availableFunds")
    return {
        "verdict": "ok",
        "detail": {
            "available_funds": available,
            "start_capital": account.get("startCapital"),
            "margin_used": account.get("margin"),
            "risk_rate": account.get("riskRate"),
            "trade_date": account.get("tradeDate"),
        },
        "why": "只用资金规模判断「1 手是否负担得起」，不据此推断策略好坏。",
    }


def verify(raw_dir: Path) -> Dict[str, Any]:
    raw = Path(raw_dir)
    if not raw.is_dir():
        raise ContestError(
            "missing_contest_payload",
            f"落盘目录不存在：{raw}",
            "先由 agent 调 panda CLI 取回 quote / contract-spec / resolve / account，"
            "剥掉账号与手机号后原样写入该目录",
        )
    products = [_check_product(raw, p) for p in CHECKED_PRODUCTS]
    if not any(p["verdict"] != "not_verified" for p in products):
        raise ContestError(
            "missing_contest_payload",
            "所有品种的规格载荷都缺失，无法对账",
            "落盘 quote__RB.json / contract_spec__RB.json（I 同理）后重试",
        )

    overall = "spec_and_cost_verified"
    if any(p["verdict"] == "cost_model_below_market" for p in products):
        overall = "cost_model_below_market"
    if any(p["verdict"] in ("blocked", "not_verified", "spec_verified_cost_unmeasured")
           for p in products):
        overall = "partially_verified"

    return {
        "kind": "contest-verification",
        "verdict": overall,
        "spec": {
            "checked_products": CHECKED_PRODUCTS,
            "unchecked_products_note": "其余 SUPPORTED_PRODUCTS 未核验，不猜测其可交易性",
            "products": products,
        },
        "execution": _check_fills(raw),
        "capital": _check_capital(raw),
        "assumptions_reconciled": {
            "fill_model": "next-bar open（backtest.simulate_rule）",
            "cost_per_side_bp": ASSUMED_PER_SIDE_BP,
            "cost_round_trip_bp": round(ASSUMED_PER_SIDE_BP * 2, 4),
            "one_lot_per_rule": True,
        },
        "redaction": "报告只含规格与成本数字；账号、手机号、用户名、俱乐部信息不落盘",
    }


def _strip_pii(node: Any) -> Any:
    """防御性再洗一遍：载荷里混进身份字段也不会出现在报告里。"""
    if isinstance(node, dict):
        return {k: _strip_pii(v) for k, v in node.items() if k not in PII_KEYS}
    if isinstance(node, list):
        return [_strip_pii(v) for v in node]
    return node


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="contest_verify.py", description=__doc__.splitlines()[0])
    parser.add_argument("--raw", default=str(DEFAULT_RAW), help="agent 落盘的仿真大赛载荷目录")
    parser.add_argument("--out", help="把报告写到该路径（建议 baselines/contest_verify.json）")
    parser.add_argument("--json", action="store_true", help="stdout 只输出一个 JSON 对象")
    args = parser.parse_args(argv)

    try:
        report = _strip_pii(verify(Path(args.raw)))
    except ContestError as exc:
        payload = {"ok": False, "error": {"code": exc.code, "message": exc.message,
                                          "hint": exc.hint, "details": exc.details}}
        print(json.dumps(payload, ensure_ascii=False))
        return 2

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["written_to"] = str(out)

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        _render(report)
    return 1 if report["verdict"] in ("cost_model_below_market", "partially_verified") else 0


def _render(report: Dict[str, Any]) -> None:
    print("仿真大赛核验 verdict：%s" % report["verdict"])
    for product in report["spec"]["products"]:
        print("\n[%s] %s" % (product["product"], product["verdict"]))
        for name, check in product["checks"].items():
            print("  - %-16s %s" % (name, check["status"]))
            if isinstance(check["detail"], dict):
                for key, value in check["detail"].items():
                    print("        %s: %s" % (key, value))
        for note in product["notes"]:
            print("  ! %s" % note)
    print("\n执行核验：%s" % report["execution"]["verdict"])
    print("  %s" % report["execution"]["why"])
    if report["execution"].get("detail", {}).get("fills"):
        for fill in report["execution"]["detail"]["fills"]:
            print("  · %s" % json.dumps(fill, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
