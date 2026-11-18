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
│   ├── data_loader.py   ← reads local bars only: built files or a caller CSV
│   ├── mcp_landing.py   ← landing builder (payload parsing / truncation guard / provenance)
│   ├── backtest.py      ← no-look-ahead simulation, paired baseline, verdict
│   ├── annotate.py      ← per-field label scoring
│   ├── evaluate.py      ← end-to-end acceptance report
│   ├── scope.py           ← freezes the equivalence scope before the run (never chosen after results)
│   ├── contest_verify.py  ← reconciles execution-cost assumptions against the simulation contest (reads landed payloads, never trades)
│   └── compare_baseline.py ← read-only guard: re-run vs the frozen anchor, field by field
├── baselines/           ← frozen reference (the acceptance anchor; committed, shipped)
│   ├── frozen_baseline.json
│   └── scope_declaration.json
├── output/              ← landing spot for regenerated products (runtime, not committed)
├── tests/
│   ├── test_ruler.py          ← 113 cases (extraction / backtest / scope)
│   ├── test_mcp_landing.py    ← 39 cases (payload parsing, the truncation guard, provenance and stitching attribution)
│   ├── test_docs.py           ← 18 cases (documented numbers = real runs)
│   ├── test_baseline_guard.py ← 53 cases (re-run compared field by field vs baselines/, negative paths, packaging guards)
│   ├── test_preflight.py      ← 3 cases (the pre-flight contract: MCP session, permission probe, model owned by the host, stop-and-report)
│   ├── test_contest_verify.py ← 17 cases (simulation-contest cost reconciliation: missing evidence must not yield a verdict, a locked book is not a verified cost, the delivery date is never substituted, identity fields never leak)

