"""Read-only guard for the frozen acceptance anchor.

Why this file exists
--------------------
The acceptance numbers used to live only in ``output/frozen_baseline.json`` —
a directory the skill's own ``.gitignore`` excludes. Anyone installing this skill
from git therefore received a package whose "冻结基线对照" deliverable was absent,
and nothing could check that a re-run still produces what the docs claim. The
frozen reference now ships in ``baselines/`` and this module is the machine check
that a regenerated run still equals it, field by field.

Roles — exactly one authority each
----------------------------------
``baselines/frozen_baseline.json``  REFERENCE. The frozen acceptance anchor.
                                    Committed, never rewritten by a run; only
                                    ``evaluate.py --baseline-output`` or a
                                    deliberate re-freeze may touch it.
``output/frozen_baseline.json``     PRODUCT. Where a run lands. Disposable,
                                    machine-local, git-ignored; it is what this
                                    tool reads to *check* against the reference,
                                    never what the reference defers to.

Usage
-----
Check the current code against the shipped anchor (regenerates from the
deterministic bundled fixtures into a temporary directory, writes nothing)::

    python3 scripts/compare_baseline.py

Check an already produced report instead::

    python3 scripts/compare_baseline.py --report output/frozen_baseline.json

Same check as part of the acceptance run::

    python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json

Exit codes
----------
``0`` every compared field matches; ``1`` at least one field differs (the
offending field paths, the frozen value and the regenerated value are printed);
``2`` the anchor is missing or unreadable, or the arguments are wrong.

This module performs no network access: it reads files inside the skill and,
in regenerate mode, drives ``scripts/evaluate.py`` over the bundled fixtures.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BASELINE_DIR = os.path.join(ROOT, "baselines")
FROZEN_REPORT = os.path.join(BASELINE_DIR, "frozen_baseline.json")
FROZEN_SCOPE = os.path.join(BASELINE_DIR, "scope_declaration.json")

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2

# Full field paths excluded from the comparison, with the reason. ``generated_at``
# is the wall-clock stamp of the run: it cannot match across runs by construction
# and it is not an acceptance number. Every other field of the report is compared,
# so widening this tuple always removes real coverage and must stay this small.
VOLATILE_FIELDS: Tuple[str, ...] = ("generated_at",)

# ``scripts/backtest.py`` publishes every float rounded to 6 decimal places
# (4 for rates, 3 for Sharpe; ``scripts/annotate.py`` uses 4), so a faithful
# re-run is expected to reproduce the frozen value *exactly*. ``FLOAT_TOL`` is
# half a unit of that finest published decimal and exists only to admit
# binary-float representation noise; any change that moves a published digit is
# orders of magnitude larger and is reported. Integers, strings, booleans,
# ``None``, list lengths and key sets are compared exactly - no tolerance.
FLOAT_TOL = 5e-7


class AnchorUnavailable(Exception):
    """The frozen reference is missing or unreadable: nothing can be compared."""


def _display(path: str) -> str:
    """Skill-relative path for messages (an install location is not information)."""
    if not path:
        return "<none>"
    rel = os.path.relpath(path, ROOT)
    return rel if not rel.startswith("..") else path


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _leaf_equal(generated: Any, frozen: Any) -> bool:
    if isinstance(generated, bool) != isinstance(frozen, bool):
        return False
    if _is_number(generated) and _is_number(frozen):
        return abs(generated - frozen) <= FLOAT_TOL
    return generated == frozen


def compare(generated: Any, frozen: Any, prefix: str = "") -> Tuple[List[Dict[str, Any]], List[str]]:
    """Recursively compare a regenerated value with the frozen reference.

    Returns ``(diffs, compared_fields)``: ``diffs`` is a list of
    ``{"field", "kind", "frozen", "generated"}`` records and ``compared_fields``
    lists every leaf field path that was actually judged (declared-volatile fields
    excluded). A field present on only one side, a list of a different length, or a
    value that changed shape is a diff - never a pass. The second return value is
    what lets a test prove the comparison still covers what it is supposed to.
    """
    diffs: List[Dict[str, Any]] = []
    compared: List[str] = []

    if isinstance(generated, dict) and isinstance(frozen, dict):
        for key in sorted(set(generated) | set(frozen)):
            field = "%s.%s" % (prefix, key) if prefix else key
            if field in VOLATILE_FIELDS:
                continue
            if key not in frozen:
                diffs.append({"field": field, "kind": "extra_in_generated",
                              "frozen": None, "generated": _short(generated[key])})
                continue
            if key not in generated:
                diffs.append({"field": field, "kind": "missing_in_generated",
                              "frozen": _short(frozen[key]), "generated": None})
                continue
            sub_diffs, sub_compared = compare(generated[key], frozen[key], field)
            diffs.extend(sub_diffs)
            compared.extend(sub_compared)
        return diffs, compared

    if isinstance(generated, list) and isinstance(frozen, list):
        if len(generated) != len(frozen):
            diffs.append({"field": prefix or "<root>", "kind": "length",
                          "frozen": len(frozen), "generated": len(generated)})
            return diffs, [prefix or "<root>"]
        for index, (item, reference) in enumerate(zip(generated, frozen)):
            field = "%s[%d]" % (prefix, index)
            if isinstance(item, (dict, list)) or isinstance(reference, (dict, list)):
                sub_diffs, sub_compared = compare(item, reference, field)
                diffs.extend(sub_diffs)
                compared.extend(sub_compared)
            elif field in VOLATILE_FIELDS:
                continue
            else:
                compared.append(field)
                if not _leaf_equal(item, reference):
                    diffs.append({"field": field, "kind": "changed",
                                  "frozen": reference, "generated": item})
        return diffs, compared

    if isinstance(generated, (dict, list)) or isinstance(frozen, (dict, list)):
        # one side is a container, the other a scalar: the field changed shape
        name = prefix or "<root>"
        diffs.append({"field": name, "kind": "changed",
                      "frozen": _short(frozen), "generated": _short(generated)})
        return diffs, compared + [name]

    if prefix in VOLATILE_FIELDS:
        return diffs, compared
    name = prefix or "<root>"
    compared.append(name)
    if not _leaf_equal(generated, frozen):
        diffs.append({"field": name, "kind": "changed",
                      "frozen": _short(frozen), "generated": _short(generated)})
    return diffs, compared


def _short(value: Any) -> Any:
    """Scalar values are reported verbatim; containers are reported as shape.

    A diff line must name the old and the new value, but pasting a 40-key dict
    into the message hides the field that actually changed.
    """
    if isinstance(value, dict):
        return "<dict with %d key(s): %s>" % (
            len(value), ", ".join(sorted(value)[:6]) + (" ..." if len(value) > 6 else ""))
    if isinstance(value, list):
        return "<list with %d item(s)>" % len(value)
    return value


def _load_anchor(path: str) -> Any:
    if not os.path.isfile(path):
        raise AnchorUnavailable(
            "frozen reference not found: %s — the acceptance anchor ships in the "
            "baselines/ directory (baselines/frozen_baseline.json, "
            "baselines/scope_declaration.json); restore it or re-install the skill, "
            "and never point this check at a regenerated product under output/"
            % _display(path))
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as exc:
        raise AnchorUnavailable("frozen reference is not valid JSON: %s (%s)"
                                % (_display(path), exc))


def verify(generated: Dict[str, Any], *,
           frozen_path: str = FROZEN_REPORT,
           scope_path: Optional[str] = FROZEN_SCOPE,
           include_fields: bool = False) -> Dict[str, Any]:
    """Judge a freshly produced report against the committed references.

    Read-only: neither file is opened for writing, and nothing is created. The
    standalone ``baselines/scope_declaration.json`` is compared against the
    ``scope_declaration`` block of the same report, which is what ties the two
    shipped references to one another (a drifted scope file is a mismatch).

    ``include_fields`` also returns the paths that were judged, so a test can
    prove the comparison still covers the acceptance numbers instead of trusting
    a count that a narrowed walk would happily keep reporting as "all good".
    """
    sections: List[Dict[str, Any]] = []

    frozen = _load_anchor(frozen_path)
    if not isinstance(frozen, dict):
        raise AnchorUnavailable("frozen reference is not a JSON object: %s"
                                % _display(frozen_path))
    diffs, fields = compare(generated, frozen)
    sections.append(_section(frozen_path, diffs, fields, include_fields))

    if scope_path:
        frozen_scope = _load_anchor(scope_path)
        live_scope = generated.get("scope_declaration")
        if not isinstance(live_scope, dict):
            sections.append({"file": scope_path, "compared": 0, "diffs": [
                {"field": "scope_declaration", "kind": "missing_in_generated",
                 "frozen": "<object>",
                 "generated": _short(live_scope)}]})
        else:
            scope_diffs, scope_fields = compare(live_scope, frozen_scope)
            sections.append(_section(scope_path, scope_diffs, scope_fields,
                                     include_fields))

    diff_count = sum(len(s["diffs"]) for s in sections)
    return {"ok": diff_count == 0, "sections": sections, "diff_count": diff_count,
            "compared": sum(s["compared"] for s in sections),
            "tolerance": FLOAT_TOL, "volatile_fields": list(VOLATILE_FIELDS)}


def _section(path: str, diffs: List[Dict[str, Any]], fields: List[str],
             include_fields: bool) -> Dict[str, Any]:
    section: Dict[str, Any] = {"file": path, "compared": len(fields), "diffs": diffs}
    if include_fields:
        section["fields"] = fields
    return section


def format_lines(result: Dict[str, Any], *, limit: int = 40) -> List[str]:
    """Human-readable, one line per offending field: frozen value -> new value."""
    lines: List[str] = []
    for section in result["sections"]:
        name = _display(section["file"])
        if not section["diffs"]:
            lines.append("[baseline] OK %s: %d field(s) compared, 0 mismatched"
                         % (name, section["compared"]))
            continue
        lines.append("[baseline] MISMATCH %s: %d of %d compared field(s) differ "
                     "(frozen reference -> this run)"
                     % (name, len(section["diffs"]), section["compared"]))
        shown = section["diffs"][:limit]
        for diff in shown:
            lines.append("  - [%s] %s: frozen=%r -> generated=%r"
                         % (diff["kind"], diff["field"], diff["frozen"], diff["generated"]))
        if len(section["diffs"]) > len(shown):
            lines.append("  ... %d more" % (len(section["diffs"]) - len(shown)))
    lines.append("[baseline] verdict: %s" % ("CONSISTENT" if result["ok"] else
                                             "%d FIELD(S) CHANGED" % result["diff_count"]))
    return lines


def regenerate(data_mode: str = "fixture") -> Dict[str, Any]:
    """Run the deterministic bundled-fixture pipeline and return its report.

    Writes only into a temporary directory; ``output/`` is left alone, because a
    read-only check must not overwrite the operator's previous product.
    """
    import evaluate  # noqa: WPS433 - imported late so --report works without deps

    if data_mode != "fixture":
        raise ValueError("regenerate() supports data_mode='fixture' only; a landed "
                         "run has its own data and must be compared against the "
                         "reference frozen from that same data")
    workdir = tempfile.mkdtemp(prefix="baseline-check-")
    try:
        out = os.path.join(workdir, "report.json")
        scope = os.path.join(workdir, "scope_declaration.json")
        rc = evaluate.main(["--fixture", "--baseline-output", out, "--scope-output", scope])
        if rc != 0:
            raise RuntimeError("the fixture run failed (exit %s); fix the run before "
                               "comparing it with the frozen anchor" % rc)
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", default=None, metavar="PATH",
                        help="a report produced by evaluate.py to check. Omit it to "
                             "regenerate from the deterministic bundled fixtures "
                             "(written to a temp dir; output/ is left untouched)")
    parser.add_argument("--frozen", default=FROZEN_REPORT, metavar="PATH",
                        help="frozen reference for the whole report "
                             "(default: %(default)s)")
    parser.add_argument("--scope", default=FROZEN_SCOPE, metavar="PATH",
                        help="frozen reference for the report's scope_declaration "
                             "block; pass an empty value to skip it (default: %(default)s)")
    parser.add_argument("--json", action="store_true",
                        help="emit the structured result as JSON instead of lines")
    args = parser.parse_args(argv)

    frozen_path = os.path.abspath(os.path.expanduser(args.frozen))
    scope_path = os.path.abspath(os.path.expanduser(args.scope)) if args.scope else None

    try:
        if args.report:
            report_path = os.path.abspath(os.path.expanduser(args.report))
            if not os.path.isfile(report_path):
                print("[baseline] error: no such report: %s (run "
                      "python3 scripts/evaluate.py --fixture first, or omit --report "
                      "to regenerate)" % _display(report_path), file=sys.stderr)
                return EXIT_USAGE
            with open(report_path, encoding="utf-8") as fh:
                try:
                    generated = json.load(fh)
                except ValueError as exc:
                    print("[baseline] error: %s is not valid JSON: %s"
                          % (_display(report_path), exc), file=sys.stderr)
                    return EXIT_USAGE
        else:
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                generated = regenerate()
    except AnchorUnavailable as exc:
        print("[baseline] error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    except (RuntimeError, ValueError) as exc:
        print("[baseline] error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE

    try:
        result = verify(generated, frozen_path=frozen_path, scope_path=scope_path)
    except AnchorUnavailable as exc:
        print("[baseline] error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if not args.report:
            print("[baseline] regenerated from the deterministic bundled fixtures "
                  "(data_mode=%s); read-only comparison against the shipped anchor, "
                  "output/ untouched" % generated.get("data_mode", "fixture"))
        for line in format_lines(result):
            print(line, file=sys.stdout if result["ok"] else sys.stderr)
    return EXIT_OK if result["ok"] else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
