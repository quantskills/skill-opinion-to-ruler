"""Score extraction against a human-labelled sample.

Why per-field
-------------
A single accuracy number hides the failure that matters: mapping a vague product
name to the wrong contract. So every field is scored separately, and
``testability`` is scored as a 4-way classification.

Label file format (JSON)::

    {
      "samples": [
        {
          "id": "s001",
          "text": "螺纹钢主力站稳3800看多，跌破3700止损",
          "published_at": "2024-05-06T08:30:00+08:00",
          "labels": {
            "instrument_symbol": "RB",
            "direction": "long",
            "entry_expr": "close > 3800",
            "stop_expr": "close < 3700",
            "exit_expr": null,
            "horizon_days": null,
            "testability": "full"
          }
        }
      ]
    }

``null`` means "the text does not state this field" — predicting a value there is
a false positive and is penalised.

Usage::

    python3 scripts/annotate.py labels.json            # score a label file
    python3 scripts/annotate.py labels.json --json     # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build import run  # noqa: E402

FIELDS = ("instrument_symbol", "direction", "entry_expr", "stop_expr", "exit_expr",
          "horizon_days", "testability")


def _flatten(rule: Dict[str, Any]) -> Dict[str, Any]:
    inst = rule.get("instrument") or {}
    horizon = rule.get("horizon") or {}
    return {
        "instrument_symbol": inst.get("symbol"),
        "direction": rule.get("direction"),
        "entry_expr": (rule.get("entry_trigger") or {}).get("expr"),
        "stop_expr": (rule.get("stop_loss") or {}).get("expr"),
        "exit_expr": (rule.get("exit_rule") or {}).get("expr"),
        "horizon_days": horizon.get("value"),
        "testability": rule.get("testability"),
    }


def _pick(predicted: List[Dict[str, Any]], expected: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pair a predicted rule with the labelled one.

    One labelled opinion may split into several rules. Selection is
    deterministic: prefer matching direction, then the first rule.
    """
    if not predicted:
        return None
    want = expected.get("direction")
    for rule in predicted:
        if rule.get("direction") == want:
            return rule
    return predicted[0]


def score(labels: Dict[str, Any], apply_defaults: bool = False) -> Dict[str, Any]:
    samples = labels.get("samples") or []
    if not samples:
        raise ValueError("label file has no 'samples'")

    counts = {f: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for f in FIELDS}
    per_sample = []

    for sample in samples:
        doc = {"id": sample.get("id"), "text": sample["text"],
               "published_at": sample.get("published_at")}
        result = run(doc, {"apply_defaults": apply_defaults})
        predicted_rules = result["documents"][0]["rules"] + result["documents"][0]["unruleable"]
        chosen = _pick(predicted_rules, sample["labels"])
        predicted = _flatten(chosen) if chosen else {f: None for f in FIELDS}

        row = {"id": sample.get("id"), "fields": {}}
        for field in FIELDS:
            exp = sample["labels"].get(field)
            got = predicted.get(field)
            c = counts[field]
            if exp is None and got is None:
                c["tn"] += 1
                ok = True
            elif exp is None and got is not None:
                c["fp"] += 1
                ok = False
            elif exp is not None and got is None:
                c["fn"] += 1
                ok = False
            else:
                same = str(exp).strip() == str(got).strip()
                c["tp" if same else "fp"] += 1
                if not same:
                    c["fn"] += 1
                ok = same
            row["fields"][field] = {"expected": exp, "predicted": got, "ok": ok}
        per_sample.append(row)

    report = {"samples": len(samples), "fields": {}}
    for field in FIELDS:
        c = counts[field]
        precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else None
        recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else None
        report["fields"][field] = {
            "tp": c["tp"], "fp": c["fp"], "fn": c["fn"], "tn": c["tn"],
            "precision": None if precision is None else round(precision, 4),
            "recall": None if recall is None else round(recall, 4),
            "exact_match_rate": round(
                sum(1 for s in per_sample if s["fields"][field]["ok"]) / len(samples), 4
            ),
        }
    report["per_sample"] = per_sample
    report["overall_exact_match"] = round(
        sum(1 for s in per_sample for f in FIELDS if s["fields"][f]["ok"]) / (len(samples) * len(FIELDS)), 4
    )
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", help="path to the labelled JSON sample file")
    parser.add_argument("--apply-defaults", action="store_true",
                        help="apply the frozen default policy before scoring")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    with open(args.labels, encoding="utf-8") as fh:
        labels = json.load(fh)
    report = score(labels, apply_defaults=args.apply_defaults)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print(f"samples: {report['samples']}   overall exact-match: {report['overall_exact_match']}")
    print(f"{'field':<20}{'prec':>7}{'rec':>7}{'exact':>8}{'fp':>5}{'fn':>5}")
    for field, m in report["fields"].items():
        prec = "-" if m["precision"] is None else f"{m['precision']:.2f}"
        rec = "-" if m["recall"] is None else f"{m['recall']:.2f}"
        print(f"{field:<20}{prec:>7}{rec:>7}{m['exact_match_rate']:>8.2f}{m['fp']:>5}{m['fn']:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())