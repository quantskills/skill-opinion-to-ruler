"""skill-opinion-to-ruler — turn a subjective trading opinion into testable rules.

Layers
------
1. ``validate_input``  — reject malformed documents early
2. ``extract_rule`` / ``extract_document`` — pure extraction, no I/O
3. ``assess``          — testability classification + frozen defaults
4. ``run`` / ``print_rules`` — composition and presentation

Hard rule: never invent a field the text does not contain. Anything absent is
``None`` and named in ``missing_fields`` so a human annotator can score it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

try:  # package import
    from .common import (  # type: ignore
        LONG_WORDS,
        PULLBACK_KW,
        SHORT_WORDS,
        _has_word,
        clamp_text,
        find_direction,
        find_horizon,
        find_instrument,
        parse_levels,
    )
except ImportError:  # direct execution (also under ``python -I``)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from common import (  # type: ignore
        LONG_WORDS,
        PULLBACK_KW,
        SHORT_WORDS,
        _has_word,
        clamp_text,
        find_direction,
        find_horizon,
        find_instrument,
        parse_levels,
    )

VERSION = "0.2.2"

# ---------------------------------------------------------------------------
# Frozen default policy
# ---------------------------------------------------------------------------
# Applied only when ``config["apply_defaults"]`` is True. Frozen *before* any
# backtest is inspected. Changing it changes ``config_hash`` and breaks
# comparability with earlier runs by design.
DEFAULT_POLICY: Dict[str, Any] = {
    "version": "frozen-1",
    "missing_horizon": {"value": 5, "unit": "trading_day", "expiry_action": "force_close"},
    "missing_entry": "market_on_next_open",
    "missing_position_size": "equal_weight_unit",
}

SCHEMA_VERSION = "rule-v1"

_SENT_SPLIT = re.compile(r"(?<=[。；;！!？?])|\n+")

# Decimal point must not split a sentence ("targets 4100.5").
_SENT_SPLIT_EN = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9\"'(])|\n+")


def _split_sentences(text: str) -> List[str]:
    """Split on Chinese and English sentence terminators, keeping decimals intact."""
    if re.search(r"[一-鿿]", text):
        parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    else:
        parts = [p.strip() for p in _SENT_SPLIT_EN.split(text) if p and p.strip()]
    return parts or [text.strip()]


# ---------------------------------------------------------------------------
# 1. Validation
# ---------------------------------------------------------------------------
def validate_input(input_data: Any) -> None:
    """Raise ``ValueError`` / ``TypeError`` with a precise message."""
    if input_data is None:
        raise ValueError("input_data must not be None")

    if isinstance(input_data, str):
        if not input_data.strip():
            raise ValueError("input_data text is empty")
        return

    if isinstance(input_data, dict):
        if "documents" in input_data:
            docs = input_data["documents"]
            if not isinstance(docs, list):
                raise TypeError("input_data['documents'] must be a list")
            if not docs:
                raise ValueError("input_data['documents'] is empty")
            for i, doc in enumerate(docs):
                try:
                    validate_input(doc)
                except (ValueError, TypeError, KeyError) as exc:
                    raise type(exc)(f"documents[{i}]: {exc}") from exc
            return
        if "text" not in input_data:
            raise KeyError("input_data requires a 'text' field")
        _validate_doc(input_data)
        return

    if isinstance(input_data, list):
        if not input_data:
            raise ValueError("input_data list is empty")
        for i, doc in enumerate(input_data):
            try:
                validate_input(doc)
            except (ValueError, TypeError, KeyError) as exc:
                raise type(exc)(f"input_data[{i}]: {exc}") from exc
        return

    raise TypeError(f"unsupported input_data type: {type(input_data).__name__}")


def _validate_doc(doc: Dict[str, Any]) -> None:
    if not isinstance(doc["text"], str):
        raise TypeError("input_data['text'] must be a string")
    if not doc["text"].strip():
        raise ValueError("input_data['text'] is empty")
    for key in ("id", "source"):
        val = doc.get(key)
        if val is not None and not isinstance(val, str):
            raise TypeError(f"input_data[{key!r}] must be a string or None")
    published = doc.get("published_at")
    if published is not None:
        if not isinstance(published, str):
            raise TypeError("input_data['published_at'] must be an ISO-8601 string or None")
        if not re.match(r"^\d{4}-\d{2}-\d{2}", published):
            raise ValueError("input_data['published_at'] must start with YYYY-MM-DD")


# ---------------------------------------------------------------------------
# 2. Extraction
# ---------------------------------------------------------------------------
def _split_sentences(text: str) -> List[str]:
    """Split on Chinese and English sentence terminators, keeping decimals intact."""
    if re.search(r"[一-鿿]", text):
        parts = [p.strip() for p in _SENT_SPLIT.split(text) if p and p.strip()]
    else:
        parts = [p.strip() for p in _SENT_SPLIT_EN.split(text) if p and p.strip()]
    return parts or [text.strip()]


def _resolve_direction(text: str, levels: Dict[str, Any]):
    """Return ``(direction, word, negated, inferred)``.

    Explicit wording wins. When absent, the *profit target* decides: an upside
    target with no downside target is a long view, and the mirror image is a
    short view. A trigger level alone is not directional (``站上``/``跌破``
    describe the condition, not the side), so it is never used to infer.
    """
    direction, word, negated = find_direction(text)
    if direction is not None:
        if negated:
            direction = {"long": "short", "short": "long", "neutral": "neutral"}[direction]
        return direction, word, negated, False

    if levels["target_up"] and not levels["target_down"]:
        return "long", None, False, True
    if levels["target_down"] and not levels["target_up"]:
        return "short", None, False, True
    return None, None, False, False


def extract_rule(sentence: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract one rule from one sentence. Pure function."""
    ctx = context or {}
    text = clamp_text(sentence)
    notes: List[Dict[str, str]] = []

    instrument = find_instrument(text)
    inherited_instrument = False
    if instrument is None and ctx.get("instrument"):
        instrument = copy.deepcopy(ctx["instrument"])
        inherited_instrument = True
        notes.append(
            {"field": "instrument", "issue": "not stated in this sentence; inherited from an earlier sentence"}
        )

    horizon = find_horizon(text)
    inherited_horizon = False
    if horizon is None and ctx.get("horizon"):
        horizon = copy.deepcopy(ctx["horizon"])
        inherited_horizon = True

    levels = parse_levels(text)
    direction, word, negated, inferred = _resolve_direction(text, levels)

    has_long = any(_has_word(text, w) for w in LONG_WORDS)
    has_short = any(_has_word(text, w) for w in SHORT_WORDS)
    if has_long and has_short:
        notes.append({"field": "direction", "issue": "both long and short wording in one sentence"})
    if negated:
        notes.append({"field": "direction", "issue": f"negation before '{word}'; direction flipped"})
    if inferred:
        notes.append(
            {"field": "direction", "issue": "no explicit long/short wording; inferred from the stated profit target"}
        )

    entry_trigger = None
    pullback = re.search(
        PULLBACK_KW + r"(?:\s*(?:到|至|在|at|to|around|near))?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if direction == "long":
        level = levels["up"]
        if level:
            entry_trigger = {
                "type": "price_condition",
                "expr": f"close > {level[0]:g}",
                "reference": "daily close",
                "source_phrase": level[1],
            }
        elif pullback:
            # "回踩 X 附近可以买" — a pullback entry is conditional on touching X,
            # which on daily bars is a close at or below the level.
            entry_trigger = {
                "type": "price_condition",
                "expr": f"close <= {float(pullback.group(1)):g}",
                "reference": "daily close",
                "source_phrase": pullback.group(0),
            }
            notes.append({"field": "entry_trigger", "issue": "pullback entry: fills only if price returns to the stated level"})
        elif levels["down"]:
            notes.append(
                {
                    "field": "entry_trigger",
                    "issue": "long view states only a downside level; treated as pullback/invalidation, not entry",
                }
            )
    elif direction == "short":
        level = levels["down"]
        if level:
            entry_trigger = {
                "type": "price_condition",
                "expr": f"close < {level[0]:g}",
                "reference": "daily close",
                "source_phrase": level[1],
            }
        elif pullback:
            entry_trigger = {
                "type": "price_condition",
                "expr": f"close >= {float(pullback.group(1)):g}",
                "reference": "daily close",
                "source_phrase": pullback.group(0),
            }
            notes.append({"field": "entry_trigger", "issue": "rebound entry: fills only if price returns to the stated level"})
        elif levels["up"]:
            notes.append(
                {
                    "field": "entry_trigger",
                    "issue": "short view states only an upside level; treated as rebound/invalidation, not entry",
                }
            )

    if entry_trigger is None and direction in ("long", "short"):
        entry_trigger = {
            "type": "market",
            "expr": "market_on_next_open",
            "reference": "next bar open after published_at",
            "source_phrase": None,
        }
        notes.append({"field": "entry_trigger", "issue": "no trigger condition stated; defaulted to market entry"})

    stop_loss = None
    if levels["stop"]:
        cmp_op = "<" if direction != "short" else ">"
        stop_loss = {
            "type": "price_condition",
            "expr": f"close {cmp_op} {levels['stop'][0]:g}",
            "reference": "daily close",
            "source_phrase": levels["stop"][1],
        }
    elif direction == "long" and levels["down"]:
        stop_loss = {
            "type": "price_condition",
            "expr": f"close < {levels['down'][0]:g}",
            "reference": "daily close",
            "source_phrase": levels["down"][1],
            "derived": True,
        }
        notes.append({"field": "stop_loss", "issue": "derived from the stated invalidation level"})
    elif direction == "short" and levels["up"]:
        stop_loss = {
            "type": "price_condition",
            "expr": f"close > {levels['up'][0]:g}",
            "reference": "daily close",
            "source_phrase": levels["up"][1],
            "derived": True,
        }
        notes.append({"field": "stop_loss", "issue": "derived from the stated invalidation level"})

    exit_rule = None
    target_up = levels["target_up"] or levels.get("target_any")
    target_down = levels["target_down"] or levels.get("target_any")
    if direction == "long" and target_up:
        exit_rule = {
            "type": "price_condition",
            "expr": f"close >= {target_up[0]:g}",
            "reference": "daily close",
            "source_phrase": target_up[1],
        }
    elif direction == "short" and target_down:
        exit_rule = {
            "type": "price_condition",
            "expr": f"close <= {target_down[0]:g}",
            "reference": "daily close",
            "source_phrase": target_down[1],
        }

    return {
        "rule_id": None,
        "schema_version": SCHEMA_VERSION,
        "source_text": sentence,
        "instrument": instrument,
        "instrument_inherited": inherited_instrument,
        "direction": direction,
        "direction_word": word,
        "direction_inferred": inferred,
        "entry_trigger": entry_trigger,
        "horizon": horizon,
        "horizon_inherited": inherited_horizon,
        "stop_loss": stop_loss,
        "exit_rule": exit_rule,
        "position_size": None,
        "invalidation": None,
        "ambiguity": notes,
    }


# ---------------------------------------------------------------------------
# 3. Decision
# ---------------------------------------------------------------------------
def assess(rule: Dict[str, Any], apply_defaults: bool = False,
           policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Classify ``testability`` and optionally apply the frozen policy."""
    policy = policy or DEFAULT_POLICY
    out = copy.deepcopy(rule)
    out["assumed"] = []
    missing = [f for f in ("instrument", "direction", "entry_trigger", "horizon",
                           "stop_loss", "exit_rule") if out[f] is None]

    if out["instrument"] is None or out["direction"] is None:
        out["missing_fields"] = missing
        out["testability"] = "none"
        out["reason"] = "no instrument or no direction — nothing to trade"
        return out

    if out["direction"] == "neutral":
        out["missing_fields"] = missing
        out["testability"] = "neutral"
        out["reason"] = "explicit neutral / stand-aside view; no position is the signal"
        return out

    # ``full`` is judged on what the TEXT pinned, never on what the policy filled.
    horizon_stated = "horizon" not in missing
    risk_stated = out["stop_loss"] is not None or out["exit_rule"] is not None
    out["missing_fields"] = missing

    if apply_defaults:
        if out["entry_trigger"] is None:
            out["entry_trigger"] = {
                "type": "market",
                "expr": "market_on_next_open",
                "reference": "next bar open after published_at",
                "source_phrase": None,
            }
            out["assumed"].append({"field": "entry_trigger", "value": policy["missing_entry"],
                                   "policy": policy["version"]})
        if out["horizon"] is None:
            out["horizon"] = copy.deepcopy(policy["missing_horizon"])
            out["assumed"].append({"field": "horizon", "value": policy["missing_horizon"],
                                   "policy": policy["version"]})
        if out["position_size"] is None:
            out["position_size"] = policy["missing_position_size"]
            out["assumed"].append({"field": "position_size", "value": policy["missing_position_size"],
                                   "policy": policy["version"]})

    if horizon_stated and risk_stated:
        out["testability"] = "full"
        out["reason"] = "all decision fields stated in the text"
    else:
        out["testability"] = "partial"
        gaps = []
        if not horizon_stated:
            gaps.append("horizon")
        if not risk_stated:
            gaps.append("stop_or_exit")
        out["reason"] = "tradable after the frozen policy fills: " + ", ".join(gaps)
    return out


def extract_document(doc: Dict[str, Any], apply_defaults: bool = False,
                     policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    text = doc["text"]
    context: Dict[str, Any] = {}
    rules: List[Dict[str, Any]] = []
    unruleable: List[Dict[str, Any]] = []

    for idx, sentence in enumerate(_split_sentences(text), start=1):
        rule = assess(extract_rule(sentence, context), apply_defaults=apply_defaults, policy=policy)
        rule["rule_id"] = f"{doc.get('id') or 'doc'}-r{idx:02d}"
        rule["published_at"] = doc.get("published_at")
        rule["source"] = doc.get("source")
        rule["source_document_text"] = text
        (rules if rule["testability"] != "none" else unruleable).append(rule)
        if rule["instrument"] is not None:
            context["instrument"] = rule["instrument"]
        if rule["horizon"] is not None:
            context["horizon"] = rule["horizon"]

    return {
        "document_id": doc.get("id"),
        "source": doc.get("source"),
        "published_at": doc.get("published_at"),
        "original_text": text,
        "rules": rules,
        "unruleable": unruleable,
        "counts": {
            "rules_total": len(rules),
            "rules_full": sum(1 for r in rules if r["testability"] == "full"),
            "rules_partial": sum(1 for r in rules if r["testability"] == "partial"),
            "rules_neutral": sum(1 for r in rules if r["testability"] == "neutral"),
            "unruleable": len(unruleable),
        },
    }


# ---------------------------------------------------------------------------
# 4. Composition
# ---------------------------------------------------------------------------
def _normalize_documents(input_data: Any) -> List[Dict[str, Any]]:
    if isinstance(input_data, str):
        docs = [{"text": input_data}]
    elif isinstance(input_data, dict) and "documents" in input_data:
        docs = input_data["documents"]
    elif isinstance(input_data, dict):
        docs = [input_data]
    else:
        docs = list(input_data)
    out = []
    for i, doc in enumerate(docs):
        if isinstance(doc, str):
            doc = {"text": doc}
        doc = dict(doc)
        doc.setdefault("id", f"doc{i + 1:03d}")
        out.append(doc)
    return out


def frozen_config(apply_defaults: bool, policy: Dict[str, Any]) -> Dict[str, Any]:
    """The exact config that ``config_hash`` covers."""
    return {"apply_defaults": apply_defaults, "policy": policy, "extractor": f"rule-based-{VERSION}"}


def run(input_data: Any, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Main entrypoint.

    Args:
        input_data: a string, one document dict, a list of documents, or
            ``{"documents": [...]}``.
        config: ``{"apply_defaults": bool, "policy": dict, "document_id_prefix": str}``

    Returns:
        ``{"documents": [...], "summary": {...}, "config": {...}, "config_hash": str}``
    """
    validate_input(input_data)
    config = config or {}
    apply_defaults = bool(config.get("apply_defaults", False))
    policy = config.get("policy") or DEFAULT_POLICY
    frozen = frozen_config(apply_defaults, policy)

    documents = [
        extract_document(doc, apply_defaults=apply_defaults, policy=policy)
        for doc in _normalize_documents(input_data)
    ]

    total = sum(d["counts"]["rules_total"] for d in documents)
    unruleable = sum(d["counts"]["unruleable"] for d in documents)
    summary = {
        "documents": len(documents),
        "rules_total": total,
        "rules_full": sum(d["counts"]["rules_full"] for d in documents),
        "rules_partial": sum(d["counts"]["rules_partial"] for d in documents),
        "rules_neutral": sum(d["counts"]["rules_neutral"] for d in documents),
        "unruleable": unruleable,
        "ruleable_share": round(total / (total + unruleable), 4) if (total + unruleable) else 0.0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": VERSION,
        "documents": documents,
        "summary": summary,
        "config": frozen,
        "config_hash": hashlib.sha256(
            json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
    }


def print_rules(result: Dict[str, Any]) -> None:
    for doc in result["documents"]:
        print(f"=== {doc['document_id']}  published_at={doc['published_at']}  source={doc['source']}")
        print(f"    original: {doc['original_text']}")
        for r in doc["rules"]:
            inst = r["instrument"]
            print(
                f"  [{r['rule_id']}] {r['testability']:<7} "
                f"{inst['symbol'] if inst else '-':<7} {str(r['direction']):<7} "
                f"entry={r['entry_trigger']['expr'] if r['entry_trigger'] else '-':<20} "
                f"horizon={r['horizon']['value'] if r['horizon'] else '-':>2}d "
                f"stop={r['stop_loss']['expr'] if r['stop_loss'] else '-':<14} "
                f"exit={r['exit_rule']['expr'] if r['exit_rule'] else '-'}"
            )
            for m in r["missing_fields"]:
                print(f"        missing: {m}")
            for a in r["ambiguity"]:
                print(f"        ambiguity[{a['field']}]: {a['issue']}")
        for u in doc["unruleable"]:
            print(f"  [{u['rule_id']}] DROPPED  {u['reason']}  «{u['source_text']}»")
    s = result["summary"]
    print(
        f"\nsummary: docs={s['documents']} rules={s['rules_total']} "
        f"full={s['rules_full']} partial={s['rules_partial']} neutral={s['rules_neutral']} "
        f"unruleable={s['unruleable']} ruleable_share={s['ruleable_share']}"
    )
    print(f"config_hash: {result['config_hash']}")


if __name__ == "__main__":
    demo = {
        "documents": [
            {
                "id": "demo-1",
                "source": "demo",
                "published_at": "2024-05-06T08:30:00+08:00",
                "text": (
                    "螺纹钢主力如果站稳3800，我认为未来两周有望上冲4000，跌破3700则看错了。"
                    "铁矿石短线看空，跌破850继续下行，止损900。"
                    "明年大宗商品整体环境应该会比今年好。"
                    "豆粕暂时观望。"
                ),
            }
        ]
    }
    print_rules(run(demo, {"apply_defaults": True}))