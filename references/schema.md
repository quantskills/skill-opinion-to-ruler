# 字段契约（rule-v1）

本文是 `scripts/build.py` 输出结构的权威说明。任何字段变更都要同时更新本文件、`SKILL.md` 与 `config_hash` 的计算口径。

## 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | str | `rule-v1`，破坏性变更时递增 |
| `extractor_version` | str | 抽取器版本，当前 `0.1.0` |
| `documents` | list | 每个输入文档一项 |
| `summary` | dict | 全局计数与 `ruleable_share` |
| `config` | dict | 本 run 实际生效的配置 |
| `config_hash` | str | `config` 的 sha256，用于判定两次运行是否可比 |

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
| `rule_id` | str | `{document_id}-r{序号}`，按句子顺序编号 |
| `source_text` | str | 该规则来自的原句 |
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
| `missing_fields` | list[str] | 文本未给出的决策字段 |
| `ambiguity` | list[{field, issue}] | 解析歧义，供标注判断 |
| `assumed` | list[{field, value, policy}] | 冻结策略补齐了什么 |
| `testability` | `full`/`partial`/`neutral`/`none` | 见下 |
| `reason` | str | 分类理由 |

### instrument

| 字段 | 说明 |
|---|---|
| `raw` | 文本中的原始称呼 |
| `symbol` | 品种代码，如 `RB`；具体合约时为 `RB2610` |
| `exchange` | `SHFE` / `DCE` / `CZCE` / `CFFEX` / `INE`，显式合约代码时为 null |
| `contract` | `main`（含主力/主连）/ `specific`（带月份）/ `unspecified` |
| `mapping_rule` | `alias_to_continuous_main` / `alias_to_symbol` / `explicit_contract_code` |

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
    "extractor": "rule-based-0.1.0",
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