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
    # English aliases. ASCII names match on word boundaries, and lowercase
    # product words ("copper") are distinct from the uppercase contract codes.
    ("CSI 300", "IF", "CFFEX"),
    ("SSE 50", "IH", "CFFEX"),
    ("CSI 500", "IC", "CFFEX"),
    ("CSI 1000", "IM", "CFFEX"),
    ("rebar", "RB", "SHFE"),
    ("iron ore", "I", "DCE"),
    ("hot rolled coil", "HC", "SHFE"),
    ("hot-rolled coil", "HC", "SHFE"),
    ("stainless steel", "SS", "SHFE"),
    ("corn starch", "CS", "DCE"),
    ("palm oil", "P", "DCE"),
    ("fuel oil", "FU", "SHFE"),
    ("crude oil", "SC", "INE"),
    ("copper", "CU", "SHFE"),
    ("aluminum", "AL", "SHFE"),
    ("aluminium", "AL", "SHFE"),
    ("zinc", "ZN", "SHFE"),
    ("nickel", "NI", "SHFE"),
    ("lead", "PB", "SHFE"),
    ("tin", "SN", "SHFE"),
    ("gold", "AU", "SHFE"),
    ("silver", "AG", "SHFE"),
    ("bitumen", "BU", "SHFE"),
    ("asphalt", "BU", "SHFE"),
    ("soybean meal", "M", "DCE"),
    ("soybean oil", "Y", "DCE"),
    ("rapeseed meal", "RM", "CZCE"),
    ("rapeseed oil", "OI", "CZCE"),
    ("methanol", "MA", "CZCE"),
    ("sugar", "SR", "CZCE"),
    ("cotton", "CF", "CZCE"),
    ("glass", "FG", "CZCE"),
    ("soda ash", "SA", "CZCE"),
    ("urea", "UR", "CZCE"),
    ("coke", "J", "DCE"),
    ("coking coal", "JM", "DCE"),
    ("polypropylene", "PP", "DCE"),
    ("plastic", "L", "DCE"),
    ("corn", "C", "DCE"),
    ("egg", "JD", "DCE"),
    ("apple", "AP", "CZCE"),
    ("jujube", "CJ", "CZCE"),
    ("peanut", "PK", "CZCE"),
    ("ferrosilicon", "SF", "CZCE"),
    ("silicomanganese", "SM", "CZCE"),
    ("pulp", "SP", "SHFE"),
    ("rubber", "RU", "SHFE"),
]

