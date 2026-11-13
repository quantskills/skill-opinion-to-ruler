"""End-to-end acceptance run: extract -> label check -> backtest -> verdict.

This is the script the acceptance document refers to. It is deliberately one
command and writes a machine-readable report plus a frozen baseline snapshot.

Usage
-----
Evaluate the bundled fixture (no network)::

    python3 scripts/evaluate.py --fixture

Evaluate with panda_data (requires credentials)::

    python3 scripts/evaluate.py --panda --start 20240101 --end 20241231

Compare against a previously frozen run::

    python3 scripts/evaluate.py --fixture --baseline-output output/baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import annotate  # noqa: E402
from backtest import applicability, evaluate, value_assessment  # noqa: E402
from build import run  # noqa: E402
from data_loader import DataUnavailable, credentials_source, load_bars  # noqa: E402
from scope import declare_scope, verify_scope  # noqa: E402

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
SCOPE_PATH = os.path.join(ROOT, "output", "scope_declaration.json")


def _load_fixture(name: str) -> Dict[str, Any]:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def _bars_for(rules: List[Dict[str, Any]], args) -> Dict[str, List[Dict[str, Any]]]:
    symbols = sorted({(r.get("instrument") or {}).get("symbol") for r in rules
                      if (r.get("instrument") or {}).get("symbol")})
    bars_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for symbol in symbols:
        csv_path = os.path.join(FIXTURE_DIR, f"bars_{symbol}.csv")
        try:
            if args.fixture:
                loaded = load_bars(symbol, args.start, args.end,
                                   csv_path=csv_path if os.path.exists(csv_path) else None)
            else:
                loaded = load_bars(symbol, args.start, args.end)
        except DataUnavailable as exc:
            print(f"[skip] {symbol}: {exc}", file=sys.stderr)
            continue
        bars_by_symbol[symbol] = loaded["bars"]
        print(f"[data] {symbol}: {len(loaded['bars'])} bars from {loaded['source']}")
    return bars_by_symbol


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help="use bundled CSV bars (offline)")
    parser.add_argument("--panda", action="store_true", help="use panda_data bars")
    parser.add_argument("--start", default="20240101")
    parser.add_argument("--end", default="20241231")
    parser.add_argument("--labels", default=os.path.join(FIXTURE_DIR, "labels.json"))
    parser.add_argument("--opinions", default=os.path.join(FIXTURE_DIR, "opinions.json"))
    parser.add_argument("--baseline-output", default=os.path.join(ROOT, "output", "frozen_baseline.json"))
    parser.add_argument("--commission-bps", type=float, default=3.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--min-trades", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.fixture and not args.panda:
        parser.error("choose --fixture (offline) or --panda (live data)")

    opinions = _load_fixture(os.path.basename(args.opinions)) if args.opinions.startswith(FIXTURE_DIR) else json.load(open(args.opinions, encoding="utf-8"))
    extracted = run(opinions, {"apply_defaults": True})
    rules = [r for d in extracted["documents"] for r in d["rules"]]

    # ---- scope is declared BEFORE any bar is fetched or any trade is simulated
    scope = declare_scope(
        extracted,
        data_mode="fixture" if args.fixture else "panda",
        start=args.start,
        end=args.end,
        baseline="hold",
        cost_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        min_trades=args.min_trades,
    )
    os.makedirs(os.path.dirname(SCOPE_PATH), exist_ok=True)
    with open(SCOPE_PATH, "w", encoding="utf-8") as fh:
        json.dump(scope, fh, ensure_ascii=False, indent=2)
    print(f"[scope] declared before run: {len(scope['declared_symbols'])} symbol(s) "
          f"{scope['declared_symbols']} over {args.start}..{args.end}  hash={scope['scope_hash'][:12]}")

    bars_by_symbol = _bars_for(rules, args)
    backtest = evaluate(rules, bars_by_symbol, baseline="hold",
                        cost_bps=args.commission_bps, slippage_bps=args.slippage_bps,
                        min_trades=args.min_trades)
    verification = verify_scope(scope, bars_by_symbol, backtest["trades"], backtest["skips"])

    labels_path = args.labels
    extraction_score = None
    if os.path.exists(labels_path):
        with open(labels_path, encoding="utf-8") as fh:
            extraction_score = annotate.score(json.load(fh))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_mode": "fixture" if args.fixture else "panda",
        "credentials_source": "n/a" if args.fixture else credentials_source(),
        "extraction": {
            "summary": extracted["summary"],
            "config_hash": extracted["config_hash"],
            "accuracy": extraction_score,
        },
        "backtest": backtest,
        "scope_declaration": scope,
        "scope_verification": verification,
        "value_assessment": value_assessment(backtest),
        "applicability": applicability(backtest, extracted["summary"], scope=scope,
                                       verification=verification),
    }

    os.makedirs(os.path.dirname(args.baseline_output), exist_ok=True)
    with open(args.baseline_output, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    s, m, e = extracted["summary"], backtest["metrics"], backtest["edge"]
    print(f"\nrules: {s['rules_total']} (full={s['rules_full']}, partial={s['rules_partial']}, "
          f"neutral={s['rules_neutral']}, unruleable={s['unruleable']})")
    if extraction_score:
        print(f"extraction exact-match: {extraction_score['overall_exact_match']}")
    print(f"trades: {m['trades']}  skipped: {m['skipped']}")
    print(f"mean net: {m['mean_net_return']}  win rate: {m['win_rate']}  sharpe: {m['sharpe']}  "
          f"maxDD: {m['max_drawdown']}")
    print(f"paired edge vs hold: {e['mean']}  CI [{e['ci_low']}, {e['ci_high']}]  n={e['n']}")
    print(f"verdict: {backtest['verdict'].upper()}")
    if verification["violations"]:
        print("SCOPE VIOLATIONS:")
        for v in verification["violations"]:
            print(f"  - {v}")
    else:
        print(f"scope honoured: {verification['symbols_traded']} traded, "
              f"span {verification['trade_span']}")
    print(f"report: {args.baseline_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())