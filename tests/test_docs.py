"""Documentation claims are checked against real runs, not against prose.

This exists because a previous revision of the README quoted effect sizes that no
run produced: the docs were green, the numbers were wrong, and no test noticed.
Every claim asserted here is derived by *executing* the thing documented.

Guards:

1. The fixture result table in ``README.md`` equals the output of
   ``evaluate.main(["--fixture", ...])`` run right now.
2. The per-file case counts and the total case count written in **both** README
   languages equal pytest's own collection, and the documented list of test
   files is the list that actually exists.
3. ``skill.json``'s version equals the top entry of ``CHANGELOG.md``.
4. The removed legacy fetch channel stays removed, and the docs describe this skill only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

README = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
README_EN = open(os.path.join(ROOT, "README.en.md"), encoding="utf-8").read()


def _run_fixture(tmp_path):
    import evaluate

    out = str(tmp_path / "report.json")
    rc = evaluate.main(["--fixture", "--baseline-output", out,
                        "--scope-output", str(tmp_path / "scope_declaration.json")])
    assert rc == 0
    return json.load(open(out, encoding="utf-8"))


def test_adapter_rule_fields_match_the_emitted_object():
    """``agents/openai.yaml``'s x-rule-fields must be exactly the emitted keys.

    Adapters are what a consumer reads instead of the code. One that lists 13 of
    25 keys hides the fields that matter most for acting safely -- and a field it
    invents would be a promise the tool cannot keep.
    """
    import build

    yml = open(os.path.join(ROOT, "agents", "openai.yaml"), encoding="utf-8").read()
    # The flow sequence is wrapped across lines, so it must be read up to its own
    # closing bracket. Splitting on lines either stops short (only the first line)
    # or runs long (swallowing the next key's value); a non-greedy bracket match
    # does neither.
    match = re.search(r"x-rule-fields:\s*\[(.*?)\]", yml, re.S)
    assert match, "agents/openai.yaml no longer declares x-rule-fields"
    declared = [f.strip() for f in match.group(1).split(",") if f.strip()]

    out = build.run({"text": "\u87ba\u7eb9\u94a2\u7ad9\u4e0a3850\u505a\u591a\uff0c\u672a\u6765\u4e24\u5468\uff0c\u76ee\u68074100\uff0c\u6b62\u635f3800\u3002",
                     "published_at": "2024-01-05T08:30:00+08:00"})
    emitted = list(out["documents"][0]["rules"][0].keys())
    # Key order is presentation; a phantom field or an undeclared real one is drift.
    assert set(declared) == set(emitted), (
        "adapter contract drifted from the code\n  only in yaml : %s\n  only in code: %s"
        % (sorted(set(declared) - set(emitted)), sorted(set(emitted) - set(declared))))
    assert len(declared) == len(set(declared)), "x-rule-fields lists a field twice"


def test_rules_table_matches_the_emitted_rule_object():
    """``references/schema.md``'s rules[] table must list exactly the emitted keys.

    Bidirectional on purpose. A field the code emits and the contract does not
    name is invisible to every reviewer -- that is how a redundant ``source_span``
    (a byte-for-byte copy of ``source_text``) nearly shipped. A field the contract
    names and the code stopped emitting is worse: the docs promise structure the
    tool no longer produces.
    """
    import build

    doc = open(os.path.join(ROOT, "references", "schema.md"), encoding="utf-8").read()
    section = doc.split("## rules[]")[1].split("\n## ")[0]
    # Only the table directly under ``## rules[]`` describes the rule object; the
    # ``###`` sub-tables document the nested dicts (instrument, trigger) and would
    # otherwise read as "documented but never emitted" top-level keys.
    section = section.split("\n###")[0]
    documented = set()
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0].startswith("`"):
            documented.add(cells[0].strip("`"))

    texts = [
        {"text": "\u87ba\u7eb9\u94a2\u4e3b\u529b\u7ad9\u4e0a3900\u770b\u591a\uff0c\u672a\u6765\u4e24\u5468\u76ee\u68074150\uff0c\u8dcc\u78343830\u6b62\u635f\u3002"},
        {"text": "\u4e2d\u79d1\u661f\u56fe\u770b\u591a\u3002"},                      # unmapped instrument
        {"text": "\u87ba\u94a2\u7ad9\u4e0a3850\u505a\u591a\uff0c\u6b62\u635f3%\u3002"},        # percentage level
        {"text": "RB2405\u770b\u591a\uff0c\u76ee\u68074100\u3002"},                    # contract code
    ]
    emitted = set()
    for t in texts:
        out = build.run(dict(t, published_at="2024-01-05T08:30:00+08:00"))
        for d in out["documents"]:
            for rule in d["rules"] + d["unruleable"]:
                emitted |= set(rule.keys())

    assert emitted - documented == set(), "schema.md 未记录这些字段：%s" % sorted(emitted - documented)
    assert documented - emitted == set(), "schema.md 记录了代码不再输出的字段：%s" % sorted(documented - emitted)


def _row(markdown: str, label: str) -> str:
    """Value cell of the ``| label | value |`` row inside section A."""
    section = markdown.split("### A.")[1].split("### B.")[0]
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == label:
            return cells[1]
    raise AssertionError("README no longer documents the row %r" % label)


def _numbers(text: str):
    """Floats in order, with the decimal places the doc chose to print."""
    out = []
    for token in re.findall(r"[-−+]?\d+(?:\.\d+)?", text.replace("+", "")):
        value = float(token.replace("−", "-"))
        decimals = len(token.split(".", 1)[1]) if "." in token else 0
        out.append((value, decimals))
    return out


def _assert_numbers(doc_text: str, actual, label: str):
    pairs = _numbers(doc_text)
    assert len(pairs) == len(actual), "%s: README prints %d numbers, run produced %d" % (
        label, len(pairs), len(actual))
    for (printed, decimals), real in zip(pairs, actual):
        assert abs(printed - round(float(real), decimals)) < 1e-12, (
            "%s: README says %s, the actual run gives %s" % (label, printed, real))


@pytest.fixture(scope="module")
def fixture_report(tmp_path_factory):
    return _run_fixture(tmp_path_factory.mktemp("docs"))


# ---------------------------------------------------------------------------
# 1. The result table
# ---------------------------------------------------------------------------
def test_readme_fixture_table_matches_a_real_run(fixture_report):
    s = fixture_report["extraction"]["summary"]
    acc = fixture_report["extraction"]["accuracy"]
    m = fixture_report["backtest"]["metrics"]
    e = fixture_report["backtest"]["edge"]

    # 26 个样本、27 条判定、exact-match 1.00：三个数字都要对上实跑
    judged = acc["fields"]["instrument_symbol"]["judgements"]
    _assert_numbers(_row(README, "标注样本 / 逐字段 exact-match"),
                    [acc["samples"], judged, acc["overall_exact_match"]],
                    "samples/judgements/exact-match")
    assert judged >= acc["samples"], (judged, acc["samples"])
    assert acc["samples_all_fields_correct"] == acc["samples"], acc
    assert 0.0 < acc["samples_all_fields_correct_ci95_low"] < 1.0, acc
    _assert_numbers(_row(README, "规则产出"),
                    [s["rules_total"], s["rules_full"], s["rules_partial"],
                     s["rules_neutral"], s["unruleable"]], "rules")
    _assert_numbers(_row(README, "可规则化比例"), [s["ruleable_share"]], "ruleable share")
    _assert_numbers(_row(README, "回测成交"), [m["trades"], m["skipped"]], "trades")
    _assert_numbers(_row(README, "净收益均值 / 胜率"),
                    [m["mean_net_return"], m["win_rate"]], "mean/win")
    _assert_numbers(_row(README, "Sharpe（逐笔 / 年化）"),
                    [m["sharpe_per_trade"], m["sharpe"]], "sharpe")
    assert m["sharpe"] != round(m["sharpe_per_trade"] * (244 ** 0.5), 3), \
        "the annualised figure must not be the sqrt(244) scaling of per-trade"
    assert m["sharpe"] == round(m["sharpe_per_trade"] * (m["sharpe_trades_per_year"] ** 0.5), 3)
    _assert_numbers(_row(README, "配对 edge vs 持有"),
                    [e["mean"], e["ci_low"], e["ci_high"], e["n"]], "edge")
    assert _row(README, "判定").strip("`") == fixture_report["backtest"]["verdict"]


def test_readme_verdict_reason_is_the_trade_gate_not_a_straddling_ci(fixture_report):
    """The CI here is entirely negative; n=10 is what makes it inconclusive.

    A doc that says "CI 跨过 0" for this row would be describing a different run.
    """
    e = fixture_report["backtest"]["edge"]
    m = fixture_report["backtest"]["metrics"]
    verdict = fixture_report["backtest"]["verdict"]
    assert e["ci_high"] < 0 and e["ci_low"] < 0
    assert m["trades"] < fixture_report["scope_declaration"]["min_trades_for_verdict"]
    assert verdict == "inconclusive"
    section = README.split("### A.")[1].split("### B.")[0]
    assert "门槛" in section, "README must attribute the inconclusive verdict to n"
    assert "两端都为负" in section, "README must not imply this CI straddles zero"


def test_english_readme_quotes_the_same_edge(fixture_report):
    """Both README languages must carry the same numbers, not drift apart."""
    e = fixture_report["backtest"]["edge"]
    assert "### A." in README_EN, "README.en.md lost the fixture results section"
    section = README_EN.split("### A.")[1].split("### B.")[0]
    rows = [line for line in section.splitlines()
            if "edge" in line.lower() and line.strip().startswith("|")]
    assert rows, "README.en.md lost its edge row"
    cells = [c.strip() for c in rows[0].strip().strip("|").split("|")]
    _assert_numbers(cells[1], [e["mean"], e["ci_low"], e["ci_high"], e["n"]], "EN edge row")


def test_both_readmes_quote_the_same_sharpe_basis(fixture_report):
    """Per-trade and annualised Sharpe must appear together in both languages.

    Publishing only the annualised column is what let the sqrt(244) mistake survive:
    11.85 looked plausible on its own. With 0.759 next to it, the scaling is visible
    and a reader can see which convention is being used.
    """
    m = fixture_report["backtest"]["metrics"]
    for doc, label, lang in ((README, "Sharpe（逐笔 / 年化）", "CN"),
                             (README_EN, "Sharpe (per trade / annualised)", "EN")):
        _assert_numbers(_row(doc, label), [m["sharpe_per_trade"], m["sharpe"]],
                        "%s sharpe row" % lang)


def test_english_readme_reports_real_numbers_not_a_placeholder(fixture_report):
    """README section B must carry the reproduced real anchor, not 待重测 prose.

    SKILL.md quoted the real anchor's n=12 / edge +0.012154 while the README said
    this version has no real-bar numbers at all. Two documents in one package
    contradicting each other is how a stale disclaimer outlives the data.
    """
    real = json.load(open(os.path.join(ROOT, "baselines", "rb-i-2024H1-real.json"),
                          encoding="utf-8"))
    mr, er = real["backtest"]["metrics"], real["backtest"]["edge"]
    assert "no real-bar numbers" not in README_EN and "待重测" not in README
    for doc, lang in ((README, "CN"), (README_EN, "EN")):
        section = doc.split("### B.")[1]
        _assert_numbers(_row_of(section, "Sharpe"), [mr["sharpe_per_trade"], mr["sharpe"]],
                        "%s section B sharpe" % lang)
        _assert_numbers(_row_of(section, "edge"), [er["mean"], er["ci_low"], er["ci_high"],
                                                   er["n"]], "%s section B edge" % lang)
        assert "inconclusive" in section, "%s section B must not upgrade the verdict" % lang


def _row_of(markdown_section: str, needle: str) -> str:
    """Value cell of the first table row whose label contains ``needle``."""
    for line in markdown_section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2 and needle in cells[0]:
            return cells[1]
    raise AssertionError("no section-B row labelled %r" % needle)



# ---------------------------------------------------------------------------
# 2. Documented case counts
# ---------------------------------------------------------------------------
TEST_FILES = ("test_ruler.py", "test_mcp_landing.py", "test_docs.py",
              "test_baseline_guard.py", "test_preflight.py", "test_contest_verify.py")


def _collected(test_file: str) -> int:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", os.path.join("tests", test_file),
         "-q", "--collect-only", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def _collected_total() -> int:
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "tests", "-q", "--collect-only",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def test_documented_case_counts_match_pytest():
    """Every per-file count, in both README languages, equals real collection."""
    for test_file in TEST_FILES:
        for doc, unit in ((README, r"(?:个用例|cases|tests)"),
                          (README_EN, r"(?:cases|tests|个用例)")):
            claimed = re.search(re.escape(test_file) +
                                r"[^\n]*?(\d+)\s*" + unit, doc)
            assert claimed, "README no longer states a case count for %s" % test_file
            assert int(claimed.group(1)) == _collected(test_file), (
                "%s: README says %s cases, pytest collects %d"
                % (test_file, claimed.group(1), _collected(test_file)))


def test_documented_total_case_count_matches_pytest():
    """The suite total quoted in the docs is pytest's own collection, not folklore.

    Docs that hardcode "118 passed" age silently the moment a guard is added, and
    a stale total is how a missing guard gets mistaken for a passing suite. Where
    the doc also spells out the per-file breakdown, that breakdown is judged too:
    bumping a total while its components go stale is exactly the half-update that
    makes a suite look bigger than it is.
    """
    total = _collected_total()
    per_file = [_collected(test_file) for test_file in TEST_FILES]
    quoted = []
    for rel in ("README.md", "README.en.md",
                os.path.join("agents", "portable-loader.md")):
        doc = _read(os.path.join(ROOT, rel))
        for line in doc.splitlines():
            if "pytest tests/" not in line:
                continue
            # Only a *full-suite* line documents the total. A targeted invocation
            # (`-k reproduces`, one file, one node id) states no total, so forcing
            # one onto it would be the guard inventing a requirement. A full-suite
            # count is still pinned either way, and per-file counts have their own
            # guard further up this file.
            if re.search(r"-k\s|::|tests/test_\w+\.py", line):
                continue
            found = re.search(r"(\d+)\s*(?:个用例|cases|tests)", line)
            assert found, "%s: the pytest line lost its documented total: %r" % (
                rel, line)
            quoted.append((rel, int(found.group(1))))
            claimed = [int(part) for part in re.findall(r"\d+", line[found.end():])]
            if claimed:
                assert claimed == per_file, (
                    "%s: breakdown %s is stale; pytest collects %s for %s"
                    % (rel, claimed, per_file, list(TEST_FILES)))
                assert sum(claimed) == int(found.group(1)), (
                    "%s: breakdown %s sums to %d but the same line claims %d"
                    % (rel, claimed, sum(claimed), int(found.group(1))))
    assert quoted, "no README quotes a suite total any more"
    stale = [(rel, n) for rel, n in quoted if n != total]
    assert not stale, "docs quote %s but pytest collects %d" % (stale, total)


def test_documented_test_file_list_is_the_real_one():
    """The tests/ tree in the docs lists exactly the modules that exist."""
    real = sorted(f for f in os.listdir(os.path.join(ROOT, "tests"))
                  if f.startswith("test_") and f.endswith(".py"))
    for rel, doc in (("README.md", README), ("README.en.md", README_EN)):
        section = doc.split("├── tests/")[1].split("references/")[0] if "├── tests/" in doc else doc
        documented = sorted(set(re.findall(r"(test_\w+\.py)", section)))
        assert documented == real, (
            "%s documents %s but tests/ holds %s" % (rel, documented, real))


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_no_document_claims_the_removed_sdk_channel():
    """Docs may name the old channel only as history (CHANGELOG) or as removed."""
    banned = ("export PANDA_DATA_" + "", "pip install " + '"panda-data',
              "--panda" + " ", "panda_data login failed", "ModuleNotFoundError: panda_data",
              "SDK")
    docs = ["README.md", "README.en.md", "SKILL.md", "INSTALL.md",
            os.path.join("references", "api_guide.md"),
            os.path.join("references", "validation.md"),
            os.path.join("references", "mcp-data.md"),
            os.path.join("agents", "portable-loader.md"),
            os.path.join("agents", "cursor-rule.mdc"),
            os.path.join("agents", "openai.yaml")]
    hits = []
    for rel in docs:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        for token in banned:
            if token in text:
                hits.append("%s: %s" % (rel, token))
    assert hits == [], "docs still advertise the SDK channel: %s" % hits


# ---------------------------------------------------------------------------
# 3. The docs must describe this skill only
# ---------------------------------------------------------------------------
DOCS = ("README.md", "README.en.md", "SKILL.md", "INSTALL.md",
        os.path.join("references", "api_guide.md"),
        os.path.join("references", "mcp-data.md"),
        os.path.join("references", "schema.md"),
        os.path.join("references", "validation.md"),
        os.path.join("agents", "portable-loader.md"),
        os.path.join("agents", "cursor-rule.mdc"),
        os.path.join("agents", "openai.yaml"))


def test_no_document_references_another_skill():
    """技能要能独立安装独立运行：文档里不出现别的技能的名字、脚本或目录约定。

    Tokens are assembled at run time so this checking file is not itself a hit.
    """
    banned = ("skill-" + "quant-data-pipeline", "fetch_" + "pandadata_mcp",
              "pandadata-" + "mcp-cache", "data/raw/" + "mcp_cache",
              "_manifest" + ".jsonl", "mcp_cache", "cache_dir",
              "--cache-dir", "allow-partial" + " at eval", "/Users" + "/")
    hits = []
    for rel in DOCS:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        for token in banned:
            if token in text:
                hits.append("%s: %s" % (rel, token))
    assert hits == [], "docs still describe the removed cross-skill design: %s" % hits


def test_documents_describe_the_agent_landing_chain():
    """Every data section must state the only true order of operations:
    agent calls MCP -> payload lands in this skill's fixtures/raw -> build -> run."""
    checked = [rel for rel in ("SKILL.md", "README.md", "README.en.md", "INSTALL.md",
                              os.path.join("references", "mcp-data.md"))
               if os.path.isfile(os.path.join(ROOT, rel))]
    assert checked
    for rel in checked:
        text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        assert "mcp__pandadata__call_pandadata" in text, f"{rel} 没写 MCP 调用"
        assert "mcp_landing.py" in text, f"{rel} 没写构建步骤"
        assert "fixtures" + "/raw" in text.replace(os.sep, "/"), \
            f"{rel} 没写本技能自有的落点"


