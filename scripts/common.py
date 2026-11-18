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
LONG_WORDS = ["看多", "做多", "买入", "买进", "多单", "多头", "看涨", "偏多", "加多", "逢低买",
              "逢低做多", "试多", "转多", "买多",
              "bullish", "long", "buy", "go long", "upside", "goes up", "higher",
    "上车",   # 进场俚语：中文交易语境里几乎只表示"跟进去做多头"
]
SHORT_WORDS = ["看空", "做空", "卖出", "卖空", "空单", "空头", "看跌", "偏空", "加空", "逢高卖",
               "逢高做空", "试空", "转空",
               "bearish", "short", "sell", "go short", "downside", "goes down", "lower"]
NEUTRAL_WORDS = ["观望", "中性", "不参与", "区间操作", "离场观望", "不追",
                 "不建议参与", "不建议", "暂不参与", "先不做", "等右侧确认",
                 "neutral", "stand aside", "stay out", "no position", "wait and see", "range-bound"]
NEGATIONS = ["不", "没有", "别", "并非", "不太", "未"]

# A negation does not have to sit flush against the direction word. ``不再看多``,
# ``不是看涨`` and ``不建议做多`` are all negated, yet ``prefix.endswith(neg)``
# misses them because an adverb (再/是/建议) intervenes — which silently kept
# ``螺纹钢不再看多`` as a *long* rule and sent it to the backtester on the wrong
# side. Match the tail of the prefix and allow up to three non-punctuation
# characters between the negator and the direction word. The window stops at
# punctuation, so ``不追。螺纹钢看多`` cannot leak a negation across a boundary.
CN_NEGATION_TAIL = re.compile(
    r"(?:没有|并非|不太|不再|不是|不建议|不宜|不应|不该|不要|不|别|未|勿|无)"
    r"[^\s，,。.;；]{0,3}$"
)

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

# ``看3850上方`` is a breakout trigger, not a 3850 target: the zone suffix makes
# the level a condition. Reading it as a target produced rules where entry and
# exit were the same number (``close > 3850`` and ``close >= 3850``), which the
# matcher then exits on the very bar it fills. Target patterns must reject a
# level that is followed by a zone suffix.
ZONE_SUFFIX = r"(?:上方|下方|以上|以下|之上|之下|附近|左右)"
ZONE_GUARD = r"(?!\s*%s|%s\s)" % (ZONE_SUFFIX, ZONE_SUFFIX)

# ``止损3%`` and ``止损 3.5 %`` state a *relative* level. They are not price
# levels, and a daily-close expression like ``close < 3`` would silently disable
# the stop on a 3850 instrument: the trade then rides to target and the loss the
# author planned to cap is reported as a win. Percentages are masked out of the
# level scan and reported as a separate, non-executable finding instead.
PERCENT_LEVEL = re.compile(r"(\d+(?:[.,]\d+)?)\s*[%％]")
PERCENT_GAP = re.compile(r"[%％]\s*(?:点|个百分点)?")

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
    return bool(CN_NEGATION_TAIL.search(prefix))


def direction_candidates(text: str):
    """Every explicit direction word as ``(start, label, word, negated)``."""
    found = []
    for words, label in ((LONG_WORDS, "long"), (SHORT_WORDS, "short")):
        for word in words:
            starts = list(_match_starts(text, word))
            if not starts:
                continue
            first = min(starts)
            found.append((first, label, word, _is_negated(text, first, word)))
    found.sort(key=lambda c: c[0])
    return found


def _has_word(text: str, word: str) -> bool:
    """True if ``word`` occurs; ASCII words must be whole words."""
    return next(_match_starts(text, word), None) is not None


def _product_index():
    """symbol -> exchange, first alias wins."""
    idx = {}
    for _name, _symbol, _exchange in INSTRUMENTS:
        idx.setdefault(_symbol, _exchange)
    return idx


PRODUCT_EXCHANGE = _product_index()

