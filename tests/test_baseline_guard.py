"""The frozen acceptance anchor is a shipped deliverable, and it is guarded.

Why these tests exist
---------------------
``skill.json`` used to declare ``output/frozen_baseline.json`` as the acceptance
report while ``.gitignore`` excluded ``output/``. Anyone installing this skill
from git therefore received **no** acceptance anchor at all, and the task
specification's "冻结基线对照" deliverable was unverifiable from a clean checkout.
Version 0.6.0 moved the reference to ``baselines/`` (committed) and left
``output/`` as the git-ignored landing spot for regenerated products.

Every test here judges numbers, not existence:

* the deterministic fixture run is re-executed and compared to
  ``baselines/frozen_baseline.json`` field by field (hundreds of leaf fields; the
  only waived one is the run timestamp, and that waiver is itself pinned);
* the required coverage list is checked against the field paths the comparator
  actually judged, so narrowing the walk breaks a test instead of hiding;
* the negative path is exercised: a copy with **one digit** changed must produce a
  structured diff naming that field, and a non-zero exit — in-process, through
  ``scripts/compare_baseline.py``, and through ``evaluate.py --check-baseline``;
* the ignore rules are evaluated (and cross-checked against real
  ``git check-ignore`` when git is installed) to prove the anchor ships while the
  runtime products do not.

Nothing here reaches the network, and nothing here writes to ``baselines/``.
"""

from __future__ import annotations

import contextlib
import copy
import fnmatch
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import compare_baseline  # noqa: E402

BASELINE_DIR = os.path.join(ROOT, "baselines")
EVIDENCE_DIR = os.path.join(ROOT, "evidence", "rb-i-2024H1")
EVIDENCE_LANDED_FILES = (
    "bars_I2405.DCE.csv", "bars_I2409.DCE.csv",
    "bars_RB2405.SHF.csv", "bars_RB2410.SHF.csv",
    "dominant_I.csv", "dominant_RB.csv", "provenance.json",
)
EVIDENCE_CASES = os.path.join(EVIDENCE_DIR, "cases_rules_labels.json")
FROZEN_REPORT = os.path.join(BASELINE_DIR, "frozen_baseline.json")
FROZEN_SCOPE = os.path.join(BASELINE_DIR, "scope_declaration.json")
GITIGNORE = os.path.join(ROOT, ".gitignore")
PYTHON = sys.executable

ACCURACY_METRICS = ("tp", "fp", "fn", "tn", "precision", "recall", "exact_match_rate")

# Field paths the acceptance story depends on, written the way the comparator
# names them. ``test_comparison_covers_every_named_acceptance_field`` fails if the
# walk ever stops judging one of them.
REQUIRED_EXACT_FIELDS = (
    # extraction summary
    "extraction.summary.documents", "extraction.summary.rules_total",
    "extraction.summary.rules_full", "extraction.summary.rules_partial",
    "extraction.summary.rules_neutral", "extraction.summary.unruleable",
    "extraction.summary.ruleable_share", "extraction.config_hash",
    # backtest: paired edge, CI, n, costs, verdict
    "backtest.edge.mean", "backtest.edge.ci_low", "backtest.edge.ci_high",
    "backtest.edge.n", "backtest.baseline", "backtest.cost_bps",
    "backtest.slippage_bps", "backtest.min_trades", "backtest.verdict",
    "backtest.metrics.trades", "backtest.metrics.skipped",
    "backtest.metrics.win_rate", "backtest.metrics.mean_net_return",
    # cost model and the frozen verdict threshold
    "scope_declaration.baseline", "scope_declaration.cost_model.commission_bps",
    "scope_declaration.cost_model.slippage_bps", "scope_declaration.cost_model.sides",
    "scope_declaration.min_trades_for_verdict", "scope_declaration.scope_hash",
    # replay equivalence: the honesty block about what this engine is *not*
    "scope_declaration.replay_equivalence.what_this_is",
    "scope_declaration.replay_equivalence.why_equivalent",
    # value + applicability
    "applicability.declared_before_run", "applicability.scope_honoured",
    "applicability.scope_hash", "applicability.coverage.ruleable_share",
    "value_assessment.decisions_created", "value_assessment.verdict",
    "value_assessment.effect_size.mean_paired_edge",
    "value_assessment.effect_size.ci_low", "value_assessment.effect_size.ci_high",
    "value_assessment.effect_size.n_trades",
    # the data the numbers came from
    "data_mode", "data.symbols.RB.bars", "data.symbols.I.bars", "data.all_complete",
    "scope_verification.honoured",
)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _bytes_of(path):
    with open(path, "rb") as fh:
        return fh.read()