# ---------------------------------------------------------------------------
# 4. Version coherence
# ---------------------------------------------------------------------------
def test_skill_version_matches_top_changelog_entry():
    meta = json.load(open(os.path.join(ROOT, "skill.json"), encoding="utf-8"))
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    top = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert top, "CHANGELOG has no version heading"
    assert meta["version"] == top.group(1), (
        "skill.json is %s but the newest CHANGELOG entry is %s"
        % (meta["version"], top.group(1)))


def _newest_changelog_entry() -> str:
    changelog = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    headings = list(re.finditer(r"^## \[", changelog, re.M))
    assert headings, "CHANGELOG has no version heading"
    start = headings[0].start()
    end = headings[1].start() if len(headings) > 1 else len(changelog)
    return changelog[start:end]


def test_removed_channel_is_recorded_as_breaking():
    newest = _newest_changelog_entry()
    assert "breaking" in newest.lower()
    assert "MCP" in newest


def test_every_version_declaration_is_in_sync():
    """skill.json and any adapter that states a version must agree, everywhere.

    A bumped package with a stale adapter version is how an installed skill ends up
    reporting itself as something it is not.
    """
    meta = json.load(open(os.path.join(ROOT, "skill.json"), encoding="utf-8"))
    declared = {"skill.json": meta["version"]}
    for rel in ("agents/openai.yaml", "agents/cursor-rule.mdc",
                "agents/portable-loader.md"):
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        for match in re.finditer(r"^[ \t]*version:[ \t]*[\"']?(\d+\.\d+\.\d+)",
                                 open(path, encoding="utf-8").read(), re.M):
            declared[rel] = match.group(1)
    assert set(declared.values()) == {meta["version"]}, (
        "version declarations disagree: %s" % declared)
    changelog_top = re.search(r"^## \[(\d+\.\d+\.\d+)\]",
                              open(os.path.join(ROOT, "CHANGELOG.md"),
                                   encoding="utf-8").read(), re.M)
    assert changelog_top and changelog_top.group(1) == meta["version"], (
        "CHANGELOG top entry is %s, everything else says %s"
        % (changelog_top and changelog_top.group(1), meta["version"]))




