# skill-opinion-to-ruler

Turn subjective trading opinions into testable, cost-adjusted trading rules.

## Overview

A stateless extraction and evaluation skill. Given timestamped opinion text, it produces one rule per actionable sentence with six decidable fields, scores the extraction against a human-labelled sample per field, and evaluates every rule against a paired buy-and-hold baseline after costs.

The deliverable's claim is **auditability**, not alpha: every assumption is recorded, every ambiguity is surfaced, and a negative result is a valid outcome.

## Architecture

```
opinion text ──► sentence split ──► extract_rule (6 fields, pure)
                                        │
                                        ├──► assess (testability + frozen defaults)
                                        │
                    ┌───────────────────┴────────────────────┐
                    ▼                                        ▼
             rules[] / unruleable[]                 labels.json
                    │                                        │
                    ▼                                        ▼
          backtest (no look-ahead, paired baseline)   annotate (per-field P/R)
                    │                                        │
                    └───────────────► evaluate.py ◄──────────┘
                                          │
              ┌───────────────────────────┴───────────────────────────┐
              ▼                                                       ▼
   output/frozen_baseline.json                        baselines/frozen_baseline.json
   regenerated product, git-ignored                    frozen acceptance anchor, shipped
              └───────────────────────┬───────────────────────────────┘
                                      ▼
                     scripts/compare_baseline.py  (read-only, field by field)
```

## Quick Start

```bash
cd skill-opinion-to-ruler

python3 scripts/build.py                                 # extraction demo
python3 scripts/annotate.py tests/fixtures/labels.json   # per-field scores
python3 scripts/evaluate.py --fixture                    # offline acceptance run
python3 scripts/compare_baseline.py                      # read-only guard vs baselines/
python3 -m pytest tests/ -v                              # 248 cases
```

The acceptance anchor ships with the skill: `baselines/frozen_baseline.json` (the frozen
reference) and `baselines/scope_declaration.json` (its scope copy) are committed, so anyone
installing from git can verify them. `evaluate.py` writes the **regenerated product** to the
git-ignored `output/`. `compare_baseline.py` re-runs the deterministic fixtures and compares
hundreds of fields against the anchor; a difference names the field (frozen -> new value) and
exits non-zero.

The real 2024H1 RB/I anchor also ships with derived daily OHLCV/dominant-map CSV, provenance and
cases/rules/labels under `evidence/rb-i-2024H1/`; raw MCP responses remain uncommitted. The opinion
texts are explicitly synthetic fixtures, while the market bars are real. Run
`python3.11 -m pytest tests/test_baseline_guard.py -k shipped_evidence -q` for the unconditional
1526-field replay, which preserves `inconclusive`. A second raw-payload guard runs when those local
files are available and byte-checks the derived evidence.

Live data: the script never goes online, and it could not if it tried — MCP tools are
callable only by an **agent**. The operator instruction is a fixed four-step chain:

```
① agent calls mcp__pandadata__call_pandadata(method=get_future_daily / get_future_dominant, params=...)
② agent writes the returned payload verbatim to tests/fixtures/raw/<method>__<label>.json
③ python3 scripts/mcp_landing.py --build      # truncation guard; writes this skill's own CSV
④ python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231
```

Steps ③ and ④ read local files only. No credentials, no network egress, no other skill
involved. If the MCP session is not logged in, the user signs in via
Settings -> PandaData -> Login. See `references/mcp-data.md`.

## Agent Integration

```python
import sys
sys.path.insert(0, "skill-opinion-to-ruler/scripts")
from build import run
from backtest import evaluate, value_assessment

extracted = run(
    {"documents": [
        {"id": "op-001", "published_at": "2024-01-05T08:30:00+08:00",
         "text": "螺纹钢主力站稳3850，未来两周上冲4100，跌破3780止损。"}
    ]},
    {"apply_defaults": True},
)
rules = [r for d in extracted["documents"] for r in d["rules"]]

backtest = evaluate(rules, {"RB": bars}, baseline="hold")
print(backtest["verdict"], backtest["edge"])
print(value_assessment(backtest))
```

### Output shape

`schema_version`, `documents[]` (each with `rules[]`, `unruleable[]`, `counts`), `summary`, `config`, `config_hash`. Full contract in `references/schema.md`.

### Testability

| Class | Meaning |
|---|---|
| `full` | text states horizon and at least one risk exit |
| `partial` | tradable after the frozen policy fills a gap |
| `neutral` | explicit stand-aside |
| `none` | no instrument or no direction; reported, not dropped |

### Data Source

No script fetches data, and none can reach the network. `--fixture` reads the bundled
synthetic CSV bars; `--landed-dir <path>` reads bars that `scripts/mcp_landing.py --build`
converted from agent-landed `get_future_daily` / `get_future_dominant` payloads. A missing
landing directory, a payload that is not a verbatim response, an empty payload, a truncated
parquet preview, an unusable bar row, a missing local file or an uncovered window raises a
structured `DataUnavailable` subclass (`landing_not_found` / `payload_unreadable` /
`payload_empty` / `payload_truncated` / `bad_bar_row` / `fixture_not_found` /
`coverage_missing`) — no silent fallback, no guessing. Exit codes: 0 ok, 2 usage error,
3 data unavailable.

### Tests

```bash
python3 -m pytest tests/ -v   # 248 cases (113 ruler + 39 landing + 18 doc guards + 58 baseline-anchor guards + 3 preflight guards + 17 contest-verification guards)
```

### Dependencies

- Python 3.8+
- Standard library only
- No optional packages: the legacy fetch channel was removed in 0.4.0, and data arrives through
  agent-landed MCP payloads (nothing this skill fetches itself)

## Boundaries

Research and educational use only. Not investment advice. Daily-close simulation: intraday triggers, limit-locked fills, liquidity impact and margin changes are not modelled. Cross-rule capital competition is not modelled. Live execution must be independently re-validated.