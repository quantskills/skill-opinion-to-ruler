"""End-to-end acceptance run: extract -> label check -> backtest -> verdict.

This is the script the acceptance document refers to. It is deliberately one
command and writes a machine-readable report plus a frozen baseline snapshot.

Data comes from local files only — there is no network path in this skill, and
MCP tools can only be called by an agent anyway. Real data therefore arrives in
three steps (see ``references/mcp-data.md``)::

    ① agent: mcp__pandadata__call_pandadata(method=get_future_daily /
                                          get_future_dominant, params=...)
    ② agent: verbatim payload -> tests/fixtures/raw/<method>__<label>.json
    ③ python3 scripts/mcp_landing.py --build   # truncation guard, writes this
                                             # skill's own CSV schema
    ④ python3 scripts/evaluate.py --landed-dir tests/fixtures/landed ...

Usage
-----
Evaluate the bundled synthetic fixture (no fetch needed)::

    python3 scripts/evaluate.py --fixture

Evaluate against bars built from landed MCP payloads::

    python3 scripts/evaluate.py --landed-dir tests/fixtures/landed \\
        --start 20240101 --end 20241231

Compare against a previously frozen run::

    python3 scripts/evaluate.py --fixture --baseline-output output/baseline.json

Check this run against the *shipped* frozen reference (read-only; exit 1 and a
field-by-field diff when the numbers moved)::

    python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json

``--baseline-output`` writes a **product** (default ``output/``, git-ignored).
The **reference** is the committed ``baselines/frozen_baseline.json``; a run
never writes to it. See ``scripts/compare_baseline.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import annotate  # noqa: E402
from backtest import applicability, evaluate, value_assessment  # noqa: E402
from build import run  # noqa: E402
import compare_baseline  # noqa: E402
from data_loader import (  # noqa: E402
    COVERAGE_POLICIES,
    DEFAULT_LANDED_DIR,
    DataUnavailable,
    data_provenance,
    load_bars,
    portable_dir,
)
from scope import declare_scope, verify_scope  # noqa: E402

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
# Runtime landing spot for this run's scope declaration (a product; `output/` is
# git-ignored). The committed reference is baselines/scope_declaration.json, and
# this script never writes there.
SCOPE_PATH = os.path.join(ROOT, "output", "scope_declaration.json")


def _location_bases() -> List[Tuple[str, str]]:
    """Named places a product could go, each resolved defensively.

    ``os.getcwd()`` and ``tempfile.gettempdir()`` can both raise -- a process whose
    working directory has been unlinked or is unreadable looks exactly like a
    sandboxed or packaged run. A location we cannot name is simply not a candidate;
    it must never take the whole report down. An earlier revision of this helper
    called ``getcwd()`` eagerly, so the fallback machinery itself became the crash
    the fallback existed to prevent.
    """
    bases: List[Tuple[str, str]] = []
    try:
        bases.append((os.getcwd(), "working directory"))
    except OSError:
        pass
    bases.append((ROOT, "skill directory"))
    try:
        bases.append((os.path.join(tempfile.gettempdir(), "skill-opinion-to-ruler"),
                      "system temporary directory"))
    except OSError:
        pass
    return bases


def _product_candidates(path: str) -> List[Tuple[str, str]]:
    """Where a regenerated product may land, best-first.

    The requested path comes first: in a checkout ``<skill>/output`` is writable
    and is the documented location. The rest only matter for an *installed* tree,
    which is read-only -- and which is frequently also the working directory, so
    "fall back to ./output" is not a fallback at all there.
    """
    name = os.path.basename(path)
    out = [(path, "requested location")]
    try:
        wanted = os.path.abspath(path)
    except OSError:                    # relative path + unreadable cwd
        wanted = path
    for base, why in _location_bases():
        candidate = os.path.join(base, "output", name)
        if candidate != wanted:
            out.append((candidate, why))
    return out


def _write_product(path: str, payload: Dict[str, Any]) -> str:
    """Write a regenerated product, surviving a read-only install.

    ``output/`` under the package is the documented landing spot, but an installed
    skill tree can be read-only (verified/packaged installs), and the acceptance
    run used to die with a bare ``PermissionError`` *after* computing every number
    -- no report to show for a complete run. Each location that fails is recorded;
    the first that works wins, and the path actually used is printed. Silently
    redirecting would make ``--check-baseline`` comparisons unverifiable, and
    giving up after one attempt is what made the fix half-a-fix.
    """
    failures: List[Tuple[str, str]] = []
    for candidate, why in _product_candidates(path):
        try:
            directory = os.path.dirname(candidate) or "."
            os.makedirs(directory, exist_ok=True)
            with open(candidate, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            failures.append((candidate, "%s: %s" % (type(exc).__name__, exc.strerror)))
            continue
        if candidate != path:
            print("[output] %s is not writable (%s); wrote the product to %s instead (%s)"
                  % (path, failures[0][1] if failures else "unknown", candidate, why))
        return candidate
    raise SystemExit(
        "[output] cannot write the product anywhere. Tried:\n%s\n"
        "Re-run with --baseline-output pointing at a writable directory."
        % "\n".join("  %s  <- %s" % (c, r) for c, r in failures))


def _load_fixture(name: str) -> Dict[str, Any]:
    with open(os.path.join(FIXTURE_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


def _bars_for(rules, args) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any],
                                     Dict[str, Dict[str, str]]]:
    """Load every declared symbol's bars.

    Returns ``(bars_by_symbol, provenance, skipped)``. A symbol that could not be
    served is *kept in the report*: dropping it silently would shrink the sample
    and leave ``partial_symbols: []`` reading like an all-complete run.
    """
    symbols = sorted({(r.get("instrument") or {}).get("symbol") for r in rules
                      if (r.get("instrument") or {}).get("symbol")})
    bars_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    provenance: Dict[str, Any] = {}
    skipped: Dict[str, Dict[str, str]] = {}
    for symbol in symbols:
        csv_path = os.path.join(FIXTURE_DIR, f"bars_{symbol}.csv")
        try:
            if args.fixture:
                # A missing synthetic fixture is a skip, never a silent fall
                # through to the landed directory: mixing the two data sources
                # in one run would make the numbers meaningless.
                if not os.path.exists(csv_path):
                    raise DataUnavailable(
                        f"bundled fixture has no bars_{symbol}.csv "
                        f"({os.path.relpath(FIXTURE_DIR, ROOT)}); run this symbol with "
                        f"--landed-dir instead")
                loaded = load_bars(symbol, args.start, args.end, csv_path=csv_path)
            else:
                loaded = load_bars(symbol, args.start, args.end,
                                   fixtures_dir=args.landed_dir,
                                   coverage=args.coverage)
        except DataUnavailable as exc:
            code = getattr(exc, "code", "data_unavailable")
            detail = getattr(exc, "detail", {}) or {}
            print(f"[skip] {symbol}: {code}: {exc}", file=sys.stderr)
            for hint in _hints(code, detail, args.landed_dir):
                print(f"       {hint}", file=sys.stderr)
            skipped[symbol] = {"code": code, "message": str(exc)}
            continue
        bars_by_symbol[symbol] = loaded["bars"]
        prov = data_provenance(loaded)
        provenance[symbol] = prov
        flags = []
        if prov.get("partial"):
            flags.append("PARTIAL")
        if prov.get("coverage_shrunk"):
            flags.append("COVERAGE SHRUNK")
        print(f"[data] {symbol}: {len(loaded['bars'])} bars from {loaded['source']}"
              + (f" ({', '.join(flags)})" if flags else ""))
    return bars_by_symbol, provenance, skipped


def _hints(code: str, detail: Dict[str, Any], landed_dir: str = "") -> List[str]:
    """Turn a structured data error into the next action the operator should take.

    Every hint names the step that actually fixes it: an MCP call by the agent,
    a verbatim landing under ``tests/fixtures/raw/``, then ``--build``.
    """
    build = f"python3 scripts/mcp_landing.py --build --out-dir {landed_dir}"
    if code in ("landing_not_found", "fixture_not_found"):
        return ["nothing landed for this request:",
                "  ① agent: mcp__pandadata__call_pandadata method=get_future_daily / "
                "get_future_dominant params={...}",
                "  ② agent: verbatim payload -> tests/fixtures/raw/<method>__<label>.json",
                "  ③ " + build]
    if code == "payload_truncated":
        bad = detail.get("truncation_reasons") or detail.get("partial_payloads") or []
        return ["refusing a truncated parquet-channel preview:", "  " + "; ".join(str(b) for b in bad),
                "cut the request (shorter date range / fewer symbols / fewer fields), re-land, "
                "then --build; --allow-partial belongs to --build, not to this script"]
    if code in ("coverage_missing",):
        missing = detail.get("missing_dates") or detail.get("missing") or []
        return ["requested window is not fully covered; missing: %s" % (missing or "see message"),
                "land the gap and --build, or pass --coverage shrink to use the covered "
                "sub-range (recorded in the report)"]
    if code in ("payload_unreadable", "payload_empty", "bad_bar_row"):
        return ["the landed payload is not usable as-is: re-call the MCP method and write the "
                "response verbatim (never hand-edit rows)",
                "check it with: python3 scripts/mcp_landing.py --inspect "
                "tests/fixtures/raw/<method>__<label>.json"]
    return []


def _summarise_provenance(provenance: Dict[str, Any],
                          skipped: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Roll the per-symbol provenance up into the block the report publishes.

    Every field here is populated from data the loader actually returns: the old
    ``shard_files`` / ``request_ids`` rollups read a ``shards`` key that
    ``data_provenance()`` no longer emits, so they were permanently ``[]`` — an
    always-empty field in an audit block is worse than no field, because it reads
    like "we checked, there were none".

    ``all_complete`` counts skipped symbols too: a run that silently lost a
    declared symbol is not complete, whatever ``partial_symbols`` says.
    """
    skipped = skipped or {}
    partial = sorted(s for s, p in provenance.items() if p.get("partial"))
    shrunk = sorted(s for s, p in provenance.items() if p.get("coverage_shrunk"))
    built_files = sorted({f for p in provenance.values() for f in p.get("files", []) if f})
    payload_files = sorted({f for p in provenance.values()
                            for f in p.get("source_payloads", []) if f})
    return {"symbols": provenance, "partial_symbols": partial, "shrunk_symbols": shrunk,
            "skipped_symbols": skipped, "built_files": built_files,
            "payload_files": payload_files,
            "all_complete": not (partial or shrunk or skipped)}