def _silenced(func, *args, **kwargs):
    """Run a pipeline step without its operator chatter polluting pytest output."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        return func(*args, **kwargs)


def _leaf_paths(node, prefix=""):
    """Every leaf field path of a JSON subtree, in the comparator's own syntax."""
    out = []
    if isinstance(node, dict):
        for key, value in node.items():
            out.extend(_leaf_paths(value, "%s.%s" % (prefix, key) if prefix else key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.extend(_leaf_paths(value, "%s[%d]" % (prefix, index)))
    else:
        out.append(prefix)
    return out


def _all_diffs(result):
    return [d for section in result["sections"] for d in section["diffs"]]


def _compared_fields(result, index=0):
    return set(result["sections"][index]["fields"])


def _set_path(document, path, value):
    """Set a dotted/indexed path. Raises if the path does not already exist."""
    tokens = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    keys = [int(t[1:-1]) if t.startswith("[") else t for t in tokens]
    if not keys:
        raise ValueError("empty path: %r" % path)
    node = document
    for key in keys[:-1]:
        node = node[key]
    leaf = keys[-1]
    existing = node[leaf]
    node[leaf] = value
    assert existing != value, "test bug: %s already held %r" % (path, value)
    return existing


@pytest.fixture(scope="module")
def anchor():
    return _read_json(FROZEN_REPORT)


@pytest.fixture(scope="module")
def regenerated():
    """A fresh fixture run produced by this session, not read back from disk."""
    return _silenced(compare_baseline.regenerate)


@pytest.fixture(scope="module")
def fresh_comparison(regenerated):
    return compare_baseline.verify(regenerated, include_fields=True)


# ---------------------------------------------------------------------------
# 1. The guard: the run must reproduce the shipped anchor, field by field
# ---------------------------------------------------------------------------
def test_the_fixture_run_reproduces_the_frozen_anchor(regenerated, fresh_comparison):
    """Re-run the pipeline from the deterministic fixtures and compare everything.

    This is the check that was missing: not "does a file exist", but "does this
    code still produce the numbers the acceptance documents claim".
    """
    assert regenerated["data_mode"] == "fixture"
    assert fresh_comparison["diff_count"] == 0, (
        "the fixture run no longer reproduces baselines/frozen_baseline.json; "
        "offending fields: %s" % [(d["field"], d["frozen"], d["generated"])
                                  for d in _all_diffs(fresh_comparison)][:20])
    # Pinned to the measured walk (report 1357 + scope declaration 78), not a loose
    # floor: README and CHANGELOG quote these figures, and "> 800" cannot keep a
    # quoted number honest -- it stayed true while the docs said something else.
    assert fresh_comparison["compared"] == 1435, (
        "the compared-field count moved (%d != 1435): the field walk was narrowed, "
        "or the anchor grew -- either way the numbers quoted in README and "
        "validation.md must be re-synced in the same commit"
        % fresh_comparison["compared"])
    assert len(fresh_comparison["sections"]) == 2, (
        "both shipped references must be judged in one run")


def test_the_shipped_anchor_still_holds_the_known_acceptance_numbers(anchor):
    """The reference itself is pinned to the numbers the docs quote.

    Without this, replacing baselines/frozen_baseline.json with a doctored one
    would keep every other test in this file green.
    """
    assert anchor["extraction"]["summary"] == {
        "documents": 16, "rules_total": 15, "rules_full": 6, "rules_partial": 7,
        "rules_neutral": 2, "unruleable": 1, "ruleable_share": 0.9375}
    symbol = anchor["extraction"]["accuracy"]["fields"]["instrument_symbol"]
    assert (symbol["tp"], symbol["fp"], symbol["fn"], symbol["tn"]) == (24, 0, 0, 3)
    assert symbol["precision"] == 1.0 and symbol["recall"] == 1.0
    assert symbol["exact_match_rate"] == 1.0
    # 26 个样本、27 条判定（一句两标的额外贡献一条），且满分必须连置信下界一起看
    acc = anchor["extraction"]["accuracy"]
    assert acc["samples"] == 26 and symbol["judgements"] == 27, acc["samples"]
    assert symbol["exact_match_ci95_low"] == pytest.approx(0.8723, abs=1e-4), symbol
    # CHANGELOG quotes 0.8677 for the all-fields-clean bound on 26 samples; pinning
    # it here means the quoted number cannot rot into folklore.
    assert acc["samples_all_fields_correct_ci95_low"] == pytest.approx(0.8677, abs=1e-4)
    assert acc["sufficient_sample_size"] is False, "26 < 40 must keep the warning armed"
    assert "40" in acc["sample_size_note"], acc["sample_size_note"]
    assert acc["samples_all_fields_correct"] == 26
    # entry 的三处策略补全必须算 policy_default，不能算读对
    entry = acc["fields"]["entry_expr"]
    assert entry["policy_default"] == 3 and entry["fp"] == 0, entry
    assert acc["rule_count_mismatches"] == 0
    assert anchor["data"]["symbols"]["RB"]["bars"] == 260
    assert anchor["data"]["symbols"]["I"]["bars"] == 260
    edge = anchor["backtest"]["edge"]
    assert edge["mean"] == pytest.approx(-0.018527, abs=compare_baseline.FLOAT_TOL)
    assert edge["ci_low"] == pytest.approx(-0.028301, abs=compare_baseline.FLOAT_TOL)
    assert edge["ci_high"] == pytest.approx(-0.008560, abs=compare_baseline.FLOAT_TOL)
    assert edge["n"] == 10
    # The verdict is inconclusive because n is under the frozen 12-trade threshold,
    # *not* because the CI straddles zero: both ends here are negative.
    assert edge["ci_high"] < 0 and edge["ci_low"] < 0
    assert anchor["backtest"]["verdict"] == "inconclusive"
    assert anchor["scope_declaration"]["min_trades_for_verdict"] == 12
    assert anchor["scope_declaration"]["cost_model"] == {
        "commission_bps": 3.0, "slippage_bps": 2.0, "sides": 2}
    assert anchor["backtest"]["cost_bps"] == 3.0 and anchor["backtest"]["slippage_bps"] == 2.0
    # the replay-equivalence block must keep saying what this engine is not
    replay = anchor["scope_declaration"]["replay_equivalence"]
    assert "not" in replay["what_this_is"].lower() or replay["what_this_is_not"]
    assert any("matching engine" in item or "模拟赛" in item
               for item in replay["what_this_is_not"]), replay["what_this_is_not"]
    assert replay["where_it_breaks"], "the failure boundary must not be empty"


def test_both_shipped_references_describe_the_same_scope(anchor):
    """baselines/scope_declaration.json must not drift from the anchor's own block."""
    assert _read_json(FROZEN_SCOPE) == anchor["scope_declaration"]


# ---------------------------------------------------------------------------
# 2. Coverage: the fields the specification names must actually be judged
# ---------------------------------------------------------------------------
def test_comparison_covers_every_named_acceptance_field(fresh_comparison):
    missing = [field for field in REQUIRED_EXACT_FIELDS
               if field not in _compared_fields(fresh_comparison)]
    assert missing == [], "the anchor guard stopped comparing: %s" % missing


def test_comparison_covers_every_accuracy_metric_of_every_labelled_field(anchor,
                                                                        fresh_comparison):
    """tp/fp/fn/tn + precision/recall/exact_match for all seven fields.

    Expected paths are derived from the anchor rather than typed out, so dropping
    a field from the report *or* from the walk is caught.
    """
    compared = _compared_fields(fresh_comparison)
    names = sorted(anchor["extraction"]["accuracy"]["fields"])
    assert len(names) == 7, names
    expected = {"extraction.accuracy.fields.%s.%s" % (name, metric)
                for name in names for metric in ACCURACY_METRICS}
    assert expected <= compared, "not compared: %s" % sorted(expected - compared)


def test_comparison_covers_the_scope_value_and_applicability_blocks(anchor,
                                                                   fresh_comparison):
    compared = _compared_fields(fresh_comparison)
    for block in ("scope_declaration", "value_assessment", "applicability",
                  "backtest", "extraction", "data", "scope_verification"):
        uncovered = [leaf for leaf in _leaf_paths(anchor[block], block)
                     if leaf not in compared]
        assert uncovered == [], "%s leaves not compared: %s" % (block, uncovered)
    # the free-text boundaries are part of the acceptance story, so they are judged
    # item by item instead of being skipped as "just prose"
    for prefix in ("scope_declaration.replay_equivalence.what_this_is_not[",
                   "scope_declaration.replay_equivalence.where_it_breaks[",
                   "applicability.replay_equivalence.where_it_breaks[",
                   "applicability.fails_when[", "applicability.out_of_scope[",
                   "applicability.in_scope[", "backtest.trades[",
                   "extraction.accuracy.per_sample["):
        assert any(field.startswith(prefix) for field in compared), (
            "no field under %s was compared" % prefix)


def test_generated_at_is_the_only_field_the_guard_waives(anchor, fresh_comparison):
    """The waiver list must stay tiny, and the waived field must really be a stamp."""
    assert compare_baseline.VOLATILE_FIELDS == ("generated_at",)
    compared = _compared_fields(fresh_comparison)
    assert "generated_at" not in compared
    assert "generated_at" in anchor
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", str(anchor["generated_at"])), (
        "baselines/frozen_baseline.json no longer records a UTC freeze timestamp")
    other = {key for key in anchor if key != "generated_at"}
    unjudged = [key for key in other
                if not any(field == key or field.startswith(key + ".")
                           or field.startswith(key + "[") for field in compared)]
    assert unjudged == [], "a whole top-level acceptance block is not compared: %s" % unjudged


def test_float_tolerance_is_half_a_published_digit_and_no_looser():
    """5e-7 is half a unit of the 6-dp rounding the report publishes.

    Representation noise below it is admitted; a change that moves a published
    digit is reported. Pinning the boundary keeps a red guard from being silenced
    by widening this constant.
    """
    assert compare_baseline.FLOAT_TOL == 5e-7
    reference = {"mean": -0.018527, "n": 10}
    noise = {"mean": -0.018527 + 4e-7, "n": 10}
    diffs, compared = compare_baseline.compare(noise, reference)
    assert diffs == [] and compared == ["mean", "n"], (diffs, compared)
    moved = {"mean": -0.018526, "n": 10}          # one digit of the 6-dp publish
    diffs, _ = compare_baseline.compare(moved, reference)
    assert [d["field"] for d in diffs] == ["mean"], diffs
    # a float where the reference says integer is tolerated only because JSON
    # numbers compare equal; a *boolean* is never forgiven for a number
    diffs, _ = compare_baseline.compare({"mean": -0.018527, "n": 10.0}, reference)
    assert diffs == [], diffs
    diffs, _ = compare_baseline.compare({"mean": -0.018527, "n": True}, reference)
    assert [d["kind"] for d in diffs] == ["changed"], diffs
    assert [d["field"] for d in diffs] == ["n"], diffs


# ---------------------------------------------------------------------------
# 3. Negative path: one changed digit must fail, loudly, and name the field
# ---------------------------------------------------------------------------
def test_a_single_digit_change_is_reported_with_frozen_and_new_values(anchor):
    """Flip the last digit of the paired edge: the guard must name that field."""
    generated = copy.deepcopy(anchor)
    _set_path(generated, "backtest.edge.mean", -0.018528)
    result = compare_baseline.verify(generated)
    assert result["ok"] is False and result["diff_count"] >= 1
    offending = [d for d in _all_diffs(result) if d["field"] == "backtest.edge.mean"]
    assert len(offending) == 1, offending
    assert offending[0]["kind"] == "changed"
    assert offending[0]["frozen"] == -0.018527      # old value: the anchor
    assert offending[0]["generated"] == -0.018528   # new value: this run
    lines = "\n".join(compare_baseline.format_lines(result))
    assert "MISMATCH" in lines
    assert "backtest.edge.mean" in lines
    assert "-0.018527" in lines and "-0.018528" in lines


@pytest.mark.parametrize("path,value", [
    ("extraction.accuracy.fields.instrument_symbol.tp", 14),
    ("extraction.accuracy.fields.stop_expr.tn", 7),
    ("extraction.summary.ruleable_share", 0.94),
    ("extraction.summary.documents", 17),
    ("backtest.edge.ci_high", -0.00855),
    ("backtest.edge.n", 11),
    ("backtest.metrics.sharpe", 5.412),
    ("scope_declaration.cost_model.commission_bps", 3.5),
    ("scope_declaration.min_trades_for_verdict", 13),
    ("scope_declaration.replay_equivalence.what_this_is", "a tick-level matching engine"),
    ("applicability.scope_honoured", False),
    ("applicability.coverage.unruleable", 0),
    ("data.symbols.RB.bars", 259),
    ("data.all_complete", False),
    ("value_assessment.effect_size.mean_paired_edge", 0.018527),
])
def test_no_class_of_acceptance_number_is_compared_loosely(anchor, path, value):
    """Ints, floats, bools and boundary text in every block must be judged."""
    generated = copy.deepcopy(anchor)
    _set_path(generated, path, value)
    result = compare_baseline.verify(generated, scope_path=None)
    fields = {d["field"]: d for d in _all_diffs(result)}
    assert path in fields, "changing %s to %r left the guard silent" % (path, value)
    assert fields[path]["frozen"] != value
    assert fields[path]["generated"] == value


def test_structural_changes_are_reported_and_not_absorbed(anchor):
    """A boundary list that loses an item, a new field, a dropped field: all fail."""
    generated = copy.deepcopy(anchor)
    dropped = generated["applicability"]["fails_when"].pop()
    result = compare_baseline.verify(generated, scope_path=None)
    assert any(d["field"] == "applicability.fails_when" and d["kind"] == "length"
               for d in _all_diffs(result)), _all_diffs(result)
    assert dropped, "the fixture anchor has an empty fails_when to begin with"

    generated = copy.deepcopy(anchor)
    generated["brand_new_metric"] = 1.0
    result = compare_baseline.verify(generated, scope_path=None)
    assert any(d["field"] == "brand_new_metric" and d["kind"] == "extra_in_generated"
               for d in _all_diffs(result)), _all_diffs(result)

    generated = copy.deepcopy(anchor)
    del generated["value_assessment"]["effect_size"]["ci_low"]
    result = compare_baseline.verify(generated, scope_path=None)
    assert any(d["field"] == "value_assessment.effect_size.ci_low"
               and d["kind"] == "missing_in_generated"
               for d in _all_diffs(result)), _all_diffs(result)

    # swapping two boundary statements must not read as "same set, fine"
    generated = copy.deepcopy(anchor)
    items = generated["applicability"]["out_of_scope"]
    items[0], items[1] = items[1], items[0]
    result = compare_baseline.verify(generated, scope_path=None)
    assert result["diff_count"] >= 2, _all_diffs(result)


def test_cli_exits_non_zero_and_names_the_changed_field(anchor):
    """compare_baseline.py --report <doctored copy> must fail and cite the field."""
    work = tempfile.mkdtemp(prefix="guard-negative-")
    try:
        doctored = os.path.join(work, "report.json")
        changed = copy.deepcopy(anchor)
        _set_path(changed, "backtest.edge.ci_low", -0.028300)
        with open(doctored, "w", encoding="utf-8") as fh:
            json.dump(changed, fh, ensure_ascii=False)
        proc = subprocess.run(
            [PYTHON, "-B", os.path.join("scripts", "compare_baseline.py"),
             "--report", doctored, "--scope", ""],
            cwd=ROOT, capture_output=True, text=True)
        assert proc.returncode == compare_baseline.EXIT_MISMATCH == 1, (
            proc.stdout + proc.stderr)
        assert "MISMATCH" in proc.stderr
        assert "backtest.edge.ci_low" in proc.stderr
        assert "frozen=-0.028301" in proc.stderr, proc.stderr
        assert "generated=-0.0283" in proc.stderr, proc.stderr
        assert proc.stdout.strip() == "", (
            "a failed guard must not print a clean-looking summary on stdout: %r"
            % proc.stdout)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_cli_exits_zero_when_the_run_matches_the_shipped_anchor():
    """Same command against an honest run: exit 0 and a CONSISTENT verdict."""
    proc = subprocess.run(
        [PYTHON, "-B", os.path.join("scripts", "compare_baseline.py")],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "verdict: CONSISTENT" in proc.stdout
    assert "MISMATCH" not in proc.stderr
    assert "baselines/frozen_baseline.json" in proc.stdout
    assert "field(s) compared" in proc.stdout


def test_cli_exits_two_when_the_anchor_is_missing():
    """A package without its anchor is a packaging error, never a pass."""
    proc = subprocess.run(
        [PYTHON, "-B", os.path.join("scripts", "compare_baseline.py"),
         "--frozen", os.path.join(tempfile.gettempdir(), "no_such_anchor_zz.json")],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == compare_baseline.EXIT_USAGE == 2, proc.stdout + proc.stderr
    assert "frozen reference not found" in proc.stderr, proc.stderr
    assert "baselines" in proc.stderr, proc.stderr


# ---------------------------------------------------------------------------
# 4. evaluate.py --check-baseline behaves the same way, and is read-only
# ---------------------------------------------------------------------------
def _evaluate(argv):
    import evaluate
    return _silenced(evaluate.main, argv)


def test_evaluate_check_baseline_flag_fails_on_a_perturbed_anchor(anchor):
    work = tempfile.mkdtemp(prefix="guard-eval-")
    try:
        doctored = os.path.join(work, "anchor.json")
        changed = copy.deepcopy(anchor)
        _set_path(changed, "extraction.summary.rules_total", 14)
        with open(doctored, "w", encoding="utf-8") as fh:
            json.dump(changed, fh, ensure_ascii=False)
        before = _bytes_of(FROZEN_REPORT) + _bytes_of(FROZEN_SCOPE)
        rc = _evaluate(["--fixture",
                        "--baseline-output", os.path.join(work, "report.json"),
                        "--scope-output", os.path.join(work, "scope.json"),
                        "--check-baseline", doctored])
        assert rc == 1, "a changed anchor number must make the acceptance run fail"
        assert _bytes_of(FROZEN_REPORT) + _bytes_of(FROZEN_SCOPE) == before, (
            "--check-baseline touched the shipped reference; it must be read-only")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_evaluate_check_baseline_flag_passes_on_the_shipped_anchor():
    work = tempfile.mkdtemp(prefix="guard-eval-")
    try:
        rc = _evaluate(["--fixture",
                        "--baseline-output", os.path.join(work, "report.json"),
                        "--scope-output", os.path.join(work, "scope.json"),
                        "--check-baseline", FROZEN_REPORT])
        assert rc == 0
        report = _read_json(os.path.join(work, "report.json"))
        assert report["extraction"]["summary"]["rules_total"] == 15
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_evaluate_writes_products_to_output_and_never_into_baselines():
    """Roles are encoded in the defaults: reference in baselines/, product in output/."""
    help_text = subprocess.run([PYTHON, "-B", os.path.join("scripts", "evaluate.py"),
                                "--help"], cwd=ROOT, capture_output=True,
                               text=True).stdout
    for flag in ("--check-baseline", "--baseline-output", "--scope-output"):
        assert flag in help_text, "evaluate.py no longer advertises %s" % flag
    for flag in ("--baseline-output", "--scope-output"):
        default = _default_for(flag)
        assert default is not None, "could not resolve the default of %s" % flag
        assert default.startswith("output"), (
            "%s writes to %r; a normal run must land in the git-ignored product "
            "directory, never in baselines/" % (flag, default))
    import evaluate
    assert os.path.relpath(evaluate.SCOPE_PATH, ROOT).startswith("output")
    # no script in the data path opens anything inside baselines/ for writing
    write_open = re.compile(r"open\([^)]*\)\s*$|\.write_text\(|json\.dump\(")
    for script in ("evaluate.py", "compare_baseline.py", "scope.py", "data_loader.py",
                   "backtest.py", "build.py", "annotate.py", "mcp_landing.py",
                   "common.py"):
        body = open(os.path.join(SCRIPTS, script), encoding="utf-8").read()
        for line in body.splitlines():
            if "baselines" in line and write_open.search(line):
                raise AssertionError("%s writes into baselines/: %s" % (script, line))


def _default_for(flag):
    """The default write target of an evaluate.py CLI flag, as a relative path."""
    lines = open(os.path.join(SCRIPTS, "evaluate.py"), encoding="utf-8").read().splitlines()
    for line in lines:
        if '"%s"' % flag in line and "default=" in line:
            tail = line.split("default=", 1)[1]
            if "os.path.join" in tail:
                parts = re.findall(r'"([^"]+)"', tail)
                if parts:
                    return "/".join(parts)
            import evaluate
            name = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", tail)
            if name:
                value = getattr(evaluate, name.group(1), None)
                if isinstance(value, str):
                    return os.path.relpath(value, ROOT)
    return None


# ---------------------------------------------------------------------------
# 5. Packaging: the anchor ships, the runtime products do not
# ---------------------------------------------------------------------------
def _parse_gitignore(text):
    """The subset of gitignore syntax this skill's file actually uses."""
    rules = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        negate = raw.startswith("!")
        pattern = raw[1:].strip() if negate else raw
        directory_only = pattern.endswith("/")
        pattern = pattern.strip("/")
        assert pattern and "\\" not in pattern and not pattern.startswith("!"), (
            "unsupported gitignore rule %r: this checker covers plain globs and "
            "directory rules only - extend it deliberately if the file grows" % raw)
        rules.append({"negate": negate, "pattern": pattern,
                      "directory_only": directory_only, "anchored": "/" in pattern})
    return rules


def _matches(rule, path):
    """Does this rule name this exact path? (patterns without "/" match a segment)"""
    if rule["anchored"]:
        return fnmatch.fnmatchcase(path, rule["pattern"])
    return fnmatch.fnmatchcase(path.split("/")[-1], rule["pattern"])


def _decide(path, rules, is_dir):
    """Last matching rule wins, which is git's rule too."""
    decision = False
    for rule in rules:
        if rule["directory_only"] and not is_dir:
            continue  # `output/` names a directory, never a file called "output"
        if _matches(rule, path):
            decision = not rule["negate"]
    return decision


def _is_ignored(relative_path, rules):
    """True when git would not track this file.

    Everything below an excluded *directory* is excluded, and no negation of a
    file inside it can re-include it - which is exactly the trap this file used
    to fall into, so the semantics are reproduced rather than approximated.
    """
    segments = relative_path.split("/")
    for depth in range(1, len(segments)):
        if _decide("/".join(segments[:depth]), rules, is_dir=True):
            return True
    return _decide(relative_path, rules, is_dir=False)


def test_the_anchor_ships_and_is_not_git_ignored():
    rules = _parse_gitignore(open(GITIGNORE, encoding="utf-8").read())
    for shipped in ("baselines/frozen_baseline.json", "baselines/scope_declaration.json",
                    "baselines/rb-i-2024H1-real.json"):
        assert os.path.isfile(os.path.join(ROOT, shipped)), (
            "acceptance anchor missing from the package: %s" % shipped)
        assert not _is_ignored(shipped, rules), (
            "%s is git-ignored, so installing from git yields no acceptance anchor"
            % shipped)
    for name in EVIDENCE_LANDED_FILES + ("cases_rules_labels.json", "README.md"):
        shipped = os.path.join("evidence", "rb-i-2024H1", name)
        assert os.path.isfile(os.path.join(ROOT, shipped)), (
            "independent-replay evidence missing: %s" % shipped)
        assert not _is_ignored(shipped, rules), (
            "%s must ship so the real anchor can be replayed without raw payloads"
            % shipped)
    # the deterministic fixtures must ship too, or the guard has nothing to run
    for fixture in ("tests/fixtures/bars_RB.csv", "tests/fixtures/bars_I.csv",
                    "tests/fixtures/labels.json", "tests/fixtures/labels_en.json",
                    "tests/fixtures/opinions.json", "tests/test_baseline_guard.py"):
        assert not _is_ignored(fixture, rules), "%s must stay committed" % fixture


def test_runtime_products_stay_git_ignored_and_are_not_the_anchor():
    rules = _parse_gitignore(open(GITIGNORE, encoding="utf-8").read())
    for product in ("output/frozen_baseline.json", "output/scope_declaration.json",
                    "output/baseline.json"):
        assert _is_ignored(product, rules), (
            "%s must stay a runtime product: shipping it would put two copies in the "
            "package, each claiming to be authoritative" % product)
    # landed real data and raw payloads remain ignored, their README markers ship
    assert _is_ignored("tests/fixtures/raw/get_future_daily__RB2405.json", rules)
    assert _is_ignored("tests/fixtures/landed/bars_RB.csv", rules)
    assert _is_ignored("tests/fixtures/landed/provenance.json", rules)
    assert not _is_ignored("tests/fixtures/raw/README.md", rules)
    assert not _is_ignored("tests/fixtures/landed/README.md", rules)


@pytest.mark.skipif(shutil.which("git") is None,
                    reason="no git binary here; the rule check above still decides, "
                           "this cross-check only adds git's own verdict")
def test_git_itself_agrees_on_what_ships():
    """Same .gitignore in a throwaway repo: what does a clean commit actually get?

    ``git check-ignore -v`` is *not* usable as the decision here: it exits 0 for
    any path a pattern matched, including paths whose matching pattern is a
    negation - which would have called baselines/frozen_baseline.json "ignored"
    and told us nothing. The ground truth is the index: ``git add -A`` followed by
    ``git ls-files``, plus ``git status --ignored`` for the excluded set.
    """
    work = tempfile.mkdtemp(prefix="ignore-proof-")
    try:
        shutil.copy(GITIGNORE, os.path.join(work, ".gitignore"))
        paths = ["baselines/frozen_baseline.json", "baselines/scope_declaration.json",
                 "output/frozen_baseline.json", "output/scope_declaration.json",
                 "tests/fixtures/bars_RB.csv", "tests/fixtures/raw/x.json",
                 "tests/fixtures/raw/README.md", "tests/fixtures/landed/provenance.json",
                 "evidence/rb-i-2024H1/bars_I2405.DCE.csv",
                 "evidence/rb-i-2024H1/cases_rules_labels.json",
                 "scripts/evaluate.py", "SKILL.md"]
        for path in paths:
            full = os.path.join(work, path)
            os.makedirs(os.path.dirname(full) or work, exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
        subprocess.run(["git", "init", "-q"], cwd=work, check=True, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=work, check=True, capture_output=True)
        tracked = set(subprocess.run(["git", "ls-files"], cwd=work, capture_output=True,
                                     text=True).stdout.split())
        assert "baselines/frozen_baseline.json" in tracked, (
            "a clean checkout would NOT receive the acceptance anchor")
        assert "baselines/scope_declaration.json" in tracked
        assert "tests/fixtures/bars_RB.csv" in tracked, "the guard needs its fixtures"
        assert "tests/fixtures/raw/README.md" in tracked
        assert "evidence/rb-i-2024H1/bars_I2405.DCE.csv" in tracked, (
            "the derived real-market evidence must ship for independent replay")
        assert "evidence/rb-i-2024H1/cases_rules_labels.json" in tracked
        for must_not in ("output/frozen_baseline.json", "output/scope_declaration.json",
                         "tests/fixtures/raw/x.json",
                         "tests/fixtures/landed/provenance.json"):
            assert must_not not in tracked, "%s must stay out of the package" % must_not

        # `git status --ignored` marks the excluded set with '!!'
        status = subprocess.run(["git", "status", "--porcelain", "--ignored"],
                                cwd=work, capture_output=True, text=True).stdout
        excluded = {line[3:] for line in status.splitlines() if line.startswith("!!")}
        assert not any(entry.startswith("baselines") for entry in excluded), excluded
        assert any(entry.rstrip("/") == "output" or entry.startswith("output")
                   for entry in excluded), excluded

        # and name the rule that does the work, as `git check-ignore -v` reports it
        proc = subprocess.run(["git", "check-ignore", "-v", "--",
                              "output/frozen_baseline.json"],
                              cwd=work, capture_output=True, text=True)
        assert proc.stdout.startswith(".gitignore:") and "output/" in proc.stdout, proc.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------
# 6. Docs must not re-announce the old, unanchored arrangement
# ---------------------------------------------------------------------------
DOC_FILES = ("README.md", "README.en.md", "SKILL.md",
             os.path.join("references", "validation.md"),
             os.path.join("references", "api_guide.md"),
             os.path.join("evidence", "rb-i-2024H1", "README.md"),
             os.path.join("agents", "portable-loader.md"))


def _doc(relative):
    return open(os.path.join(ROOT, relative), encoding="utf-8").read()


def test_docs_point_at_the_committed_anchor_not_the_ignored_directory():
    for relative in DOC_FILES:
        text = _doc(relative)
        if "frozen_baseline.json" in text:
            assert "baselines/frozen_baseline.json" in text, (
                "%s mentions frozen_baseline.json but no longer names the shipped "
                "anchor path baselines/" % relative)
    meta = _read_json(os.path.join(ROOT, "skill.json"))
    outputs = meta["outputs"]
    assert outputs["acceptance_anchor"] == "baselines/frozen_baseline.json"
    assert outputs["acceptance_anchor_scope"] == "baselines/scope_declaration.json"
    assert outputs["regenerated_report"] == "output/frozen_baseline.json"
    assert outputs["acceptance_anchor_is_gitignored"] is False


def test_skill_json_declares_only_paths_that_are_true():
    """Every path skill.json publishes must exist, and its role must match reality.

    The defect this version fixes was exactly this: metadata pointing at an
    acceptance artifact inside a git-ignored directory. A declared anchor that
    a clean checkout cannot ship is not an anchor, so the declaration is now
    checked against the filesystem *and* against the ignore rules.
    """
    meta = _read_json(os.path.join(ROOT, "skill.json"))
    rules = _parse_gitignore(open(GITIGNORE, encoding="utf-8").read())
    outputs = meta["outputs"]
    anchors = [outputs["acceptance_anchor"], outputs["acceptance_anchor_scope"]]
    products = [outputs["regenerated_report"], outputs["regenerated_scope"]]
    for declared in anchors:
        assert os.path.isfile(os.path.join(ROOT, declared)), (
            "skill.json calls %s the acceptance anchor but it is not in the package"
            % declared)
        assert not _is_ignored(declared, rules), (
            "skill.json declares %s as the anchor while .gitignore hides it" % declared)
        assert declared.startswith("baselines/"), declared
    for declared in products:
        assert declared.startswith("output/"), declared
        assert _is_ignored(declared, rules), (
            "%s is declared as a regenerated product but would ship in the package"
            % declared)
    assert outputs["regenerated_products_are_gitignored"] is True
    for key in ("real_market_acceptance_anchor", "real_market_cases_rules_labels"):
        declared = outputs[key]
        assert os.path.isfile(os.path.join(ROOT, declared)), declared
        assert not _is_ignored(declared, rules), declared
    evidence_dir = outputs["real_market_evidence"]
    assert os.path.isdir(os.path.join(ROOT, evidence_dir)), evidence_dir
    assert outputs["real_market_evidence_is_gitignored"] is False
    # the commands it advertises must exist and be the documented entrypoints
    for key, command in outputs.items():
        if not isinstance(command, str) or "scripts/" not in command:
            continue
        script = re.search(r"scripts/[\w/]+\.py", command).group(0)
        assert os.path.isfile(os.path.join(ROOT, script)), (
            "skill.json advertises %s but %s is not there" % (key, script))
    # and the entrypoint metadata must describe real files
    for key in ("entrypoint", "entry_script"):
        assert os.path.isfile(os.path.join(ROOT, meta[key])), "%s is missing" % key


def test_baseline_directory_is_documented_in_the_tree():
    """The shipped anchor must be listed where the package layout is described."""
    for relative in ("README.md", "README.en.md"):
        text = _doc(relative)
        assert "├── baselines/" in text, "%s lost baselines/ from the layout" % relative
        assert "├── output/" in text, "%s lost output/ from the layout" % relative


def test_docs_still_label_output_as_the_regenerated_product():
    """One authority: baselines/ is the reference, output/ is what a run produces."""
    for relative in DOC_FILES:
        text = _doc(relative)
        if "output/" in text:
            assert ("重新生成" in text or "产物" in text or "product" in text.lower()
                    or "runtime" in text.lower()), (
                "%s mentions output/ without saying it is the regenerated landing spot"
                % relative)
    combined = _doc("README.md") + _doc("README.en.md") + _doc("SKILL.md")
    assert "--check-baseline" in combined, "no doc shows how to verify the anchor"
    assert "compare_baseline.py" in combined


def test_no_document_hardcodes_an_install_path():
    """The skill must work installed anywhere, so absolute paths are banned.

    Two blind spots were load-bearing, not cosmetic. The watch list stopped at
    documents, so ``baselines/*.json`` — the only artifacts that publish numbers
    other people are asked to trust — was never read by this check; and the ban
    list stopped at the home-directory prefixes, so a temporary build directory
    was not recognised as an install path at all. Together they let 13 such paths
    ship inside the real-market anchor, where they identified nothing.
    """
    watched = DOC_FILES + ("CHANGELOG.md", os.path.join("scripts", "compare_baseline.py"),
                           os.path.join("tests", "test_baseline_guard.py"))
    banned = ("/Use" + "rs/", "/hom" + "e/", "/tm" + "p/", "/pr" + "ivate/")
    for relative in watched:
        text = _doc(relative)
        for marker in banned:
            assert marker not in text, "%s hardcodes an install path" % relative
    evidence_json = [os.path.join(EVIDENCE_DIR, name)
                     for name in ("provenance.json", "cases_rules_labels.json")]
    for anchor in _shipped_anchor_paths() + evidence_json:
        text = open(anchor, encoding="utf-8").read()
        for marker in banned:
            assert marker not in text, (
                "%s hardcodes a machine path: it must name files portably, or its "
                "published numbers cannot be re-run anywhere else"
                % os.path.basename(anchor))
    for relative in ("scripts/compare_baseline.py", "scripts/evaluate.py",
                     "scripts/data_loader.py"):
        assert "os.path.dirname(os.path.abspath(__file__))" in _doc(relative), (
            "%s must resolve everything from its own location" % relative)


# ---------------------------------------------------------------------------
# The second anchor: shipped real-market reference
#
# ``baselines/rb-i-2024H1-real.json`` publishes acceptance numbers produced from
# licensed PandaData bars. For a long time nothing in this file mentioned it: the
# fixture anchor was guarded field-by-field while the real one was guarded by
# prose in SKILL.md only, and it carried a one-off temporary build directory in
# ``data.landed_dir`` / ``data.built_files`` / ``data.symbols.*.files``. That made
# the numbers unverifiable by anyone else, and the install-path guard could not
# see it because that test watched documents only and banned home-directory
# prefixes only. These tests close both halves of that gap.
# ---------------------------------------------------------------------------

REAL_REPORT = os.path.join(BASELINE_DIR, "rb-i-2024H1-real.json")
SHIP_DIRS = ("tests", "fixtures", "raw")

# Split so this file cannot incriminate itself: it is on the watched list above.
_MACHINE_PATH_MARKERS = ("/Use" + "rs/", "/hom" + "e/", "/tm" + "p/",
                         "/pr" + "ivate/", "/va" + "r/", "/roo" + "t/")


def _shipped_anchor_paths():
    """Every committed anchor JSON, whatever it is named."""
    return sorted(os.path.join(BASELINE_DIR, name)
                  for name in os.listdir(BASELINE_DIR) if name.endswith(".json"))


def _iter_strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            for item in _iter_strings(value, "%s.%s" % (path, key)):
                yield item
    elif isinstance(node, list):
        for index, value in enumerate(node):
            for item in _iter_strings(value, "%s[%d]" % (path, index)):
                yield item
    elif isinstance(node, str):
        yield path, node


@pytest.mark.parametrize("anchor", _shipped_anchor_paths(),
                         ids=lambda p: os.path.basename(p))
def test_no_shipped_anchor_records_a_machine_path(anchor):
    """A shipped report must name files portably, or its numbers are uncheckable.

    A temporary build directory is not provenance, it is a leftover: the
    directory existed for minutes on one machine, so every ``data.*`` path built
    from it identified nothing for a reader. The report must stay readable
    anywhere it is opened.
    """
    text = open(anchor, encoding="utf-8").read()
    payload = json.loads(text)
    offenders = []
    for field, value in _iter_strings(payload):
        if value.startswith("/") or any(marker in value for marker in _MACHINE_PATH_MARKERS):
            offenders.append((field, value))
    assert not offenders, (
        "%s records machine-local paths; use data_loader.portable_path for anything "
        "that enters a report: %s" % (os.path.basename(anchor), offenders[:6]))


def test_real_anchor_is_self_consistent():
    """The real anchor's verdict must follow from its own edge, n and threshold.

    Even before running the shipped-evidence replay, a reader can check that the
    anchor does not contradict itself: ``verdict`` must be what ``decide_verdict``
    returns for the edge and trade count it publishes, and the trade list must
    match the reported count.
    """
    import backtest

    payload = json.load(open(REAL_REPORT, encoding="utf-8"))
    edge, metrics = payload["backtest"]["edge"], payload["backtest"]["metrics"]
    min_trades = payload["scope_declaration"]["min_trades_for_verdict"]
    assert metrics["trades"] == len(payload["backtest"]["trades"])
    assert edge["n"] == len(payload["backtest"]["trades"]), (
        "edge.n must equal the number of simulated trades")
    assert payload["backtest"]["verdict"] == backtest.decide_verdict(
        {"mean": edge["mean"], "lo": edge["ci_low"], "hi": edge["ci_high"]},
        edge["n"], min_trades=min_trades), (
        "the published verdict is not what the published edge implies")
    assert edge["ci_low"] < edge["mean"] < edge["ci_high"]


def test_real_anchor_declares_the_universe_it_actually_used():
    """Scope honoured must be true, or the anchor does not mean what SKILL.md says."""
    payload = json.load(open(REAL_REPORT, encoding="utf-8"))
    assert payload["data_mode"] == "landed"
    assert payload["applicability"]["scope_honoured"] is True, (
        "the anchor is cited as real-market evidence; a degraded scope must not ship")
    assert payload["data"]["all_complete"] is True
    assert not payload["data"]["partial_symbols"], (
        "numbers built from truncated payloads must never back a published claim")


def _payload_dir():
    """Where the licensed raw payloads live, if this machine has them.

    ``tests/fixtures/raw/`` is the documented landing spot and is git-ignored, so
    an install may or may not have it. ``OPINION_TO_RULER_RAW_DIR`` lets a data
    holder point the check at their own copy.
    """
    override = os.environ.get("OPINION_TO_RULER_RAW_DIR")
    if override and os.path.isdir(override):
        return override
    default = os.path.join(ROOT, *SHIP_DIRS)
    return default if os.path.isdir(default) else None


def test_real_anchor_reproduces_from_the_raw_payloads():
    """Rebuild the real anchor from payloads and compare every field.

    This is the check that makes the licensed run more than a screenshot: raw
    payloads land -> ``mcp_landing --build`` -> ``evaluate --landed-dir`` ->
    compare against the shipped anchor. Skips when no payloads are present
    rather than pretending to have verified anything.
    """
    raw = _payload_dir()
    needed = ("get_future_daily__I2405_20240102_20240327.json",
              "get_future_daily__I2409_20240328_20240628.json",
              "get_future_daily__RB_20240102_20240628.json",
              "get_future_dominant__I_RB_20240102_20240628.json")
    if not raw or not all(os.path.exists(os.path.join(raw, n)) for n in needed):
        pytest.skip("licensed raw payloads are not present (git-ignored); "
                    "set OPINION_TO_RULER_RAW_DIR to the payload directory to run")

    work = tempfile.mkdtemp(prefix="real-anchor-")
    # Named so the recorded provenance matches the shipped anchor's landing dir.
    landed = os.path.join(work, "real_landed")
    report = os.path.join(work, "report.json")
    scope = os.path.join(work, "scope.json")
    try:
        built = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS, "mcp_landing.py"), "--build",
             "--raw-dir", raw, "--out-dir", landed,
             "--start", "20240102", "--end", "20240628"],
            capture_output=True, text=True, cwd=ROOT)
        assert built.returncode == 0, built.stdout + built.stderr
        for name in EVIDENCE_LANDED_FILES:
            assert _bytes_of(os.path.join(landed, name)) == _bytes_of(
                os.path.join(EVIDENCE_DIR, name)), (
                "shipped derived evidence differs from a fresh raw-payload build: %s" % name)

        run = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS, "evaluate.py"), "--landed-dir", landed,
             "--start", "20240102", "--end", "20240628",
             "--baseline-output", report, "--scope-output", scope],
            capture_output=True, text=True, cwd=ROOT)
        assert run.returncode == 0, run.stdout + run.stderr

        generated = json.load(open(report, encoding="utf-8"))
        result = compare_baseline.verify(generated, frozen_path=REAL_REPORT,
                                         scope_path=scope)
        assert result["diff_count"] == 0, (
            "the shipped real anchor does not reproduce from its own payloads: %s"
            % [d["field"] for d in _all_diffs(result)][:12])
        # 1526 is the figure the docs quote for the real anchor's field walk.
        assert result["compared"] == 1526, (
            "the real anchor's field walk changed (%d != 1526); README section B "
            "and CHANGELOG quote this number and must be re-synced with it"
            % result["compared"])
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_real_anchor_reproduces_from_shipped_evidence():
    """Replay the real anchor with no raw payloads, login or network access.

    The committed derived CSV/provenance set is copied to the portable directory
    name recorded by the anchor. Everything afterwards is the normal evaluation
    and field-by-field comparator, so a clean clone always executes this guard.
    """
    work = tempfile.mkdtemp(prefix="evidence-anchor-")
    landed = os.path.join(work, "real_landed")
    report = os.path.join(work, "report.json")
    scope = os.path.join(work, "scope.json")
    try:
        os.makedirs(landed)
        for name in EVIDENCE_LANDED_FILES:
            source = os.path.join(EVIDENCE_DIR, name)
            assert os.path.isfile(source), "missing shipped evidence: %s" % name
            shutil.copyfile(source, os.path.join(landed, name))

        run = subprocess.run(
            [PYTHON, os.path.join(SCRIPTS, "evaluate.py"), "--landed-dir", landed,
             "--start", "20240102", "--end", "20240628",
             "--baseline-output", report, "--scope-output", scope],
            capture_output=True, text=True, cwd=ROOT)
        assert run.returncode == 0, run.stdout + run.stderr

        generated = json.load(open(report, encoding="utf-8"))
        result = compare_baseline.verify(generated, frozen_path=REAL_REPORT,
                                         scope_path=scope)
        assert result["diff_count"] == 0, (
            "the real anchor does not reproduce from shipped evidence: %s"
            % [d["field"] for d in _all_diffs(result)][:12])
        assert result["compared"] == 1526
        assert generated["backtest"]["verdict"] == "inconclusive"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_shipped_cases_rules_labels_match_the_twelve_real_trades():
    """The reviewer-facing cases/rules/labels must be complete and reproducible."""
    evidence = _read_json(EVIDENCE_CASES)
    real = _read_json(REAL_REPORT)
    fixture = _read_json(FROZEN_REPORT)
    trades = {t["rule_id"]: t for t in real["backtest"]["trades"]}
    assert evidence["market_data"]["status"] == "real"
    assert evidence["opinion_text"]["status"] == "synthetic"
    assert len(evidence["cases"]) == len(trades) == 12
    assert [c["rule"]["rule_id"] for c in evidence["cases"]] == list(trades)
    assert real["extraction"] == fixture["extraction"], (
        "both anchors intentionally use the same synthetic opinions and labels")

    import build

    opinions = _read_json(os.path.join(ROOT, "tests", "fixtures", "opinions.json"))
    labels = _read_json(os.path.join(ROOT, "tests", "fixtures", "labels.json"))
    extracted = build.run(opinions, {"apply_defaults": True})
    assert extracted["config_hash"] == real["extraction"]["config_hash"]
    assert evidence["extraction"]["config_hash"] == extracted["config_hash"]
    rules = {r["rule_id"]: r for d in extracted["documents"] for r in d["rules"]}
    documents = {d["id"]: d for d in opinions["documents"]}
    samples = {s["id"]: s for s in labels["samples"]}
    for item in evidence["cases"]:
        rule_id = item["rule"]["rule_id"]
        doc_id = rule_id.rsplit("-r", 1)[0]
        opinion = documents[doc_id]
        assert item["case"] == {"id": opinion["id"],
                                "published_at": opinion["published_at"],
                                "text": opinion["text"]}
        assert item["rule"] == rules[rule_id]
        assert item["label"] == samples[doc_id]["labels"]
        assert item["trade"] == trades[rule_id]
        assert samples[doc_id]["text"] == opinion["text"]
        assert samples[doc_id]["published_at"] == opinion["published_at"]

    for path in (EVIDENCE_CASES, os.path.join(EVIDENCE_DIR, "provenance.json")):
        offenders = [(field, value) for field, value in _iter_strings(_read_json(path))
                     if value.startswith("/") or any(m in value for m in
                                                    _MACHINE_PATH_MARKERS)]
        assert not offenders, "evidence records a machine path: %s" % offenders[:6]


