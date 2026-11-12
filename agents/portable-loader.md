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
                                          ▼
                              output/frozen_baseline.json
```

## Quick Start

```bash
cd skill-opinion-to-ruler

python3 scripts/build.py                                 # extraction demo
python3 scripts/annotate.py tests/fixtures/labels.json   # per-field scores
python3 scripts/evaluate.py --fixture                    # offline acceptance run
python3 -m pytest tests/ -v                              # 50 cases
```

Live data:

```bash
export PANDA_DATA_USERNAME=<your_username>
export PANDA_DATA_PASSWORD=<your_password>
python3 scripts/evaluate.py --panda --start 20240101 --end 20241231
```

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

No data fetched by default. `--fixture` reads local CSV bars; `--panda` uses `panda_data` (`get_future_dominant` / `get_future_daily`). Credential failure raises `DataUnavailable`; there is no silent fallback.

### Tests

```bash
python3 -m pytest tests/ -v   # 50 cases
```

### Dependencies

- Python 3.8+
- Standard library only
- Optional: `panda-data==1.0.6`

## Boundaries

Research and educational use only. Not investment advice. Daily-close simulation: intraday triggers, limit-locked fills, liquidity impact and margin changes are not modelled. Cross-rule capital competition is not modelled. Live execution must be independently re-validated.