"""Score extraction against a human-labelled sample.

Why per-field
-------------
A single accuracy number hides the failure that matters: mapping a vague product
name to the wrong contract. So every field is scored separately, and
``testability`` is scored as a 4-way classification.

Why the sample count is published next to the rate
--------------------------------------------------
An exact-match rate of ``1.0`` on a small sample is not evidence of a correct
extractor: it is evidence that nothing was tried that the extractor is bad at.
Sixteen samples where every field matched gives a 95% Clopper-Pearson lower
bound of about ``0.79``, not ``1.00`` — so the bound is printed beside the rate,
and the CLI warns below ``MIN_REPORTABLE_SAMPLES``. The headline number cannot
be read as proof on its own any more.

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

One case is scored differently, on purpose. When the extractor fills a field from
the **frozen default policy** it records that in ``assumed``. Such a value is not
a claim about what the author wrote, so counting it as a true positive would let
the policy grade its own homework, while counting it as a false positive would
penalise documented, correct behaviour. It is counted as ``policy_default`` and
reported separately, and ``exact_match_text_only`` — reading skill with policy
outputs excluded — is published next to the headline rate.

Earlier versions of the bundled labels did the first of these by accident: three
samples carried ``entry_expr = "market_on_next_open"`` as *gold* although the
sentences state no entry condition, i.e. the gold had been copied from extractor
output. Those labels are now ``null`` and land in ``policy_default`` instead.

A sample whose text genuinely yields several rules (one per instrument) may give
``labels`` as a **list**, paired with the predicted rules in order of appearance.
A missing or spurious rule is scored, not silently dropped, so "the sentence had
two instruments and we reported one" is a visible error.

Usage::

    python3 scripts/annotate.py labels.json            # score a label file
    python3 scripts/annotate.py labels.json --json     # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build import run  # noqa: E402

FIELDS = ("instrument_symbol", "direction", "entry_expr", "stop_expr", "exit_expr",
          "horizon_days", "testability")

# ``assumed`` names fields by their schema key; labels name them by field key.
ASSUMED_TO_LABEL = {
    "instrument": "instrument_symbol",
    "direction": "direction",
    "entry_trigger": "entry_expr",
    "stop_loss": "stop_expr",
    "exit_rule": "exit_expr",
    "horizon": "horizon_days",
}

# Below this many samples a perfect score is not a useful claim, so say so.
MIN_REPORTABLE_SAMPLES = 40
CI_LEVEL = 0.95


# ---------------------------------------------------------------------------
# Exact binomial proportion interval (Clopper-Pearson), stdlib only
# ---------------------------------------------------------------------------
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny, eps, fpmin, itmax = 1e-300, 3e-14, 1e-300, 300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbeta + b * math.log1p(-x) + a * math.log(x)) \
        * _betacf(b, a, 1.0 - x) / b


def clopper_pearson_lower(successes: int, trials: int,
                          level: float = CI_LEVEL) -> Optional[float]:
    """One-sided lower bound of an exact binomial interval at ``level``.

    Used instead of a normal approximation because the interesting case is a
    perfect score, where the approximation degenerates to "0 errors, so the
    error rate is zero" — exactly the claim that must not be made.
    """
    if trials <= 0:
        return None
    k, n = successes, trials
    alpha = 1.0 - level
    if k == 0:
        return 0.0
    if k == n:
        # Closed form: I_p(n, 1) = p**n = alpha/2 (two-sided) -> bound.
        return round((alpha / 2.0) ** (1.0 / n), 4)
    target = alpha / 2.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if _betainc(k, n - k + 1, mid) > target:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-12:
            break
    return round(0.5 * (lo + hi), 4)


# ---------------------------------------------------------------------------
# Prediction / label pairing
# ---------------------------------------------------------------------------
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


def _assumed_labels(rule: Optional[Dict[str, Any]]) -> Set[str]:
    """Label-field names the rule does not *read* from the text but was filled."""
    if not rule:
        return set()
    out: Set[str] = set()
    for item in rule.get("assumed") or []:
        name = ASSUMED_TO_LABEL.get(str(item.get("field")))
        if name:
            out.add(name)
    return out


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


def _pairs(sample: Dict[str, Any],
           predicted: List[Dict[str, Any]]) -> List[Tuple[Optional[Dict[str, Any]],
                                                          Optional[Dict[str, Any]]]]:
    """``[(label, prediction)]`` for one sample, ordered and length-checked.

    With ``labels`` as a dict the sample contributes one pair (classic behaviour:
    pick the matching rule). With ``labels`` as a list the sample contributes one
    pair per side, so an over- or under-split sentence is scored rather than
    quietly matched.
    """
    labels = sample.get("labels")
    if isinstance(labels, list):
        count = max(len(labels), len(predicted))
        return [(labels[i] if i < len(labels) else None,
                 predicted[i] if i < len(predicted) else None)
                for i in range(count)]
    return [(labels, _pick(predicted, labels or {}))]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score(labels: Dict[str, Any], apply_defaults: bool = False) -> Dict[str, Any]:
    samples = labels.get("samples") or []
    if not samples:
        raise ValueError("label file has no 'samples'")

    counts = {f: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "policy_default": 0} for f in FIELDS}
    text_only = {f: {"ok": 0, "judged": 0} for f in FIELDS}
    judgements = {f: 0 for f in FIELDS}
    hits = {f: 0 for f in FIELDS}
    per_sample: List[Dict[str, Any]] = []
    rule_count_mismatches = 0

    for sample in samples:
        doc = {"id": sample.get("id"), "text": sample["text"],
               "published_at": sample.get("published_at")}
        result = run(doc, {"apply_defaults": apply_defaults})
        block = result["documents"][0]
        predicted_rules = block["rules"] + block["unruleable"]
        declared = sample.get("labels")
        expected_rules = len(declared) if isinstance(declared, list) else 1
        if expected_rules != len(predicted_rules):
            rule_count_mismatches += 1

        sample_ok = True
        row = {"id": sample.get("id"), "fields": {},
               "predicted_rules": len(predicted_rules), "labelled_rules": expected_rules}
        for label_set, chosen in _pairs(sample, predicted_rules):
            assumed = _assumed_labels(chosen)
            predicted = _flatten(chosen) if chosen else {f: None for f in FIELDS}
            label_set = label_set or {}
            pair_entries: List[Dict[str, Any]] = []
            for field in FIELDS:
                exp = label_set.get(field)
                got = predicted.get(field)
                c = counts[field]
                verdict = "ok"
                if exp is None and got is None:
                    c["tn"] += 1
                    ok = True
                elif exp is None and got is not None:
                    if field in assumed:
                        # Filled by the frozen policy, not read from the text:
                        # neither credit nor blame, but visible in the report.
                        c["policy_default"] += 1
                        ok = True
                        verdict = "policy_default"
                    else:
                        c["fp"] += 1
                        ok = False
                        verdict = "fp"
                elif exp is not None and got is None:
                    c["fn"] += 1
                    ok = False
                    verdict = "fn"
                else:
                    same = str(exp).strip() == str(got).strip()
                    c["tp" if same else "fp"] += 1
                    if not same:
                        c["fn"] += 1
                    ok = same
                    verdict = "ok" if same else "fp_fn"
                # Judgement counters, not per-sample booleans: a list-labelled
                # sample contributes several judgements of the same field, and
                # averaging them into "one sample, one vote" would let a
                # mis-split sentence hide behind the majority.
                judgements[field] += 1
                hits[field] += int(ok)
                if verdict != "policy_default":
                    text_only[field]["judged"] += 1
                    text_only[field]["ok"] += int(ok)
                sample_ok = sample_ok and ok
                entry = {"expected": exp, "predicted": got, "ok": ok, "kind": verdict}
                pair_entries.append(entry)
            for field, entry in zip(FIELDS, pair_entries):
                if field not in row["fields"]:
                    row["fields"][field] = entry
                elif row["fields"][field]["ok"] and not entry["ok"]:
                    row["fields"][field] = entry          # keep the failure visible
        row["all_fields_ok"] = sample_ok
        per_sample.append(row)

    report: Dict[str, Any] = {"samples": len(samples), "fields": {}}
    for field in FIELDS:
        c = counts[field]
        precision = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else None
        recall = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else None
        judged = text_only[field]["judged"]
        report["fields"][field] = {
            "tp": c["tp"], "fp": c["fp"], "fn": c["fn"], "tn": c["tn"],
            "policy_default": c["policy_default"],
            "precision": None if precision is None else round(precision, 4),
            "recall": None if recall is None else round(recall, 4),
            "exact_match_rate": round(hits[field] / judgements[field], 4)
            if judgements[field] else None,
            "exact_match_ci95_low": clopper_pearson_lower(hits[field], judgements[field]),
            "exact_match_text_only": (round(text_only[field]["ok"] / judged, 4)
                                      if judged else None),
            "exact_match_text_only_ci95_low": (clopper_pearson_lower(text_only[field]["ok"], judged)
                                               if judged else None),
            "judgements": judgements[field],
            "judged_without_policy": judged,
        }
    report["per_sample"] = per_sample
    report["rule_count_mismatches"] = rule_count_mismatches
    total_judgements = sum(judgements.values())
    total_hits = sum(hits.values())
    report["overall_exact_match"] = (round(total_hits / total_judgements, 4)
                                     if total_judgements else None)
    clean = sum(1 for s in per_sample if s["all_fields_ok"])
    report["samples_all_fields_correct"] = clean
    report["samples_all_fields_correct_ci95_low"] = clopper_pearson_lower(clean, len(samples))
    report["sufficient_sample_size"] = len(samples) >= MIN_REPORTABLE_SAMPLES
    report["sample_size_note"] = (
        "perfect per-field rates on %d samples give a 95%% lower bound of about %s; "
        "%d+ samples are needed before an exact-match rate reads as evidence rather "
        "than as absence of counter-examples"
        % (len(samples), report["samples_all_fields_correct_ci95_low"],
           MIN_REPORTABLE_SAMPLES)
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

    print("samples: %d   overall exact-match: %s   per-sample all-fields-correct: %d/%d "
          "(95%% lower bound %s)"
          % (report["samples"], report["overall_exact_match"],
             report["samples_all_fields_correct"], report["samples"],
             report["samples_all_fields_correct_ci95_low"]))
    print("rule-count mismatches: %d   fields filled by the frozen policy are counted "
          "separately and excluded from the text-only rates"
          % report["rule_count_mismatches"])
    print("%-20s%7s%7s%8s%9s%6s%6s%8s" % ("field", "prec", "rec", "exact",
                                          "exact95lo", "fp", "fn", "policy"))
    for field, m in report["fields"].items():
        prec = "-" if m["precision"] is None else "%.2f" % m["precision"]
        rec = "-" if m["recall"] is None else "%.2f" % m["recall"]
        lo = "-" if m["exact_match_ci95_low"] is None else "%.2f" % m["exact_match_ci95_low"]
        rate = "-" if m["exact_match_rate"] is None else "%.2f" % m["exact_match_rate"]
        print("%-20s%7s%7s%8s%9s%6d%6d%8d"
              % (field, prec, rec, rate, lo, m["fp"], m["fn"], m["policy_default"]))
    if not report["sufficient_sample_size"]:
        print("[warn] %s" % report["sample_size_note"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