# ---------------------------------------------------------------------------
# Products must survive a read-only install, and must not name this machine
# ---------------------------------------------------------------------------
def test_evaluate_writes_products_when_the_install_is_read_only():
    """``evaluate.py`` used to die with a bare PermissionError here.

    The documented landing spot is ``<skill>/output``, which is fine in a
    checkout and wrong in an install: a verified install tree is read-only, so
    the acceptance run crashed *after* computing every number, with no report to
    show for it. The fallback must say which path it used -- silently writing the
    product elsewhere would make ``--check-baseline`` unverifiable.
    """
    import evaluate

    work = tempfile.mkdtemp(prefix="readonly-")
    try:
        locked = os.path.join(work, "output")
        os.makedirs(locked, exist_ok=True)
        os.chmod(locked, 0o500)
        target = os.path.join(locked, "frozen_baseline.json")
        try:
            written = evaluate._write_product(target, {"marker": "payload"})
        finally:
            os.chmod(locked, 0o700)
        assert written != target, "the fallback returned the unwritable path"
        assert os.path.exists(written), written
        assert json.load(open(written, encoding="utf-8"))["marker"] == "payload"
        assert not written.startswith(locked), written
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_fallback_survives_a_read_only_working_directory_too():
    """The install being read-only usually means the *cwd* is read-only as well.

    The first version of this fix fell back to ``./output`` -- which is exactly
    the directory a packaged install keeps read-only, so running the acceptance
    suite from inside such an install still died. A fallback that assumes the
    place it fell back to is writable is not a fallback.
    """
    import evaluate

    work = tempfile.mkdtemp(prefix="both-readonly-")
    saved = os.getcwd()
    try:
        locked = os.path.join(work, "output")
        os.makedirs(locked, exist_ok=True)
        os.chmod(locked, 0o500)
        target = os.path.join(locked, "frozen_baseline.json")
        cwd_dir = os.path.join(work, "cwd")
        os.makedirs(cwd_dir, exist_ok=True)
        os.chmod(cwd_dir, 0o500)
        os.chdir(cwd_dir)                      # cwd 也只读：安装态的真实形状
        try:
            written = evaluate._write_product(target, {"marker": "escaped"})
        finally:
            os.chdir(saved)
            os.chmod(locked, 0o700)
            os.chmod(cwd_dir, 0o700)
        assert written != target, written
        assert not written.startswith(locked), written
        assert not written.startswith(cwd_dir), written
        assert json.load(open(written, encoding="utf-8"))["marker"] == "escaped"
    finally:
        os.chdir(saved)
        shutil.rmtree(work, ignore_errors=True)


