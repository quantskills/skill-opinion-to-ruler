"""Pre-run scope declaration.

The task requires that the equivalent-replay range be stated **before** the run,
not chosen after seeing results. This module enforces that order:

1. ``declare_scope`` is built from *inputs only* (opinions, args, frozen config).
   It cannot see a single trade.
2. It is written to disk and hashed.
3. The backtest runs.
4. ``verify_scope`` compares what was declared against what actually happened.

A mismatch is recorded rather than hidden, so a reader can tell whether the
reported numbers sit inside the range that was promised.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence

SCOPE_VERSION = "scope-v1"

# Products the instrument alias table can map. Kept explicit so the declaration
# names the universe instead of saying "whatever we happened to use".
SUPPORTED_PRODUCTS = ("RB", "I", "HC", "SS", "J", "JM", "CU", "AL", "ZN", "NI",
                      "PB", "SN", "AU", "AG", "SC", "FU", "BU", "M", "Y", "P",
                      "RM", "OI", "MA", "SR", "CF", "FG", "SA", "UR", "PP", "L",
                      "C", "CS", "JD", "AP", "CJ", "PK", "SF", "SM", "SP", "RU",
                      "IF", "IH", "IC", "IM")

REPLAY_EQUIVALENCE = {
    "what_this_is": "daily bar replay (close-to-close with next-open fills)",
    "what_this_is_not": [
        "a futures simulation contest / matching engine",
        "intraday or tick-level execution",
        "margin, force-liquidation or capital-competition modelling",
    ],
    "why_equivalent": (
        "the rule set is declared in trading-day horizons and daily-close triggers, "
        "so a daily replay resolves every decision point the rules can express"
    ),
    "where_it_breaks": [
        "rules that depend on intraday touch order",
        "limit-locked sessions where no fill is possible",
        "portfolio-level capital allocation across simultaneous rules",
        "roll gaps from unadjusted dominant stitching",
    ],
}


def _symbols_from_opinions(extracted: Dict[str, Any]) -> List[str]:
    out = set()
    for doc in extracted["documents"]:
        for rule in doc["rules"] + doc["unruleable"]:
            sym = (rule.get("instrument") or {}).get("symbol")
            if sym:
                out.add(sym)
    return sorted(out)


def _unmapped(extracted: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rules that name a direction but have no tradable symbol."""
    out = []
    for doc in extracted["documents"]:
        for rule in doc["rules"] + doc["unruleable"]:
            if rule.get("instrument") is None and rule.get("direction") in ("long", "short"):
                out.append({
                    "rule_id": rule.get("rule_id"),
                    "source_text": rule.get("source_text"),
                    "direction": rule.get("direction"),
                    "reason": "no symbol in the futures alias table",
                })
    return out


def declare_scope(extracted: Dict[str, Any], data_mode: str, start: str, end: str,
                  baseline: str, cost_bps: float, slippage_bps: float,
                  min_trades: int) -> Dict[str, Any]:
    """Build the declaration from inputs only. Must run before the backtest."""
    declared_symbols = _symbols_from_opinions(extracted)
    outside = [s for s in declared_symbols if s not in SUPPORTED_PRODUCTS]

    scope = {
        "scope_version": SCOPE_VERSION,
        "declared_before_backtest": True,
        "data_mode": data_mode,
        "date_range": {"start": start, "end": end},
        "declared_symbols": declared_symbols,
        "supported_universe": list(SUPPORTED_PRODUCTS),
        "symbols_outside_universe": outside,
        "unmapped_rules": _unmapped(extracted),
        "baseline": baseline,
        "cost_model": {"commission_bps": cost_bps, "slippage_bps": slippage_bps, "sides": 2},
        "min_trades_for_verdict": min_trades,
        "replay_equivalence": REPLAY_EQUIVALENCE,
        "extraction_config_hash": extracted.get("config_hash"),
        "in_scope": [
            f"daily-close rules on {', '.join(declared_symbols) or 'no mapped symbol'}"
            f" over {start}..{end}",
            "horizons expressed in trading days",
            "bars strictly after each opinion's published_at",
        ],
        "out_of_scope": [
            "futures simulation contest / live matching",
            "intraday entries, limit-order fills, auction mechanics",
            "position sizing across simultaneous rules",
            "products outside the declared symbol list",
            "roll adjustment (unadjusted dominant stitching is used)",
        ],
        "fails_when": [
            f"fewer than {min_trades} closed trades",
            "a rule has no numeric level and no explicit direction",
            "bars are missing for a declared symbol",
        ],
    }
    scope["scope_hash"] = hashlib.sha256(
        json.dumps(scope, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return scope


def verify_scope(scope: Dict[str, Any], bars_by_symbol: Dict[str, Sequence[Dict[str, Any]]],
                 trades: Sequence[Dict[str, Any]], skips: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare the promise against what actually happened."""
    declared = list(scope["declared_symbols"])
    used = sorted(bars_by_symbol)
    missing = [s for s in declared if s not in used]
    extra = [s for s in used if s not in declared]

    actual_symbols = sorted({t.get("symbol") for t in trades if t.get("symbol")})
    undeclared_trades = [s for s in actual_symbols if s not in declared]

    dates = [t.get("entry_date") for t in trades if t.get("entry_date")]
    trade_span = {"first": min(dates), "last": max(dates)} if dates else None
    start, end = scope["date_range"]["start"], scope["date_range"]["end"]

    violations: List[str] = []
    if missing:
        violations.append(f"declared symbol(s) produced no bars: {missing}")
    if extra:
        violations.append(f"bars fetched for undeclared symbol(s): {extra}")
    if undeclared_trades:
        violations.append(f"trades on undeclared symbol(s): {undeclared_trades}")
    if trade_span and (trade_span["first"] < start or trade_span["last"] > end):
        violations.append(
            f"trade span {trade_span['first']}..{trade_span['last']} escapes declared "
            f"range {start}..{end}"
        )

    return {
        "scope_hash": scope["scope_hash"],
        "symbols_declared": declared,
        "symbols_with_bars": used,
        "symbols_traded": actual_symbols,
        "trade_span": trade_span,
        "declared_range": [start, end],
        "skipped_rules": len(skips),
        "violations": violations,
        "honoured": not violations,
    }