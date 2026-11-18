# 字段契约（rule-v1）

本文是 `scripts/build.py` 输出结构的权威说明。任何字段变更都要同时更新本文件、`SKILL.md` 与 `config_hash` 的计算口径。

## 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | str | `rule-v1`，破坏性变更时递增 |
| `extractor_version` | str | 抽取器版本，当前 `0.4.1`（`scripts/build.py` 的 `VERSION` 常量） |
| `documents` | list | 每个输入文档一项 |
| `summary` | dict | 全局计数与 `ruleable_share` |
| `config` | dict | 本 run 实际生效的配置 |
| `config_hash` | str | `config` 的 sha256，用于判定两次运行是否可比 |

> `extractor` 版本是**算法指纹**，不是发布号：它进了 `config_hash`，而 `baselines/frozen_baseline.json` 冻结的正是某个 `config_hash` 下的结果。升级技能版本（如 0.5.0→0.6.0）**不应**动 `build.py:VERSION`；动它等于改基线口径，需要一次显式的重冻结决策，否则 `compare` 会正确地拒绝解读 delta。

## documents[]

| 字段 | 类型 | 说明 |
|---|---|---|
| `document_id` | str | 输入 `id`，缺省为 `doc001` 形式 |
| `source` | str/null | 来源标识，原样透传 |
| `published_at` | str/null | ISO-8601，**回测必需** |
| `original_text` | str | 原文，不改写 |
| `rules` | list | `testability != none` 的规则 |
| `unruleable` | list | `testability == none` 的条目，字段结构与 `rules` 相同 |
| `counts` | dict | `rules_total` / `rules_full` / `rules_partial` / `rules_neutral` / `unruleable` |

## rules[]

| 字段 | 类型 | 说明 |
|---|---|---|
| `rule_id` | str | `{document_id}-r{序号}`，**按规则编号而不是按句子编号**：一句拆出两条时是 `-r01`、`-r02` |
| `source_text` | str | 该规则来自的原句（一句两标的时两条规则的该字段相同） |
| `schema_version` | str | 单条规则的契约版本，当前 `rule-v1` |
| `published_at` | str | 从文档透传，便于下游只拿一条规则也能知道发布时间 |
| `source` | str/null | 从文档透传的来源标识 |
| `source_document_text` | str | 整篇原文（`source_text` 是句子，这个是文档） |
| `instrument` | dict/null | 见下 |
| `instrument_inherited` | bool | 本句未提标的、从前面句子继承 |
| `direction` | `long`/`short`/`neutral`/null | 交易方向 |
| `direction_word` | str/null | 命中的措辞，便于人工复核 |
| `direction_inferred` | bool | 无多空措辞、由目标位推断 |
| `entry_trigger` | dict | 见下 |
| `horizon` | dict/null | `{value, unit:"trading_day", expiry_action:"force_close"}` |
| `horizon_inherited` | bool | 期限继承自前句 |
| `stop_loss` | dict/null | 结构同 `entry_trigger` |
| `exit_rule` | dict/null | 结构同 `entry_trigger` |
| `position_size` | null/str | 抽取阶段恒为 null；默认策略下为 `equal_weight_unit` |
| `invalidation` | null | 保留位 |
| `percent_levels` | list[{field, value, phrase}] | 文本里的**百分比**价位（如 `止损3%`）。`field` 指它本应属于哪个字段；这些值**不进** `expr`，因为日线收盘撮合无法执行相对价 |
| `missing_fields` | list[str] | 文本未给出的决策字段 |
| `ambiguity` | list[{field, issue}] | 解析歧义，供标注判断 |
| `assumed` | list[{field, value, policy, stage?}] | 冻结策略补齐了什么。`stage: "extraction"` 表示这条默认在**抽取阶段**就生效（进场条件），没有该键的是 `apply_defaults=True` 才补的（期限、仓位） |
| `testability` | `full`/`partial`/`neutral`/`none` | 见下 |
| `reason` | str | 分类理由 |