def test_unnameable_working_directory_does_not_break_the_happy_path():
    """A failing ``getcwd()`` must not take down a write that was never in doubt.

    The fallback chain resolves candidate locations eagerly, so the first version
    of it called ``os.getcwd()`` before touching the requested -- perfectly
    writable -- path. The machinery built to prevent a crash then became a new
    one, found only by running the exported copy from a shell whose cwd the
    sandbox would not report. Listing a location we cannot name is optional;
    writing the report is not.
    """
    import evaluate

    work = tempfile.mkdtemp(prefix="named-fine-")
    target = os.path.join(work, "output", "frozen_baseline.json")
    saved = os.getcwd

    def exploding_getcwd():
        raise PermissionError(13, "Operation not permitted")

    try:
        os.getcwd = exploding_getcwd
        # The chain still resolves the two locations that do not need cwd at all.
        kinds = [why for _, why in evaluate._product_candidates(target)]
        assert "requested location" in kinds and "skill directory" in kinds, kinds
        assert "working directory" not in kinds, kinds
        written = evaluate._write_product(target, {"marker": "happy path"})
    finally:
        os.getcwd = saved
    assert written == target, (written, target)
    assert json.load(open(written, encoding="utf-8"))["marker"] == "happy path"
    shutil.rmtree(work, ignore_errors=True)


