"""Lexicons and deterministic parsers for skill-opinion-to-ruler.

Standard library only. Every mapping here is part of the public contract and is
documented in ``references/schema.md``; changing a lexicon changes
``config_hash`` and therefore invalidates comparability with earlier runs.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Instrument dictionary
# ---------------------------------------------------------------------------
# Longest / most specific names first: "螺纹钢" before "螺纹", "玉米淀粉" before
# "玉米". A bare single Chinese character is never matched implicitly.
INSTRUMENTS = [
    ("沪深300", "IF", "CFFEX"),
    ("上证50", "IH", "CFFEX"),
    ("中证500", "IC", "CFFEX"),
    ("中证1000", "IM", "CFFEX"),
    ("铁矿石", "I", "DCE"),
    ("螺纹钢", "RB", "SHFE"),
    ("热轧卷板", "HC", "SHFE"),
    ("热卷", "HC", "SHFE"),
    ("不锈钢", "SS", "SHFE"),
    ("玉米淀粉", "CS", "DCE"),
    ("棕榈油", "P", "DCE"),
    ("燃料油", "FU", "SHFE"),
    ("沪铜", "CU", "SHFE"),
    ("沪铝", "AL", "SHFE"),
    ("沪锌", "ZN", "SHFE"),
    ("沪镍", "NI", "SHFE"),
    ("沪铅", "PB", "SHFE"),
    ("沪锡", "SN", "SHFE"),
    ("沪金", "AU", "SHFE"),
    ("沪银", "AG", "SHFE"),
    ("硅铁", "SF", "CZCE"),
    ("锰硅", "SM", "CZCE"),
    ("螺纹", "RB", "SHFE"),
    ("铁矿", "I", "DCE"),
    ("黄金", "AU", "SHFE"),
    ("白银", "AG", "SHFE"),
    ("原油", "SC", "INE"),
    ("沥青", "BU", "SHFE"),
    ("豆粕", "M", "DCE"),
    ("豆油", "Y", "DCE"),
    ("菜粕", "RM", "CZCE"),
    ("菜油", "OI", "CZCE"),
    ("甲醇", "MA", "CZCE"),
    ("白糖", "SR", "CZCE"),
    ("棉花", "CF", "CZCE"),
    ("玻璃", "FG", "CZCE"),
    ("纯碱", "SA", "CZCE"),
    ("尿素", "UR", "CZCE"),
    ("焦炭", "J", "DCE"),
    ("焦煤", "JM", "DCE"),
    ("聚丙烯", "PP", "DCE"),
    ("塑料", "L", "DCE"),
    ("玉米", "C", "DCE"),
    ("淀粉", "CS", "DCE"),
    ("鸡蛋", "JD", "DCE"),
    ("苹果", "AP", "CZCE"),
    ("红枣", "CJ", "CZCE"),
    ("花生", "PK", "CZCE"),
    ("纸浆", "SP", "SHFE"),
    ("橡胶", "RU", "SHFE"),
    ("燃油", "FU", "SHFE"),
]

MAIN_PAT = re.compile(r"(主力|主连|连续)")

# ---------------------------------------------------------------------------
# Direction lexicon
# ---------------------------------------------------------------------------
LONG_WORDS = ["看多", "做多", "买入", "买进", "多单", "看涨", "偏多", "加多", "逢低买",
              "逢低做多", "试多", "转多", "买多"]
SHORT_WORDS = ["看空", "做空", "卖出", "卖空", "空单", "看跌", "偏空", "加空", "逢高卖",
               "逢高做空", "试空", "转空", "卖空"]
NEUTRAL_WORDS = ["观望", "中性", "不参与", "区间操作", "离场观望", "不追"]
NEGATIONS = ["不", "没有", "别", "并非", "不太", "未"]

# ---------------------------------------------------------------------------
# Horizon lexicon: pattern -> trading days
# ---------------------------------------------------------------------------
HORIZON_PATTERNS = [
    (r"(当天|当日|日内|今天|今日|隔夜)", 1),
    (r"(短线|短期)", 3),
    (r"(一天|1天|一个交易日|1个交易日)", 1),
    (r"(三天|3天|三个交易日|3个交易日)", 3),
    (r"(一周|1周|本周|下周|未来一周|一周内)", 5),
    (r"(两周|2周|半个月|未来两周)", 10),
    (r"(中线|中期)", 20),
    (r"(一个月|1个月|本月|未来一个月)", 20),
    (r"(一季度|一个季度|1个季度|三个月|3个月)", 60),
    (r"(长线|长期)", 60),
]

# ---------------------------------------------------------------------------
# Price levels
# ---------------------------------------------------------------------------
UP_KW = r"(?:站稳|站上|成功站上|突破|上破|上穿|收复|有效突破)"
DOWN_KW = r"(?:跌破|下破|失守|下穿|跌穿|击穿)"
TARGET_UP_KW = r"(?:目标(?:位|价)?|上看|看到|看至|看高至|上冲|冲击|有望到|有望上冲|有望涨至)"
TARGET_DOWN_KW = r"(?:下看|看向|看低至|下探|有望跌至|有望下探|有望跌到)"
STOP_KW = r"(?:止损|止损位|止损价)"
PULLBACK_KW = r"(?:回踩|回抽|回调|回落|回撤)"

NUM = r"(\d+(?:\.\d+)?)"
RANGE_SEP = r"(?:-|~|到|至|—)"

# Tokens that mark a sentence as referring to a price level rather than a date.
LEVEL_HINT = re.compile(r"(?:元|点|附近|上方|下方|以上|以下|之上|之下)")


def find_instrument(text):
    """Return ``{raw, symbol, exchange, contract, mapping_rule}`` or None."""
    for name, symbol, exchange in INSTRUMENTS:
        idx = text.find(name)
        if idx < 0:
            continue
        end = idx + len(name)
        # Guard against substring false positives inside a longer product name.
        longer = [n for n, _, _ in INSTRUMENTS if n != name and name in n]
        if any(n in text and n != name and idx >= text.find(n) and end <= text.find(n) + len(n) for n in longer):
            continue
        return _instrument_payload(name, symbol, exchange, text, end)

    m = re.search(r"\b([A-Z]{1,2})(\d{3,4})\b", text)
    if m:
        return {
            "raw": m.group(0),
            "symbol": m.group(0),
            "exchange": None,
            "contract": "specific",
            "mapping_rule": "explicit_contract_code",
        }
    return None


def _instrument_payload(raw, symbol, exchange, text, end):
    contract = "main" if MAIN_PAT.search(text) else "unspecified"
    tail = text[end:]
    month = re.match(r"\s*(\d{3,4})\b", tail)
    if month and not LEVEL_HINT.match(tail[month.end(): month.end() + 2] or ""):
        contract = "specific"
        symbol = f"{symbol}{month.group(1)}"
    return {
        "raw": raw,
        "symbol": symbol,
        "exchange": exchange,
        "contract": contract,
        "mapping_rule": "alias_to_continuous_main" if contract == "main" else "alias_to_symbol",
    }


def find_direction(text):
    """Return ``(direction, matched_word, negated)``.

    Explicit long/short words win. Negation directly before the word flips it.
    """
    for words, label in ((SHORT_WORDS, "short"), (LONG_WORDS, "long")):
        for word in words:
            idx = text.find(word)
            if idx < 0:
                continue
            prefix = text[max(0, idx - 3): idx]
            negated = any(prefix.endswith(neg) for neg in NEGATIONS)
            return label, word, negated
    for word in NEUTRAL_WORDS:
        if word in text:
            return "neutral", word, False
    return None, None, False


def find_horizon(text):
    for pat, days in HORIZON_PATTERNS:
        if re.search(pat, text):
            return {"value": days, "unit": "trading_day", "expiry_action": "force_close"}
    return None


def _first(patterns, text):
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return float(m.group(1)), m.group(0)
    return None


def parse_levels(text):
    """Extract price levels by role, independent of direction.

    Returns a dict with keys ``up``, ``down``, ``target_up``, ``target_down``,
    ``stop``; each value is ``(float, source_phrase)`` or None.
    """
    out = {
        "up": None,
        "down": None,
        "target_up": None,
        "target_down": None,
        "target_any": None,
        "stop": None,
    }

    up = _first([
        TARGET_UP_KW + r"\s*(?:在|到|至|位)?\s*" + NUM,
        NUM + r"\s*(?:目标位|目标价)",
        r"目标\s*" + NUM,
        r"上看\s*" + NUM,
    ], text)
    down = _first([
        TARGET_DOWN_KW + r"\s*(?:到|至|位)?\s*" + NUM,
        r"目标\s*" + NUM + r"\s*(?:下方|以下)",
    ], text)
    out["target_up"] = up
    out["target_down"] = down
    # A bare "目标 3700" is direction-neutral: it is attributed by the opinion's
    # direction in extract_rule(), never guessed here.
    out["target_any"] = _first([r"目标\s*(?:位|价)?\s*(?:在|到|至)?\s*" + NUM], text)

    out["up"] = _first([
        UP_KW + r"\s*(?:在|到|至|于)?\s*" + NUM,
        NUM + r"\s*(?:上方|以上|之上)",
        r"站上\s*" + NUM,
    ], text)
    out["down"] = _first([
        DOWN_KW + r"\s*(?:在|到|至|于)?\s*" + NUM,
        NUM + r"\s*(?:下方|以下|之下)",
    ], text)

    out["stop"] = _first([
        STOP_KW + r"\s*(?:位|价)?\s*(?:在|于|设|放到|放在|设在|放在)?\s*" + NUM,
        NUM + r"\s*(?:止损|作为止损)",
    ], text)
    return out


def clamp_text(text):
    return re.sub(r"\s+", " ", text).strip()