│   └── fixtures/
│       ├── bars_*.csv      ← bundled synthetic bars (used by --fixture)
│       ├── raw/            ← verbatim MCP payloads landed by the agent (not committed)
│       └── landed/         ← output of --build (not committed)
├── references/
│   ├── schema.md / api_guide.md / mcp-data.md / validation.md
└── agents/              ← Cursor / Hermes / OpenClaw adapters
```

---

## Quick start

```bash
python3 scripts/build.py                                 # extraction demo
python3 scripts/annotate.py tests/fixtures/labels.json   # per-field precision / recall
python3 scripts/evaluate.py --fixture                    # offline end-to-end run
python3 scripts/mcp_landing.py --build                   # landed payloads -> this skill's own CSV
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231
# execution-cost reconciliation: the agent lands simulation-contest payloads first, then this
# reads them (see references/contest_verification.md)
python3 scripts/contest_verify.py --out baselines/contest_verify_$(date +%Y%m%d).json
python3 scripts/compare_baseline.py                      # read-only: re-run vs baselines/ anchor
python3 -m pytest tests/ -v                              # 243 cases (113 + 39 + 18 + 53 + 3 + 17, see the tests/ tree below)
```

Real bars never go through the script: MCP tools can only be called by an **agent**. The
agent calls `mcp__pandadata__call_pandadata(method=get_future_daily / get_future_dominant,
params=...)`, writes each returned payload **verbatim** to
`tests/fixtures/raw/<method>__<label>.json`, and only then
`python3 scripts/mcp_landing.py --build` converts them into
`tests/fixtures/landed/bars_<SYMBOL>.csv`. `evaluate.py --landed-dir` reads those files
(see `references/mcp-data.md`). No credentials, no network egress.

The acceptance anchor ships with the skill: `baselines/frozen_baseline.json` is the frozen
reference and `baselines/scope_declaration.json` its scope copy — both committed, so a git
install can actually verify them. `evaluate.py` writes the **regenerated products** to
`output/` (still git-ignored: a landing spot, never a second authority). Check the anchor
with `python3 scripts/compare_baseline.py`, or inside a run with
`python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json`;
a mismatch names the field that moved (frozen value -> new value) and exits non-zero.

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

### A. Bundled fixture (offline, synthetic bars)

Every number below is the **actual output** of `python3 scripts/evaluate.py --fixture`;
`tests/test_docs.py` asserts the table against a live run, so the docs cannot drift away
from the code unnoticed. The same numbers are frozen in the shipped
`baselines/frozen_baseline.json` and re-checked field by field against a fresh run by
`tests/test_baseline_guard.py`.

| Item | Result |
|---|---|
| Labelled samples / per-field exact match | 26 samples (27 judgements) / 1.00 |
| Rules produced | 15 (full 6 / partial 7 / neutral 2 / none 1) |
| Ruleable share | 0.9375 |
| Trades simulated | 10 (5 skipped) |
| Mean net return / win rate | +0.0195 / 0.80 |
| Sharpe (per trade / annualised) | 0.759 / 5.411 |
| Paired edge vs hold | **−0.018527, CI [−0.028301, −0.008560], n=10** |
| Verdict | `inconclusive` |

Read that precisely: **both ends of the CI are negative**, so on these synthetic bars the
rules consistently lose to holding. The verdict is `inconclusive` because n=10 is below the
frozen 12-trade threshold — **not** because the CI straddles zero. Synthetic bars exist to
exercise the pipeline; they are not market evidence.

### B. Real bars (fetched via PandaData MCP, landed inside this skill)

Numbers from real bars landed from licensed MCP payloads (the payloads themselves are not
shipped), frozen in `baselines/rb-i-2024H1-real.json`. The chain is unchanged: **the agent
fetches, the payload is written verbatim, the scripts read local files only** — the scripts never
go online.

| Item | Result |
|---|---|
| Window / products | 2024-01-02 – 2024-06-28 / RB, I |
| Volume | 117 stitched daily bars per product; 234 dominant-map rows + 320 contract-day rows |
| Dominant rolls | 1 per product (`roll_count`); the basis gap at the roll is **preserved** |
| Trades simulated | 12 (3 skipped) |
| Mean net / win rate / max drawdown | −0.008188 / 0.50 / −0.1453 |
| Sharpe (per trade / annualised) | −0.235 / −1.612 |
| Paired edge vs hold | **+0.012154, CI [−0.004511, +0.028479], n=12** |
| Verdict | `inconclusive` |

That table is not copied prose:
`tests/test_baseline_guard.py::test_real_anchor_reproduces_from_the_raw_payloads` re-lands from the
payloads, re-evaluates and compares this anchor field by field; it skips rather than passes when
the licensed payloads are absent.

The re-run corrected two things too. n=12 clears the frozen trade threshold but the **CI straddles
zero**, so the verdict stays `inconclusive` — meeting a gate is not evidence of an effect. And the
synthetic anchor yields **−0.0185** for the same rules, the **opposite sign** to real data, which is
precisely why synthetic evidence is not allowed to cap the value score.

To reproduce (steps 1–2 are performed by the agent; the scripts never go online):

1. `mcp__pandadata__auth_status` — if not logged in: Settings → PandaData → Login.
2. Call `get_future_dominant` / `get_future_daily` (RB, I, **20240102–20240628** — the window the
   shipped anchor actually used; a different window is a different measurement and cannot be
   compared against this table) following the slicing table in `references/mcp-data.md`, and
   write each returned payload **verbatim** to `tests/fixtures/raw/<method>__<label>.json`.
3. `python3 scripts/mcp_landing.py --build` — the truncation guard lives here: a payload with
   `truncated: true` or `row_count < total_rows` is refused with a non-zero exit. Then
   `--verify` to re-check what landed and what was built.
4. `python3 scripts/evaluate.py --landed-dir <writable>/real_landed --start 20240102 --end 20240628`
   — the directory must be named `real_landed`; that is the name recorded in the report.
5. If the product location is not writable (an installed skill directory is read-only),
   `evaluate.py` walks `requested path -> ./output -> <skill>/output -> system temp/output`,
   **prints the path it actually wrote**, and does not crash after computing every number because
   it cannot write into the package. A read-only install usually has a read-only working
   directory too, so a single fallback location is not a fallback.

`provenance.json` records which payload each file came from and the requested window; the report
stores only **names** for `landed_dir` and `files`, never this machine's absolute paths — otherwise
a shipped anchor would carry the fetching machine's directory layout.

One caveat that survives the rewrite: even with a full year of bars, trades only land in the
one or two months the opinion texts cover (Jan–Feb 2024 for these fixtures), so this is
**not** a multi-regime test.

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