def test_product_candidate_chain_is_ordered_and_names_the_product():
    """The fallback chain must be ordered best-first and keep the file name.

    Name preserved, not renamed: ``compare_baseline.py`` and the docs both point
    at ``frozen_baseline.json``, and a fallback that changed the file name would
    make the printed path impossible to find again. Every entry must carry a
    reason, because "it wrote somewhere" is not enough -- the run has to say
    *where* and *why not the requested place*.
    """
    import evaluate

    work = tempfile.mkdtemp(prefix="nowrite-")
    saved = os.getcwd()
    try:
        locked = os.path.join(work, "output")
        os.makedirs(locked, exist_ok=True)
        os.chmod(locked, 0o500)
        cwd_dir = os.path.join(work, "cwd")
        os.makedirs(cwd_dir, exist_ok=True)
        os.chmod(cwd_dir, 0o500)
        os.chdir(cwd_dir)
        # ROOT 与 tempdir 也在候选链里，所以这里只验证链条本身存在且可解释。
        candidates = evaluate._product_candidates(os.path.join(locked, "x.json"))
        assert len(candidates) >= 3, candidates
        kinds = [why for _, why in candidates]
        assert "working directory" in kinds and "system temporary directory" in kinds, kinds
        names = [os.path.basename(c) for c, _ in candidates]
        assert names.count("x.json") == len(names), names
    finally:
        os.chdir(saved)
        os.chmod(locked, 0o700)
        os.chmod(cwd_dir, 0o700)
        shutil.rmtree(work, ignore_errors=True)


