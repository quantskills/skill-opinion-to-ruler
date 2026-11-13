# Opinion to Ruler

Turn a subjective trading opinion (a comment, a daily note, a talk transcript) into **testable, backtestable trading rules**, validate the extraction against a human-labelled sample, then evaluate cost-adjusted results against a frozen baseline.

The question this skill answers is *"can this opinion become a decidable rule?"* — not *"how bullish does it sound?"*

---

## The problem

A typical opinion looks like this:

> If rebar holds above 3850, I see it testing 4100 over the next two weeks; a break below 3780 means I'm wrong.

A person understands it. A machine cannot test it. To become testable, it has to be compressed into six decidable fields:

| Field | Value from this sentence |
|---|---|
| Instrument | rebar → `RB` (dominant continuous) |
| Direction | long (inferred from the target being above price; flagged as inferred) |
| Entry trigger | `close > 3850` |
| Horizon | two weeks = 10 trading days |
| Stop loss | `close < 3780` |
| Exit rule | `close >= 4100` |

Only with all six does the sentence stop being a *view* and become a *hypothesis*.

---

## Layout

```
skill-opinion-to-ruler/
├── SKILL.md
├── README.md / README.en.md
├── LICENSE / INSTALL.md / requirements.txt / skill.json / CHANGELOG.md
├── scripts/
│   ├── build.py         ← run() / validate_input() / 4-layer extraction
│   ├── common.py        ← instrument, direction, horizon, price lexicons
│   ├── data_loader.py   ← panda_data channel and CSV fallback
│   ├── backtest.py      ← no-look-ahead simulation, paired baseline, verdict
│   ├── annotate.py      ← per-field label scoring
│   └── evaluate.py      ← end-to-end acceptance report
├── tests/
│   ├── test_ruler.py    ← 50 cases
│   └── fixtures/        ← opinions, human labels, offline bars
├── references/
│   ├── schema.md / api_guide.md / validation.md
└── agents/              ← Cursor / Hermes / OpenClaw adapters
```

---

## Quick start

```bash
python3 scripts/build.py                                 # extraction demo
python3 scripts/annotate.py tests/fixtures/labels.json   # per-field precision / recall
python3 scripts/evaluate.py --fixture                    # offline end-to-end run
python3 scripts/evaluate.py --panda --start 20240101 --end 20241231
python3 -m pytest tests/ -v
```

With real data:

```bash
export PANDA_DATA_USERNAME=<your_username>
export PANDA_DATA_PASSWORD=<your_password>
```

The acceptance report is written to `output/frozen_baseline.json` (git-ignored).

---

## Design decisions

**1. Never invent a field.** If the text states no stop loss, `stop_loss` is `null` and appears in `missing_fields`. This lets labelling penalise fabrication, and stops the backtest from crediting the author with risk control they never specified. Defaults require an explicit `apply_defaults=True`, and every filled field is recorded in `assumed` and folded into `config_hash`.

**2. Inference leaves a trace.** With price levels but no explicit long/short wording, direction can be inferred from the *profit target* side. That inference lands in `ambiguity` and sets `direction_inferred: true`. Ambiguity is surfaced, not swallowed.

**3. Unruleable content is output, not dropped.** "Commodities should do better next year" has no instrument, no condition, no horizon. It goes to `unruleable`, and `ruleable_share` is reported. **A source whose opinions mostly fail to rule-ify is itself a finding.**

**4. No look-ahead.** Only bars strictly after `published_at` are used, and fills happen at the next bar's open. A missing `published_at` aborts the simulation rather than assuming a same-day close.

**5. Paired comparison against a simple baseline.** The default baseline is buy-and-hold on the same instrument over the same dates. Each rule trade is differenced against that baseline, removing market drift:

```
>= 12 trades and bootstrap CI lower bound > 0  → positive
>= 12 trades and CI upper bound <= 0           → negative
otherwise                                      → inconclusive
```

**A negative verdict is a valid deliverable.** If a source's rules, after costs, fail to beat holding, measuring that and stating the boundary is a real result.

---

## Current status

Measured on two datasets. The divergence between them is exactly what this skill is meant to expose: **the same opinions flip sign when you move from synthetic to real bars.**

### A. Bundled fixture (offline, synthetic bars)

| Item | Result |
|---|---|
| Per-field exact match | 1.00 on all 7 fields |
| Rules produced | 15 (full 6 / partial 7 / neutral 2 / none 1) |
| Ruleable share | 0.94 |
| Trades simulated | 10 |
| Paired edge vs hold | −0.0032, CI [−0.0096, 0.0] |
| Verdict | `inconclusive` |

### B. panda_data real bars (RB / I, full-year 2024, 242 daily bars)

| Item | Result |
|---|---|
| Per-field exact match | 1.00 on all 7 fields |
| Trades simulated | 12 (meets the 12-trade threshold) |
| Mean net return | −0.0082, win rate 0.50 |
| Paired edge vs hold | +0.0122, CI [−0.0045, 0.0285] |
| Verdict | `inconclusive` |

**Reading these numbers.** The paired edge is positive on average, but the CI straddles zero and the 12 trades split evenly between wins and losses. Mean net return is negative while the edge is positive: these rules lose money, they just lose less than holding. The sample only just reaches the threshold; it is not evidence that the opinions work.

> **Correction note:** versions up to 0.2.0 reported an edge of `+0.0162, CI [0.0021, 0.0328]`. That figure was defective — the baseline used each rule's own exit date, which made **every long rule's edge exactly zero**. The baseline now holds for the rule's pre-declared horizon instead. The table above is the corrected result, and a regression test guards the failure.

The two data modes disagree (edge negative in A, positive in B), which is precisely why synthetic bars cannot count as evidence. A citable conclusion needs real, timestamped, single-source opinions with a much larger sample.

---

## Disclaimer

- Research and educational use only. Not investment advice, no trade signals, no position sizing recommendations.
- No guarantee of returns. Historical replay results do not indicate future performance.
- Daily-close mechanics only: intraday triggers, limit-locked bars, liquidity impact and margin changes are not modelled. Live execution must be independently re-validated.
- Community project under QuantSkills. Not certified or endorsed by any regulator, exchange, broker or QuantSkills.

---

## Known limitations

- Extraction is lexicon + regex, not an LLM. **Chinese and English are both supported, including mixed sentences.** It covers common futures phrasing; irony, long-range anaphora and unusual metaphor fall to `none` or raise `ambiguity`.
- English matching is word-boundary aware (`long` does not fire inside `longer`), but a sentence containing both long and short wording is still flagged as ambiguous.
- The lexicon is an explicit whitelist. New languages or new products require edits to `scripts/common.py`; the logic does not change.
- The instrument alias table is a whitelist; unknown products are not guessed.
- Cross-rule capital competition is not modelled; rules are evaluated independently.
- The 12-trade threshold is conservative. Passing it does not imply statistical power.

---

## License

GPL-3.0-only. See `LICENSE`.