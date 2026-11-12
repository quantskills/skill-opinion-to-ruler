"""Cost-aware, no-look-ahead evaluation of extracted rules against a frozen baseline.

The backtester is deliberately small: the deliverable's claim is *auditability*,
not alpha. Every rule is simulated exactly as extracted; nothing is tuned on the
evaluation window.

Baseline
--------
``hold``         — long the same instrument over the identical holding window.
                   This is the "simple baseline" the task requires.
``cash``         — flat; every rule trade is measured against zero return.

Both are *paired* : each rule trade is compared with the baseline over the same
dates, so market drift is removed from the difference.

Verdict
-------
``positive``      — paired edge > 0 with bootstrap CI excluding 0 and >= MIN_TRADES
``negative``      — baseline agnostic; enough trades but no significant edge
``inconclusive``  — too few trades, or CI straddles 0

A negative verdict is a valid deliverable: it means "this opinion, rule-ified and
cost-charged, does not beat holding".
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence

BARS_PER_YEAR = 244
MIN_TRADES = 12


class BacktestError(ValueError):
    """Raised for malformed bars or rules."""


def _norm_date(value: Any) -> str:
    return str(value).replace("-", "")[:8]


def parse_expr(expr: str):
    """Parse ``close > 3800`` / ``close <= 5`` into ``(op, level)``."""
    if not expr:
        return None
    parts = expr.strip().split()
    if len(parts) != 3 or parts[0] != "close":
        raise BacktestError(f"unsupported expression: {expr!r}")
    op, raw = parts[1], parts[2]
    ops = {">": "gt", ">=": "ge", "<": "lt", "<=": "le"}
    if op not in ops:
        raise BacktestError(f"unsupported operator in {expr!r}")
    try:
        level = float(raw)
    except ValueError as exc:
        raise BacktestError(f"non-numeric level in {expr!r}") from exc
    return ops[op], level


def _hit(op: str, level: float, close: float) -> bool:
    return {
        "gt": close > level,
        "ge": close >= level,
        "lt": close < level,
        "le": close <= level,
    }[op]


def _bars_after(bars: Sequence[Dict[str, Any]], published_at: Optional[str]) -> List[Dict[str, Any]]:
    """Strictly-after filter. The document's publish date is never tradable."""
    if published_at is None:
        raise BacktestError("published_at is required to guarantee no look-ahead")
    cut = _norm_date(published_at)
    return [b for b in bars if b["date"] > cut]