MAIN_PAT = re.compile(r"(主力|主连|连续|dominant|front[- ]month|continuous)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Direction lexicon (Chinese + English)
# ---------------------------------------------------------------------------
LONG_WORDS = ["看多", "做多", "买入", "买进", "多单", "看涨", "偏多", "加多", "逢低买",
              "逢低做多", "试多", "转多", "买多",
              "bullish", "long", "buy", "go long", "upside", "goes up", "higher"]
SHORT_WORDS = ["看空", "做空", "卖出", "卖空", "空单", "看跌", "偏空", "加空", "逢高卖",
               "逢高做空", "试空", "转空",
               "bearish", "short", "sell", "go short", "downside", "goes down", "lower"]
NEUTRAL_WORDS = ["观望", "中性", "不参与", "区间操作", "离场观望", "不追",
                 "neutral", "stand aside", "stay out", "no position", "wait and see", "range-bound"]
NEGATIONS = ["不", "没有", "别", "并非", "不太", "未"]

# English negation is matched as a word just before the direction word.
EN_NEGATION_PAT = re.compile(
    r"\b(?:not|no|never|avoid|without|don't|doesn't|isn't|aren't|won't|no longer)\s+"
    r"(?:\w+\s+){0,2}$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Horizon lexicon: pattern -> trading days (Chinese + English)
# ---------------------------------------------------------------------------
HORIZON_PATTERNS = [
    (r"(当天|当日|日内|今天|今日|隔夜|\b(?:today|intraday|overnight)\b)", 1),
    (r"(短线|短期|\bshort[- ]term\b)", 3),
    (r"(一天|1天|一个交易日|1个交易日|\b(?:one|1|a)\s+day\b)", 1),
    (r"(三天|3天|三个交易日|3个交易日|\b(?:three|3)\s+days?\b)", 3),
    (r"(一周|1周|本周|下周|未来一周|一周内|\b(?:one|1|a)\s+week\b|\bthis week\b|\bnext week\b)", 5),
    (r"(两周|2周|半个月|未来两周|\b(?:two|2)\s+weeks?\b|\bfortnight\b)", 10),
    (r"(中线|中期|\bmedium[- ]term\b)", 20),
    (r"(一个月|1个月|本月|未来一个月|\b(?:one|1|a)\s+month\b|\bthis month\b|\bnext month\b)", 20),
    (r"(一季度|一个季度|1个季度|三个月|3个月|\b(?:one|1|a)\s+quarter\b|\bnext quarter\b|\b(?:three|3)\s+months?\b)", 60),
    (r"(长线|长期|\blong[- ]term\b)", 60),
]

# ---------------------------------------------------------------------------
# Price levels (Chinese + English)
# ---------------------------------------------------------------------------
UP_KW = (r"(?:站稳|站上|成功站上|突破|上破|上穿|收复|有效突破"
         r"|holds?(?:\s+above)?|breaks? above|breakout above|closes? above|reclaims?|clears?|above)")
DOWN_KW = (r"(?:跌破|下破|失守|下穿|跌穿|击穿"
           r"|breaks? below|closes? below|loses?|drops? below|falls? below|below)")
TARGET_UP_KW = (r"(?:目标(?:位|价)?|上看|看到|看至|看高至|上冲|冲击|有望到|有望上冲|有望涨至"
                r"|涨到|涨至|升至|升到|走高至|反弹至|反弹到"
                r"|targets?(?: of)?|targeting|upside to|sees?|eyes|looking for|up to|towards?|heads? to"
                r"|rises? to|rallies? to|climbs? to)")
TARGET_DOWN_KW = (r"(?:下看|看向|看低至|下探|有望跌至|有望下探|有望跌到"
                  r"|跌到|跌至|降至|降到|回落至|回调至"
                  r"|downside to|down to|falls? to|drops? to|slides? to)")
STOP_KW = r"(?:止损|止损位|止损价|stop[- ]?loss|stops?)"
PULLBACK_KW = (r"(?:回踩|回抽|回调|回落|回撤"
               r"|pullback|pull back|retrace(?:ment)?|dip|retreat)")

NUM = r"(\d+(?:\.\d+)?)"
RANGE_SEP = r"(?:-|~|到|至|—)"

# Tokens that mark a sentence as referring to a price level rather than a date.
LEVEL_HINT = re.compile(
    r"(?:元|点|附近|上方|下方|以上|以下|之上|之下|\bpts?\b|\bpoints?\b|\babove\b|\bbelow\b|\barea\b)",
    re.IGNORECASE,
)

# Connector words between a keyword and its number, e.g. "targets of 4100".
CONNECTOR = r"\s*(?:在|到|至|于|位|at|of|to|is|around|near|the)?\s*"


def _is_ascii(word: str) -> bool:
    return word.isascii()


def _match_starts(text: str, word: str):
    """Yield match start offsets. ASCII words match on word boundaries."""
    if _is_ascii(word):
        for m in re.finditer(r"\b" + re.escape(word) + r"\b", text, re.IGNORECASE):
            yield m.start()
    else:
        idx = text.find(word)
        while idx >= 0:
            yield idx
            idx = text.find(word, idx + 1)


def _is_negated(text: str, start: int, word: str) -> bool:
    prefix = text[max(0, start - 24):start]
    if _is_ascii(word):
        return bool(EN_NEGATION_PAT.search(prefix))
    return any(prefix.endswith(neg) for neg in NEGATIONS)


def _has_word(text: str, word: str) -> bool:
    """True if ``word`` occurs; ASCII words must be whole words."""
    return next(_match_starts(text, word), None) is not None


def find_instrument(text):
    """Return ``{raw, symbol, exchange, contract, mapping_rule}`` or None."""
    for name, symbol, exchange in INSTRUMENTS:
        starts = list(_match_starts(text, name))
        if not starts:
            continue
        start = starts[0]
        end = start + len(name)
        if _is_ascii(name):
            return _instrument_payload(name, symbol, exchange, text, end)
        # Guard against substring false positives inside a longer product name.
        longer = [n for n, _, _ in INSTRUMENTS if n != name and name in n]
        if any(n in text and n != name and start >= text.find(n) and end <= text.find(n) + len(n) for n in longer):
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
    English words match on word boundaries, so ``long`` does not fire inside
    ``longer`` and ``short`` does not fire inside ``shortage``.
    """
    for words, label in ((SHORT_WORDS, "short"), (LONG_WORDS, "long")):
        best = None
        for word in words:
            for start in _match_starts(text, word):
                if best is None or start < best[0]:
                    best = (start, word)
                break
        if best is not None:
            start, word = best
            return label, word, _is_negated(text, start, word)
    for word in NEUTRAL_WORDS:
        if next(_match_starts(text, word), None) is not None:
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
        TARGET_UP_KW + CONNECTOR + NUM,
        NUM + r"\s*(?:目标位|目标价)",
        r"目标\s*" + NUM,
        r"上看\s*" + NUM,
        # Bare "看 4100" / "看至4100": a target verb directly followed by a number.
        r"看(?:到|至|高至)?\s*" + NUM,
    ], text)
    down = _first([
        TARGET_DOWN_KW + CONNECTOR + NUM,
        r"目标\s*" + NUM + r"\s*(?:下方|以下)",
    ], text)
    out["target_up"] = up
    out["target_down"] = down
    # A bare "目标 3700" / "target 3700" is direction-neutral: it is attributed by
    # the opinion's direction in extract_rule(), never guessed here.
    out["target_any"] = _first([
        r"目标\s*(?:位|价)?\s*(?:在|到|至)?" + CONNECTOR + NUM,
        r"\btargets?\b" + CONNECTOR + NUM,
        r"\b(?:sees?|eyes?|looking for|upside to)\b" + CONNECTOR + NUM,
    ], text)

    out["up"] = _first([
        UP_KW + CONNECTOR + NUM,
        NUM + r"\s*(?:上方|以上|之上)",
        r"站上\s*" + NUM,
    ], text)
    out["down"] = _first([
        DOWN_KW + CONNECTOR + NUM,
        NUM + r"\s*(?:下方|以下|之下)",
    ], text)

    out["stop"] = _first([
        STOP_KW + r"\s*(?:位|价)?(?:\s*(?:在|于|设|放到|放在|设在))?" + CONNECTOR + NUM,
        NUM + r"\s*(?:止损|作为止损)",
        r"\bstop(?:s|ped)?\b[^.\d]{0,18}" + NUM,
    ], text)
    return out


def clamp_text(text):
    return re.sub(r"\s+", " ", text).strip()