# The extractor has always *emitted* exchange codes (``symbol: "RB"``), but it
# could not *read* them: ``find_instrument`` only scanned the alias column, so
# ``RB看多，站上3850`` was dropped as "no instrument" while ``螺纹钢看多`` parsed
# fine. Codes are scanned case-sensitively with ASCII guards so ``If`` and
# ``longer`` cannot fire, and single-letter codes (I/M/P/Y/C/L/J) additionally
# require an adjacent CJK character — otherwise ``I think gold...`` would map to
# iron ore. ``IF`` is held to the same rule because it is an English word.
CJK_PAT = re.compile(r"[㐀-䶿一-鿿]")
SINGLE_LETTER_CODES = sorted([c for c in PRODUCT_EXCHANGE if len(c) == 1])
MULTI_LETTER_CODES = sorted([c for c in PRODUCT_EXCHANGE if len(c) >= 2],
                            key=len, reverse=True)
CODE_REQUIRING_CJK = {"IF"}
CONTRACT_CODE_PAT = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,2})(\d{3,4})(?![A-Za-z0-9])")
CLAUSE_PAT = re.compile(r"[，,、；;]")


def _alias_hits(text):
    """Occurrences of alias names as ``(start, end, payload)``, position sorted."""
    hits = []
    for name, symbol, exchange in INSTRUMENTS:
        for start in _match_starts(text, name):
            end = start + len(name)
            # Skip an occurrence that sits inside a longer alias for ANOTHER
            # product; same-symbol longer aliases are harmless (dedup keeps the
            # earliest occurrence anyway).
            shadowed = False
            for other, other_symbol, _ in INSTRUMENTS:
                if other_symbol == symbol or other == name or name not in other:
                    continue
                pos = text.find(other)
                if pos != -1 and pos <= start and end <= pos + len(other):
                    shadowed = True
                    break
            if shadowed:
                continue
            hits.append((start, end, _instrument_payload(name, symbol, exchange, text, end)))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    return hits


def _code_hits(text):
    """Occurrences of exchange codes / contract codes as ``(start, end, payload)``."""
    hits = []
    for m in CONTRACT_CODE_PAT.finditer(text):
        code = m.group(1)
        if code not in PRODUCT_EXCHANGE:
            continue
        payload = {
            "raw": m.group(0),
            "symbol": code,
            "exchange": PRODUCT_EXCHANGE[code],
            "contract": "specific",
            "contract_code": m.group(0),
            "mapping_rule": "contract_to_product",
        }
        hits.append((m.start(), m.end(), payload))
    if MULTI_LETTER_CODES:
        pat = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(MULTI_LETTER_CODES) +
                         r")(?![A-Za-z0-9])")
        for m in pat.finditer(text):
            code = m.group(1)
            if code in CODE_REQUIRING_CJK and not _has_cjk_neighbour(text, m.start(), m.end()):
                continue
            payload = _instrument_payload(code, code, PRODUCT_EXCHANGE[code], text, m.end())
            payload["mapping_rule"] = "code_to_continuous_main" \
                if payload["contract"] == "main" else "code_to_symbol"
            hits.append((m.start(), m.end(), payload))
    for code in SINGLE_LETTER_CODES:
        for m in re.finditer(r"(?<![A-Za-z0-9])" + code + r"(?![A-Za-z0-9])", text):
            if not _has_cjk_neighbour(text, m.start(), m.end()):
                continue
            payload = _instrument_payload(code, code, PRODUCT_EXCHANGE[code], text, m.end())
            payload["mapping_rule"] = "code_to_continuous_main" \
                if payload["contract"] == "main" else "code_to_symbol"
            hits.append((m.start(), m.end(), payload))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    return hits


def _has_cjk_neighbour(text, start, end):
    return bool(CJK_PAT.search(text[max(0, start - 1):start] or "") or
                 CJK_PAT.search(text[end:end + 1] or ""))


def instrument_hits(text):
    """Every instrument mention, aliases and codes together, in text order."""
    return sorted(_alias_hits(text) + _code_hits(text), key=lambda h: (h[0], -(h[1] - h[0])))