def simulate_rule(rule: Dict[str, Any], bars: Sequence[Dict[str, Any]],
                  cost_bps: float = 3.0, slippage_bps: float = 2.0) -> Dict[str, Any]:
    """Simulate one rule. Returns a trade record, or a skip record with a reason."""
    base = {"rule_id": rule.get("rule_id"), "symbol": None, "status": "skipped"}
    instrument = rule.get("instrument")
    if instrument is None:
        base["reason"] = "no instrument"
        return base
    base["symbol"] = instrument.get("symbol")

    if rule.get("testability") not in ("full", "partial"):
        base["reason"] = f"testability={rule.get('testability')}"
        return base

    horizon = rule.get("horizon") or {}
    hold_days = int(horizon.get("value") or 0)
    if hold_days <= 0:
        base["reason"] = "no usable horizon"
        return base

    if not rule.get("published_at"):
        base["reason"] = "published_at missing; refusing to simulate (look-ahead risk)"
        return base

    window = _bars_after(bars, rule.get("published_at"))
    if not window:
        base["reason"] = "no bars after published_at"
        return base

    entry = rule.get("entry_trigger") or {}
    exit_rule = rule.get("exit_rule")
    stop_rule = rule.get("stop_loss")
    direction = rule["direction"]
    sign = 1 if direction == "long" else -1

    entry_cond = parse_expr(entry.get("expr")) if entry.get("type") == "price_condition" else None
    stop_cond = parse_expr(stop_rule["expr"]) if stop_rule else None
    exit_cond = parse_expr(exit_rule["expr"]) if exit_rule else None

    # ---- entry -----------------------------------------------------------
    entry_idx = None
    for i, bar in enumerate(window):
        if entry_cond is None:
            entry_idx = i  # market on next open
            break
        op, level = entry_cond
        if _hit(op, level, bar["close"]):
            entry_idx = i
            break
    if entry_idx is None:
        base["reason"] = "entry condition never triggered within available bars"
        return base

    # Fill at the *next* bar's open so a close-based signal is tradable.
    fill_idx = entry_idx + 1
    if fill_idx >= len(window):
        base["reason"] = "no bar available to fill after the trigger"
        return base
    entry_price = window[fill_idx]["open"] or window[fill_idx]["close"]

    # ---- exit ------------------------------------------------------------
    exit_idx = None
    exit_reason = None
    last_check = fill_idx
    for i in range(fill_idx, len(window)):
        bar = window[i]
        last_check = i
        if stop_cond and _hit(*stop_cond, bar["close"]):
            exit_idx, exit_reason = i, "stop_loss"
            break
        if exit_cond and _hit(*exit_cond, bar["close"]):
            exit_idx, exit_reason = i, "target"
            break
        if i - fill_idx >= hold_days - 1:
            exit_idx, exit_reason = i, "horizon"
            break

    if exit_idx is None:
        exit_idx, exit_reason = last_check, "data_end"

    exit_price = window[exit_idx]["close"]
    held = exit_idx - fill_idx + 1

    gross = sign * (exit_price / entry_price - 1.0)
    cost = (cost_bps + slippage_bps) * 2 / 10_000.0
    net = gross - cost

    return {
        "rule_id": rule.get("rule_id"),
        "symbol": instrument.get("symbol"),
        "direction": direction,
        "status": "traded",
        "entry_date": window[fill_idx]["date"],
        "exit_date": window[exit_idx]["date"],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "held_bars": held,
        "gross_return": round(gross, 6),
        "cost": round(cost, 6),
        "net_return": round(net, 6),
        "exit_reason": exit_reason,
        "signal_basis": entry.get("type"),
        "stop_used": bool(stop_rule),
        "exit_used": bool(exit_rule),
    }


def baseline_return(bars: Sequence[Dict[str, Any]], entry_date: str, exit_date: str,
                    cost_bps: float = 3.0, slippage_bps: float = 2.0) -> Optional[float]:
    """Paired long-hold return over the identical dates."""
    by_date = {b["date"]: i for i, b in enumerate(bars)}
    if entry_date not in by_date or exit_date not in by_date:
        return None
    i0, i1 = by_date[entry_date], by_date[exit_date]
    if i1 <= i0:
        return None
    gross = bars[i1]["close"] / bars[i0]["open"] - 1.0
    return gross - (cost_bps + slippage_bps) * 2 / 10_000.0


def _bootstrap_ci(values: List[float], iters: int = 2000, seed: int = 20240101) -> Dict[str, float]:
    if not values:
        return {"mean": 0.0, "lo": 0.0, "hi": 0.0}
    rng = random.Random(seed)
    n = len(values)
    means = []
    for _ in range(iters):
        means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return {
        "mean": sum(values) / n,
        "lo": means[int(0.025 * iters)],
        "hi": means[int(0.975 * iters) - 1],
    }


def _sharpe(returns: List[float]) -> Optional[float]:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    sd = math.sqrt(var)
    return None if sd == 0 else round(mean / sd * math.sqrt(BARS_PER_YEAR), 3)


def _max_drawdown(returns: List[float]) -> float:
    equity, peak, worst = 1.0, 1.0, 0.0
    for r in returns:
        equity *= 1.0 + r
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return round(worst, 6)


def decide_verdict(edge: Dict[str, float], trades: int, min_trades: int = MIN_TRADES) -> str:
    """Deterministic and reproducible — no subjective judgement."""
    if trades < min_trades:
        return "inconclusive"
    if edge["mean"] > 0 and edge["lo"] > 0:
        return "positive"
    if edge["mean"] <= 0 and edge["hi"] < 0:
        return "negative"
    if edge["mean"] <= 0:
        return "negative" if edge["hi"] <= 0 else "inconclusive"
    return "inconclusive"


