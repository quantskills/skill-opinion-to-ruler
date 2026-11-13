# 验收口径（validation）

本文规定什么算「做完了」，以及每一条如何被机器检查。所有检查都能在 `tests/` 或 `evaluate.py` 里复现。

## 一、任务核心完成条件

| 条件 | 机器检查 | 位置 |
|---|---|---|
| 保留原观点与发布时间 | `original_text` 与输入逐字相同；`published_at` 原样透传 | `test_no_invented_fields`, `extract_document` |
| 事先固定标的、方向、期限、触发/退出 | 六字段结构 + `DEFAULT_POLICY` 冻结 + `config_hash` | `test_config_hash_is_stable`, `test_config_hash_changes_with_policy` |
| 人工标注样本检验抽取准确率 | 逐字段 precision / recall / exact-match | `scripts/annotate.py`, `test_labelled_sample_scores_perfectly` |
| 对照简单基线的成本后结果 | 配对 `hold` 基线 + 成本参数 | `test_baseline_hold_is_paired`, `test_costs_reduce_return` |

## 二、数据前提

| 前提 | 实现 |
|---|---|
| 合法可用且有时间戳的历史观点 | 输入契约要求 `published_at`；回测缺它就拒跑 |
| 对应行情 | `load_bars`，panda_data 或 CSV |
| 费用 | `config` 内的 `commission_bps` / `slippage_bps`，默认 3bp + 2bp 双边 |
| 覆盖沉默/反转/错误观点 | 标注样本必须包含 `neutral`、否定翻转、以及事后被证明错误的观点 |
| 语言覆盖 | 中文与英文各一份标注集（`labels.json` / `labels_en.json`），均需 exact-match 1.00 |

「错误观点」的检查方式：标注文件里应存在方向最终被行情证伪的样本。当前 fixture 的 16 条样本中，`op-002`、`op-008`、`op-009`、`op-012`、`op-015` 均以空头规则入场并在单边上涨区间运行，属于被证伪的一类；`op-005`、`op-016` 是沉默样本；`op-004` 是否定词反转样本。

## 三、新增研究与去重（相对 Q14）

| Q14 做法 | 本题做法 | 机器可见差异 |
|---|---|---|
| 聚合成一个情绪代理 | 逐条观点拆成规则，每条独立回测 | 输出是 `rules[]` 而非单一 score |
| 只统计方向命中率 | 六个可判定字段 + 成本后配对收益 | `backtest.trades[].edge` |
| 只保留命中样本 | 沉默/反转/错误全部保留并分类计数 | `unruleable`、`rules_neutral` 独立统计 |

因此「只总结文章」或「只统计方向命中率」在结构上就无法通过验收：前者产不出 `rules[]`，后者产不出 `trades[].edge`。

## 四、交付要求

| 要求 | 状态 |
|---|---|
| 可复跑的 skill | `python3 scripts/evaluate.py --fixture` 一条命令跑完 |
| 环境与数据说明 | `README.md` + `references/api_guide.md` |
| 冻结基线对照 | `output/frozen_baseline.json`，`config_hash` 保证可比性 |
| 输入输出索引 | `references/schema.md` 全字段表 |
| 使用及失败边界 | `SKILL.md`「已知局限」+ `applicability` |
| 交易执行部分可核验 | 日线回放；品种/接口不支持时写入 `out_of_scope` |

## 五、价值验收

`value_assessment` 必须回答三问：

| 问题 | 字段 |
|---|---|
| 改变了什么交易决策 | `decisions_created` + `decision_change_examples`（规则 vs 持有） |
| 作用多大 | `effect_size.mean_paired_edge` + CI + 笔数 + Sharpe + 最大回撤 |
| 适用边界 | `applicability.in_scope` / `out_of_scope` / `fails_when` |

判定规则固定、可复现：

```python
def decide_verdict(edge, trades, min_trades=12):
    if trades < min_trades:
        return "inconclusive"
    if edge["mean"] > 0 and edge["lo"] > 0:
        return "positive"
    if edge["mean"] <= 0 and edge["hi"] < 0:
        return "negative"
    if edge["mean"] <= 0:
        return "negative" if edge["hi"] <= 0 else "inconclusive"
    return "inconclusive"
```

**负结果同样是合格交付。** `verdict=negative` 只需满足样本量门槛与 `config_hash` 可比，不被判为不合格。

## 六、无未来函数

| 检查 | 实现 |
|---|---|
| 只用发布之后的 bar | `_bars_after` 严格 `>` 比较 |
| 成交在下一根开盘 | `fill_idx = entry_idx + 1` |
| 无 `published_at` 即停 | `simulate_rule` 返回 `skipped`，`_bars_after` 抛异常 |

对应测试：`test_no_look_ahead_requires_published_at`、`test_trade_never_starts_before_publish_date`。

## 七、复现命令

```bash
cd skill-opinion-to-ruler
python3 scripts/build.py
python3 scripts/annotate.py tests/fixtures/labels.json
python3 scripts/annotate.py tests/fixtures/labels_en.json
python3 scripts/evaluate.py --fixture
python3 -m pytest tests/ -v
```

四条命令全部成功，且 `evaluate.py` 报告里 `verdict` 有值、`applicability` 非空，即视为通过验收。

## 八、不合格情形

- 只输出文章摘要或情绪分数，没有六字段规则
- 只统计方向命中率，没有成本后收益
- 丢弃或未统计不可规则化条目
- 用文章发布之后的行情「补全」或修正观点
- 回测使用未来数据，或缺失 `published_at` 仍强行回测
- 标注样本只保留命中项
- 报告缺少基线对照、成本假设或适用边界
- 声称正向结论但样本量低于门槛且未标 `inconclusive`