def _explicit_source(parser: argparse.ArgumentParser, argv) -> bool:
    """True only when the caller actually named --landed-dir.

    ``argv`` is what argparse saw; relying on it instead of comparing against the
    default keeps an explicit ``--landed-dir <default>`` from being rejected.
    """
    del parser
    toks = list(sys.argv[1:] if argv is None else (argv or []))
    return any(t == "--landed-dir" or t.startswith("--landed-dir=") for t in toks)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixture", action="store_true",
                        help="use bundled synthetic CSV bars (offline, no fetch)")
    parser.add_argument("--landed-dir", default=DEFAULT_LANDED_DIR,
                        help="directory of bars built by scripts/mcp_landing.py "
                             "(default: %(default)s)")
    parser.add_argument("--coverage", choices=COVERAGE_POLICIES, default="error",
                        help="policy when the landed files do not span --start/--end "
                             "(default: error; shrink uses the covered sub-range and records it)")
    parser.add_argument("--start", default="20240101")
    parser.add_argument("--end", default="20241231")
    parser.add_argument("--labels", default=os.path.join(FIXTURE_DIR, "labels.json"))
    parser.add_argument("--opinions", default=os.path.join(FIXTURE_DIR, "opinions.json"))
    parser.add_argument("--baseline-output", default=os.path.join(ROOT, "output", "frozen_baseline.json"),
                        help="where this run's report is written (a regenerated "
                             "product under git-ignored output/; the shipped frozen "
                             "reference lives in baselines/ and is never written here)")
    parser.add_argument("--scope-output", default=SCOPE_PATH,
                        help="where the pre-run scope declaration is written "
                             "(product path; baselines/scope_declaration.json is the "
                             "committed reference and is only read)")
    parser.add_argument("--check-baseline", default=None, metavar="PATH",
                        help="read-only acceptance guard: after the run, compare this "
                             "run's report and scope block field by field against the "
                             "shipped frozen reference (e.g. "
                             "baselines/frozen_baseline.json). Mismatching fields are "
                             "printed with frozen -> generated values and the exit "
                             "code is 1. Never writes to the reference.")
    parser.add_argument("--commission-bps", type=float, default=3.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--min-trades", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.fixture and not _explicit_source(parser, argv):
        parser.error("choose --fixture (bundled synthetic bars) or --landed-dir <path> "
                     "(bars built by scripts/mcp_landing.py from landed MCP payloads)")
    if not args.fixture:
        args.landed_dir = os.path.abspath(os.path.expanduser(args.landed_dir))

    opinions = (_load_fixture(os.path.basename(args.opinions))
                if args.opinions.startswith(FIXTURE_DIR)
                else json.load(open(args.opinions, encoding="utf-8")))
    extracted = run(opinions, {"apply_defaults": True})
    rules = [r for d in extracted["documents"] for r in d["rules"]]

    data_mode = "fixture" if args.fixture else "landed"

    # ---- scope is declared BEFORE any bar is read or any trade is simulated
    scope = declare_scope(
        extracted,
        data_mode=data_mode,
        start=args.start,
        end=args.end,
        baseline="hold",
        cost_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
        min_trades=args.min_trades,
    )
    args.scope_output = _write_product(args.scope_output, scope)
    print(f"[scope] declared before run: {len(scope['declared_symbols'])} symbol(s) "
          f"{scope['declared_symbols']} over {args.start}..{args.end}  hash={scope['scope_hash'][:12]}")

    bars_by_symbol, provenance, skipped = _bars_for(rules, args)
    data = _summarise_provenance(provenance, skipped)
    if not args.fixture:
        landed = portable_dir(args.landed_dir)
        data["landed_dir"] = landed["landed_dir"]
        data["landed_dir_outside_skill"] = landed["landed_dir_outside_skill"]
        if landed["landed_dir_outside_skill"]:
            data["landed_dir_note"] = (
                "the build directory sat outside the skill tree, so only its name is "
                "recorded: an absolute path here is not reproducible on another "
                "machine. The authoritative provenance is source_payloads (gateway "
                "request ids) plus the per-contract windows below.")
        data["coverage_policy"] = args.coverage
    if data["partial_symbols"]:
        print("[warn] PARTIAL data (built from truncated MCP payloads) for: %s — these numbers "
              "must not back a published conclusion" % ", ".join(data["partial_symbols"]),
              file=sys.stderr)
    if data["shrunk_symbols"]:
        print("[warn] coverage shrunk to the covered sub-range for: %s"
              % ", ".join(data["shrunk_symbols"]), file=sys.stderr)
    if skipped:
        print("[warn] %d declared symbol(s) were NOT served and are missing from these "
              "numbers: %s — the sample is smaller than declared, fix the data and re-run"
              % (len(skipped), ", ".join(sorted(skipped))), file=sys.stderr)
    if not bars_by_symbol:
        print("[error] no bars available for any declared symbol; nothing to backtest. "
              "See the [skip] lines above.", file=sys.stderr)
        return 2

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
        "data_mode": data_mode,
        "data": data,
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
    if data["partial_symbols"] or data["shrunk_symbols"] or skipped:
        report["data_quality_warning"] = (
            "data is not complete for every declared symbol: see data.partial_symbols "
            "(built from truncated MCP payloads), data.shrunk_symbols (window shorter than "
            "requested) and data.skipped_symbols (served by nothing at all, so the sample is "
            "smaller than declared)")

    args.baseline_output = _write_product(args.baseline_output, report)

    # ---- read-only acceptance guard against the shipped frozen reference
    check_rc = 0
    if args.check_baseline:
        frozen_path = os.path.abspath(os.path.expanduser(args.check_baseline))
        try:
            result = compare_baseline.verify(report, frozen_path=frozen_path)
        except compare_baseline.AnchorUnavailable as exc:
            print("\n[check-baseline] error: %s" % exc, file=sys.stderr)
            return 2
        # In --json mode the guard writes through stderr, so the report payload on
        # stdout is not interleaved with verdict lines. (The pre-existing [scope] /
        # [data] prefix lines are unchanged and still make --json stdout non-pure.)
        print("\n" + "\n".join(compare_baseline.format_lines(result)),
              file=sys.stderr if args.json else sys.stdout)
        check_rc = 0 if result["ok"] else 1
        if not result["ok"]:
            print("[check-baseline] the frozen acceptance anchor does not reproduce: "
                  "the numbers above changed. Fix the run or re-freeze the baseline "
                  "deliberately (documented in CHANGELOG) - never to make this check "
                  "pass.", file=sys.stderr)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return check_rc

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
    return check_rc


if __name__ == "__main__":
    raise SystemExit(main())