def test_products_are_written_in_place_when_the_directory_is_writable():
    """The fallback must not become the normal case: a writable install keeps
    ``<skill>/output`` as documented."""
    import evaluate

    work = tempfile.mkdtemp(prefix="writable-")
    try:
        target = os.path.join(work, "output", "frozen_baseline.json")
        written = evaluate._write_product(target, {"marker": "in place"})
        assert written == target, (written, target)
        assert json.load(open(written, encoding="utf-8"))["marker"] == "in place"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_portable_path_never_returns_an_absolute_path():
    """``data_loader.portable_path`` is the only naming rule for shipped reports."""
    import data_loader

    inside = os.path.join(data_loader.ROOT, "tests", "fixtures", "bars_RB.csv")
    assert data_loader.portable_path(inside) == "tests/fixtures/bars_RB.csv"

    base = os.path.join(tempfile.gettempdir(), "somewhere", "real_landed")
    outside = os.path.join(base, "bars_I2405.DCE.csv")
    assert data_loader.portable_path(outside, base) == "bars_I2405.DCE.csv", \
        data_loader.portable_path(outside, base)
    assert data_loader.portable_path(outside) == "bars_I2405.DCE.csv"

    note = data_loader.portable_dir(base)
    assert note["landed_dir"] == "real_landed"
    assert note["landed_dir_outside_skill"] is True
    in_skill = data_loader.portable_dir(os.path.join(data_loader.ROOT, "tests",
                                                     "fixtures", "landed"))
    assert in_skill["landed_dir"] == "tests/fixtures/landed"
    assert in_skill["landed_dir_outside_skill"] is False