### instrument

| 字段 | 说明 |
|---|---|
| `raw` | 文本中的原始称呼 |
| `symbol` | **品种代码**，恒为 `RB`、`I` 这种可取数的品种层代码。具体合约写法（`RB2405`）也解析成 `RB`：合约号不是品种，把它当代码会让白名单校验永远对不上 |
| `contract_code` | str，仅 `contract == "specific"` 时存在，如 `RB2405`，保留作者点的那张合约 |
| `exchange` | `SHFE` / `DCE` / `CZCE` / `CFFEX` / `INE`。显式合约代码也解析得到交易所（由品种代码反查），不再留 null |
| `contract` | `main`（含主力/主连）/ `specific`（带月份）/ `unspecified`（只说品种名或裸代码） |
| `mapping_rule` | `alias_to_continuous_main`（品种名+主力）/ `alias_to_symbol`（品种名）/ `code_to_symbol`（裸代码 `RB`、`I`）/ `contract_to_product`（合约号 `RB2405`→`RB`）/ `context_inherited`（本句无标的，继承上文） |

### entry_trigger / stop_loss / exit_rule

| 字段 | 说明 |
|---|---|
| `type` | `price_condition` 或 `market` |
| `expr` | 可判定表达式，形如 `close > 3850`；市价进场为 `market_on_next_open` |
| `reference` | 判定基准，当前固定 `daily close` |
| `source_phrase` | 表达式来源的原句片段，便于追溯 |
| `derived` | 仅 `stop_loss` 可能出现，表示由失效位推导 |

## testability 判定

| 值 | 判据 |
|---|---|
| `none` | 缺 `instrument` 或 `direction` |
| `neutral` | `direction == "neutral"` |
| `full` | 文本自身含 `horizon`，且 `stop_loss` 或 `exit_rule` 至少其一 |
| `partial` | 有标的与方向，但文本缺期限或缺风险出口 |

`full` 只由文本自身决定。`apply_defaults` 补齐字段不会把 `partial` 提升为 `full`。

## config 与 config_hash

```python
config = {
    "apply_defaults": bool,
    "policy": {...},          # 见 DEFAULT_POLICY
    "extractor": "rule-based-0.4.1",
}
config_hash = sha256(json.dumps(config, sort_keys=True, ensure_ascii=False))
```

两次运行的 `config_hash` 不同，结果**不可比**。

## 冻结策略 DEFAULT_POLICY

| 键 | 值 | 说明 |
|---|---|---|
| `version` | `frozen-1` | 策略版本 |
| `missing_horizon` | 5 交易日，到期强平 | 文本未写期限时 |
| `missing_entry` | `market_on_next_open` | 文本未写触发时 |
| `missing_position_size` | `equal_weight_unit` | 文本未写仓位时 |
| `missing_stop` | null | **不补止损** |

## 回测交易记录

| 字段 | 说明 |
|---|---|
| `status` | `traded` / `skipped` |
| `entry_date` / `exit_date` | 严格晚于 `published_at` |
| `entry_price` / `exit_price` | 进场为下一根 bar 开盘价，出场为收盘价 |
| `held_bars` | 持有 bar 数 |
| `gross_return` | 未扣费收益（空头取负号） |
| `cost` | 双边手续费+滑点 |
| `net_return` | `gross_return - cost` |
| `baseline_return` | 同日期买入持有收益，`cash` 基线时为 0 |
| `edge` | `net_return - baseline_return` |
| `exit_reason` | `stop_loss` / `target` / `horizon` / `data_end` |

## summary

| 字段 | 说明 |
|---|---|
| `rules_total` | `rules_full + rules_partial + rules_neutral` |
| `unruleable` | 无法规则化的条目数 |
| `ruleable_share` | `rules_total / (rules_total + unruleable)` |