def evaluate(rules: Sequence[Dict[str, Any]], bars_by_symbol: Dict[str, List[Dict[str, Any]]],
             cost_bps: float = 3.0, slippage_bps: float = 2.0,
             baseline: str = "hold") -> Dict[str, Any]:
    """Run every rule and compare each trade with its paired baseline."""
    if baseline not in ("hold", "cash"):
        raise BacktestError("baseline must be 'hold' or 'cash'")

    trades, skips = [], []
    for rule in rules:
        symbol = (rule.get("instrument") or {}).get("symbol")
        bars = bars_by_symbol.get(symbol)
        if bars is None:
            skips.append({"rule_id": rule.get("rule_id"), "reason": f"no bars for {symbol}"})
            continue
        record = simulate_rule(rule, bars, cost_bps, slippage_bps)
        if record["status"] != "traded":
            skips.append({"rule_id": record["rule_id"], "reason": record["reason"]})
            continue
        if baseline == "hold":
            base = baseline_return(bars, record["entry_date"], record["exit_date"], cost_bps, slippage_bps)
            record["baseline_return"] = None if base is None else round(base, 6)
            record["edge"] = None if base is None else round(record["net_return"] - base, 6)
        else:
            record["baseline_return"] = 0.0
            record["edge"] = record["net_return"]
        trades.append(record)

    net = [t["net_return"] for t in trades]
    edges = [t["edge"] for t in trades if t["edge"] is not None]
    ci = _bootstrap_ci(edges)
    verdict = decide_verdict(ci, len(edges))

    by_reason: Dict[str, int] = {}
    for t in trades:
        by_reason[t["exit_reason"]] = by_reason.get(t["exit_reason"], 0) + 1

    return {
        "baseline": baseline,
        "cost_bps": cost_bps,
        "slippage_bps": slippage_bps,
        "trades": trades,
        "skips": skips,
        "metrics": {
            "trades": len(trades),
            "skipped": len(skips),
            "win_rate": round(sum(1 for r in net if r > 0) / len(net), 4) if net else 0.0,
            "mean_net_return": round(sum(net) / len(net), 6) if net else 0.0,
            "total_net_return": round(sum(net), 6),
            "sharpe": _sharpe(net),
            "max_drawdown": _max_drawdown(net),
            "mean_baseline_return": round(sum(t["baseline_return"] for t in trades if t["baseline_return"] is not None)
                                          / max(1, len([t for t in trades if t["baseline_return"] is not None])), 6),
            "exit_reasons": by_reason,
        },
        "edge": {
            "mean": round(ci["mean"], 6),
            "ci_low": round(ci["lo"], 6),
            "ci_high": round(ci["hi"], 6),
            "n": len(edges),
        },
        "verdict": verdict,
    }


def value_assessment(backtest: Dict[str, Any]) -> Dict[str, Any]:
    """The three questions the deliverable must answer."""
    m, edge = backtest["metrics"], backtest["edge"]
    changed = sum(1 for t in backtest["trades"] if t["direction"] in ("long", "short"))
    return {
        "decisions_created": changed,
        "decision_change_examples": [
            {
                "rule_id": t["rule_id"],
                "would_trade": f"{t['direction']} {t['symbol']}",
                "baseline_alternative": "hold" if backtest["baseline"] == "hold" else "stay flat",
                "net_return": t["net_return"],
                "baseline_return": t["baseline_return"],
            }
            for t in backtest["trades"][:5]
        ],
        "effect_size": {
            "mean_paired_edge": edge["mean"],
            "ci_low": edge["ci_low"],
            "ci_high": edge["ci_high"],
            "n_trades": edge["n"],
            "win_rate": m["win_rate"],
            "sharpe": m["sharpe"],
            "max_drawdown": m["max_drawdown"],
        },
        "verdict": backtest["verdict"],
        "note": "verdict=negative or inconclusive is a valid result; it bounds where the signal works.",
    }


def applicability(backtest: Dict[str, Any], coverage: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "in_scope": [
            "daily-close rules on futures products supported by the instrument alias table",
            "rules whose horizon is expressed in trading days",
            "evaluation on bars strictly after the opinion's publish date",
        ],
        "out_of_scope": [
            "intraday entries, limit-order fills, auction mechanics",
            "position sizing interactions across simultaneous rules",
            "products absent from the alias table (they map to no symbol)",
            "continuous-contract adjustment: segments are stitched at unadjusted prices, so a roll gap remains visible",
        ],
        "fails_when": [
            "fewer than %d trades" % MIN_TRADES,
            "the opinion has no numeric levels and no explicit direction",
            "bars are missing for the mapped symbol",
        ],
        "coverage": coverage,
    }