def test_documented_extractor_fingerprint_matches_the_code():
    """``build.VERSION`` is a *second* version namespace, and it drifts silently.

    The package version (skill.json / CHANGELOG) has its own agreement guard above,
    but the extractor version is what actually enters ``config_hash``: a dictionary
    change that bumps it re-signs both anchors while leaving the package version
    alone. Until now nothing tied ``references/schema.md`` to it, so the documented
    fingerprint stayed on the previous value after a real semantics change -- docs
    describing an extractor that no longer exists.

    The SKILL.md output example is checked too, against the *shipped anchor's* hash
    rather than against itself: an illustrative hash that matches nothing real is
    folklore with a hex face.
    """
    import build

    version = build.VERSION
    schema = _read(os.path.join(ROOT, "references", "schema.md"))
    documented = re.findall(r"extractor_version`?\s*\|[^|]*\|[^`]*`([\d.]+)`", schema)
    assert "`%s`" % version in schema, (
        "references/schema.md documents extractor_version %s but build.VERSION is %s"
        % (documented, version))
    assert "rule-based-%s" % version in schema, (
        "references/schema.md still shows an old config_hash example")
    assert schema.count("rule-based-") == 1, (
        "references/schema.md carries more than one rule-based-* fingerprint: %d"
        % schema.count("rule-based-"))

    skill = _read(os.path.join(ROOT, "SKILL.md"))
    anchor = json.loads(_read(os.path.join(ROOT, "baselines", "frozen_baseline.json")))
    real = anchor["extraction"]["config_hash"]
    quoted = re.findall(r'"config_hash":\s*"([0-9a-f]{6,})\.\.\."', skill)
    assert quoted, "SKILL.md no longer shows a truncated config_hash example"
    assert quoted[0] == real[:len(quoted[0])], (
        "SKILL.md's example config_hash is %s but the shipped anchor says %s"
        % (quoted[0], real[:len(quoted[0])]))
    # Bumping the extractor version must be *visible* in the fingerprint, or the
    # constant is theatre: its purpose is letting a caller see the algorithm moved.
    # Recomputed through the public API (not by restating the hash formula) so this
    # guard also proves the shipped anchor was signed by *this* build of the
    # extractor under the policy evaluate.py actually uses.
    import build as _build
    live = _build.run({"text": u"占位", "published_at": "2024-01-05T08:30:00+08:00"},
                      {"apply_defaults": True})
    assert live["config_hash"] == real, (
        "the shipped anchor was signed by a different extractor/policy than the code "
        "in this package produces (%s vs %s)" % (live["config_hash"][:8], real[:8]))
    assert live["config"]["extractor"] == "rule-based-" + version, live["config"]