def find_instruments(text):
    """Instruments mentioned in ``text``, position ordered, one entry per symbol."""
    out = []
    seen = set()
    for _start, _end, payload in instrument_hits(text):
        sym = payload["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        out.append(payload)
    return out


def instrument_spans(text):
    """Split ``text`` into per-instrument spans.

    Chinese opinion text strings several products together inside one sentence,
    separated by commas: ``螺纹钢多头铁矿空头，RB看3850上方，I看840下方。`` A
    sentence-level level scan gives both products the same price pool, so the
    rebar rule picked up iron ore's 840 as its stop. This maps every clause to
    the instrument it speaks about: a clause that names two instruments is cut
    at each mention, and a clause that names none inherits the most recent one.

    Returns ``[(payload, span_text), ...]`` in first-mention order, or ``[]``
    when nothing is mapped (the caller then falls back to context inheritance).
    """
    hits = instrument_hits(text)
    if not hits:
        return []

    ranges = []
    pos = 0
    for m in CLAUSE_PAT.finditer(text):
        if m.start() > pos:
            ranges.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        ranges.append((pos, len(text)))

    groups, order, active = {}, [], None
    for c_start, c_end in ranges:
        clause_hits = [h for h in hits if h[0] >= c_start and h[1] <= c_end]
        if not clause_hits:
            if active is not None:
                groups[active].append((c_start, c_end))
            continue
        cut = c_start
        for i, (_h_start, _h_end, payload) in enumerate(clause_hits):
            nxt = clause_hits[i + 1][0] if i + 1 < len(clause_hits) else c_end
            sym = payload["symbol"]
            if sym not in groups:
                groups[sym] = []
                order.append(sym)
                groups[sym].append((max(c_start, _h_start - 0), nxt))
            else:
                groups[sym].append((cut, nxt) if _h_start >= cut else (_h_start, nxt))
            cut = nxt
            active = sym
        if cut < c_end:
            groups[active].append((cut, c_end))

    spans = []
    for sym in order:
        pieces = [text[s:e] for s, e in sorted(groups[sym])]
        spans.append((next(p for _s, _e, p in hits if p["symbol"] == sym),
                      "，".join(p.strip("，,、 ") for p in pieces if p.strip("，,、 "))))
    return spans


def find_percent_levels(text):
    """Relative (percentage) levels, which are not executable price levels."""
    out = []
    for m in PERCENT_LEVEL.finditer(text):
        before = text[max(0, m.start() - 14):m.start()]
        after = text[m.end():m.end() + 6]
        tail = r"[^，,。.;；\d]{0,8}$"
        if re.search(STOP_KW + tail, before):
            field = "stop_loss"
        elif re.search(r"(涨幅|上涨|上行|跌幅|下跌|下行)" + tail, after):
            field = "exit_rule"
        elif re.search(TARGET_UP_KW + tail, before) or re.search(TARGET_DOWN_KW + tail, before):
            field = "exit_rule"
        elif re.search(PULLBACK_KW + tail, before):
            field = "entry_trigger"
        elif re.search(UP_KW + tail, before) or re.search(DOWN_KW + tail, before):
            field = "entry_trigger"
        else:
            field = "price_level"
        out.append({"field": field,
                    "value": float(m.group(1).replace(",", ".")),
                    "phrase": m.group(0).strip()})
    return out


def mask_percent_levels(text):
    """Blank out ``3%``-style tokens so the level scan cannot read ``3`` as a price."""
    return PERCENT_LEVEL.sub(" ", text)


def find_instrument(text):
    """Return ``{raw, symbol, exchange, contract, mapping_rule}`` or None.

    The earliest mention in the text wins — alias names and exchange codes are
    merged into one position-ordered list, so ``螺纹钢...铁矿石`` maps to RB.
    """
    hits = instrument_hits(text)
    if hits:
        return hits[0][2]

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

    Position decides, not dictionary order: the earliest *unnegated* explicit
    word wins, so ``螺纹钢多头铁矿空头`` reads as long (what the author said
    about rebar) instead of whichever list happened to be scanned first.
    When every explicit word is negated the caller must not flip the sign —
    see ``_resolve_direction`` in build.py.
    """
    cands = direction_candidates(text)
    for _start, label, word, negated in cands:
        if not negated:
            return label, word, False
    if cands:
        _start, label, word, _neg = cands[0]
        return label, word, True
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
        TARGET_UP_KW + CONNECTOR + NUM + ZONE_GUARD,
        NUM + r"\s*(?:目标位|目标价)",
        r"目标\s*" + NUM + ZONE_GUARD,
        r"上看\s*" + NUM + ZONE_GUARD,
        # Bare "看 4100" / "看至4100": a target verb directly followed by a number.
        # ``看3850上方`` is excluded by the zone guard — it is a trigger, not a
        # target, and treating it as a target made entry and exit the same price.
        r"看(?:到|至|高至)?\s*" + NUM + ZONE_GUARD,
    ], text)
    down = _first([
        TARGET_DOWN_KW + CONNECTOR + NUM + ZONE_GUARD,
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