def test_portable_path_does_not_re_resolve_an_already_relative_name():
    """A relative name must survive untouched.

    Re-running ``abspath`` on ``tests/fixtures/bars_I.csv`` resolves against the
    *current directory*, so running the tool from anywhere else would quietly
    turn a root-relative path into a bare file name and change the anchor.
    """
    import data_loader

    name = "tests/fixtures/bars_I.csv"
    assert data_loader._portable_files([name])[0] == name
    assert data_loader._portable_files([]) == []
    assert data_loader._portable_files([None, 7]) == []


def test_ignore_machine_paths_skips_only_the_landing_dir_name(tmp_path):
    """A renamed ``--out-dir`` must not look like a drifted result.

    ``data.landed_dir`` records the basename of whatever directory the bars were
    landed in, so a reviewer who follows the README but writes ``--out-dir
    my_landed`` gets one MISMATCH and exit code 1 on an otherwise identical run.
    The strict default is unchanged; the flag exists so that reviewer can still
    show every acceptance number matches, and the skipped leaf is named in the
    result rather than silently dropped.
    """
    import compare_baseline

    generated = {"data": {"landed_dir": "renamed_landed"},
                 "backtest": {"mean_net": -0.008188}}
    frozen = {"data": {"landed_dir": "real_landed"},
              "backtest": {"mean_net": -0.008188}}

    diffs, fields = compare_baseline.compare(generated, frozen)
    assert [d["field"] for d in diffs] == ["data.landed_dir"]
    assert "data.landed_dir" in fields

    anchor = tmp_path / "frozen.json"
    anchor.write_text(json.dumps(frozen), encoding="utf-8")
    result = compare_baseline.verify(
        generated, frozen_path=str(anchor), scope_path=None,
        ignore_machine_paths=True,
    )
    assert result["ok"] is True
    assert result["diff_count"] == 0
    assert result["ignored_fields"] == ["data.landed_dir"]
    assert result["compared"] == 1  # only backtest.mean_net is still judged


def test_ignoring_machine_paths_does_not_hide_a_real_regression(tmp_path):
    """The flag must not become a blanket 'ignore data quality' switch."""
    import compare_baseline

    anchor = tmp_path / "frozen.json"
    anchor.write_text(json.dumps(
        {"data": {"landed_dir": "real_landed"},
         "backtest": {"mean_net": -0.008188}}), encoding="utf-8")
    result = compare_baseline.verify(
        {"data": {"landed_dir": "renamed_landed"},
         "backtest": {"mean_net": -0.009999}},
        frozen_path=str(anchor), scope_path=None, ignore_machine_paths=True,
    )
    assert result["ok"] is False
    assert [d["field"] for d in result["sections"][0]["diffs"]] == ["backtest.mean_net"]