def test_changelog_current_entry_quotes_the_live_suite_total():
    """The top CHANGELOG entry's suite-size claim is checked against real collection.

    The count guard above reads the two READMEs and the loader note, so the
    CHANGELOG sat outside it and drifted twice in one session: it said "164 → 220"
    while the suite had already moved to 223 and then 224. Same failure mode, fourth
    file -- which is why the fix is to widen the watch list, not to patch the number.

    Scope matters the other way too: earlier releases record the count that was true
    when *they* shipped, and rewriting those to the live total would be falsifying
    history. Only the entry matching ``skill.json``'s version is judged.
    """
    BEFORE = 164          # collected by the installed package this audit started from

    text = _read(os.path.join(ROOT, "CHANGELOG.md"))
    meta = json.loads(_read(os.path.join(ROOT, "skill.json")))
    sections = [sec for sec in re.split(r"(?m)^## ", text) if sec.startswith("[")]
    assert sections, "CHANGELOG has no version sections"
    top = sections[0]
    top_version = top.split("]")[0].lstrip("[")
    assert top_version == meta["version"], (
        "CHANGELOG top entry is %s but skill.json says %s" % (top_version, meta["version"]))

    total = _collected_total()
    grown = [int(n) for n in re.findall(r"%d\s*→\s*(\d+)\s*条用例" % BEFORE, top)]
    assert grown, "the %s entry no longer states how far the suite grew" % top_version
    stale = [n for n in grown if n != total]
    assert not stale, ("CHANGELOG %s says the suite is %s but pytest collects %d; "
                       "earlier entries are history and are not checked"
                       % (top_version, stale, total))

    added = [int(n) for n in re.findall(r"新增\s*(\d+)\s*条", top)]
    assert added, "the %s entry no longer states how many cases were added" % top_version
    wrong = [n for n in added if n != total - BEFORE]
    assert not wrong, ("CHANGELOG claims %s added cases; %d - %d = %d"
                       % (wrong, total, BEFORE, total - BEFORE))


def test_agent_normalization_protocol_is_documented():
    """The pre-normalization conduct must live in SKILL.md and both READMEs.

    Extraction is lexicon + regex and only accepts canonical sentences. The
    fallback for non-normalizable input is refuse + name the missing essential
    + give one canonical example -- never invent levels. If this protocol
    silently disappears from the docs, reading agents will start feeding the
    extractor fabricated input, and every downstream number becomes fiction
    with a clean audit trail.
    """
    skill = _read(os.path.join(ROOT, "SKILL.md"))
    for token in ("非标准输入的规范化前置", "不具备分析要点", "规范语句",
                  "禁止增删改任何价格水平、方向、品种"):
        assert token in skill, "SKILL.md lost the normalization protocol: %r" % token

    for token in ("规范化", "不具备分析要点", "规范语句示例"):
        assert token in README, "README.md lost the normalization bullet: %r" % token
    for token in ("normaliz", "analyzable essentials", "canonical example"):
        assert token.lower() in README_EN.lower(), \
            "README.en.md lost the normalization bullet: %r" % token
