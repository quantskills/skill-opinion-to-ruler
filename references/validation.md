# 验收口径（validation）

本文规定什么算「做完了」，以及每一条如何被机器检查。所有检查都能在 `tests/`、`evaluate.py`
或 `compare_baseline.py` 里复现，且全部只读本技能目录内的文件。

## 一、任务核心完成条件

| 条件 | 机器检查 | 位置 |
|---|---|---|
| 保留原观点与发布时间 | `original_text` 与输入逐字相同；`published_at` 原样透传 | `test_no_invented_fields`, `extract_document` |
| 事先固定标的、方向、期限、触发/退出 | 六字段结构 + `DEFAULT_POLICY` 冻结 + `config_hash` | `test_config_hash_is_stable`, `test_config_hash_changes_with_policy` |
| 人工标注样本检验抽取准确率 | 逐字段 precision / recall / exact-match，**并连样本量与 Clopper-Pearson 95% 下界一起报**；策略默认补上的槽位单列 `policy_default`，不计入"读对" | `scripts/annotate.py`, `test_labelled_sample_scores_perfectly`, `test_clopper_pearson_matches_a_known_value`, `test_policy_filled_field_is_not_scored_as_a_prediction` |
| 对照简单基线的成本后结果 | 配对 `hold` 基线 + 成本参数 | `test_baseline_hold_is_paired`, `test_costs_reduce_return` |
| 冻结基线随包发布且可核对 | 从确定性夹具重跑，与 `baselines/frozen_baseline.json` **逐字段判等**（浮点容差 5e-7，仅 `generated_at` 豁免）；不一致即结构化报错 + 非 0 退出 | `test_baseline_guard.py`（`test_the_fixture_run_reproduces_the_frozen_anchor` 及其负路径用例）, `scripts/compare_baseline.py` |

## 二、数据前提

| 前提 | 实现 |
|---|---|
| 合法可用且有时间戳的观点 | 输入契约要求 `published_at`；回测缺它就拒跑。随包 12 例的文本是 `opinions.json` 明确自述 synthetic 的合成夹具，真实的是 RB/I 行情；真实作者样本须由调用方另行提供 |
| 对应行情 | `load_bars`，读本技能 `tests/fixtures/landed/` 里由 MCP 载荷构建的 CSV，或调用方自备 CSV（脚本不联网、不要凭证） |
| 费用 | `config` 内的 `commission_bps` / `slippage_bps`，默认 3bp + 2bp 双边 |
| 覆盖沉默/反转/错误观点 | 标注样本必须包含 `neutral`（观望）、**否定撤回**（判 `neutral`，不是反向）、以及事后被证明错误的观点 |
| 覆盖**曾经坏掉的具体写法** | 百分比止损、裸品种代码、具体合约号、一句两标的、仓位管理动词、期权各至少一条；哪一类从样本里消失，那一类就会重新坏掉而测试全绿 |
| 语言覆盖 | 中文与英文各一份标注集（`labels.json` / `labels_en.json`），均需 exact-match 1.00 |

数据完整性同样是验收项，而不是"跑通就行"：

| 检查 | 报告字段 | 不合格判定 |
|---|---|---|
| 构建时放行了截断载荷（`--allow-partial`） | `data.partial_symbols`、逐标的 `partial_payloads` | 非空即不得作为正式结论发布 |
| 窗口未被完整覆盖 | `data.shrunk_symbols`、逐标的 `coverage_missing` / `missing_dates` | 降级必须在结论里声明 |
| 声明的标的根本没被服务 | `data.skipped_symbols`（带错误码） | 非空即样本小于声明，结论作废并重取数据 |

「错误观点」的检查方式：样本集里必须存在规则执行后**净收益为负**的条目，且这些条目不得从统计中剔除。

下面这张盈亏分布表来自 **0.4.0 之前的取数通道**在 2024 年真实行情（RB/I，242 根日线）上的那次运行，
照原样保留只为追溯历史，**不是当前结果**——该通道已在 0.4.0 移除，242 根日线这个规模也不可在
当前链路复现。当前可复现的真实行情结果在 `baselines/rb-i-2024H1-real.json`（2024-01-02..06-28，
RB/I 各 117 根拼接日线，n=12，edge +0.012154，CI 跨 0 → `inconclusive`）。
`tests/test_baseline_guard.py::test_real_anchor_reproduces_from_shipped_evidence` 从随包
`evidence/rb-i-2024H1/` 的派生行情、案例/规则/标签**无条件重跑并逐字段比对**；有原始载荷时，
`test_real_anchor_reproduces_from_the_raw_payloads` 再复核 `raw -> landed` 派生关系。完整步骤见
`references/mcp-data.md` 第 1 节（agent 取数 → 原样落盘 → `--build` → 评测）与第 5 节（截断守卫）。

历史那次运行的 12 笔成交盈亏分布：

| 类别 | 条数 | 规则 |
|---|---:|---|
| 亏损（观点被证伪） | 6 | `op-001 / op-003 / op-008 / op-010 / op-011 / op-013` |
| 盈利（观点命中） | 6 | `op-002 / op-004 / op-007 / op-009 / op-012 / op-015` |
| 沉默（明确观望） | 2 | `op-005`、`op-016`，判 `neutral`，不入回测 |
| 否定撤回 | 1 | `op-004`「不看空，站上900才算转多」：`不看空` 命中否定并记入 `ambiguity`，方向取**未被否定的** `转多` → `long`。否定本身**不翻符号**；只是否定词独立出现（`不再看多`）时判 `neutral` |
| 不可规则化 | 1 | `op-006`（宏观判断，无标的无方向） |

**注意**：这里统计的是**规则执行结果**，不是对观点正确性的外部认定。同一批样本在合成 fixture 行情下判定的盈亏分布不同（见 `README.md` 的 A/B 两表），所以"哪些是错误观点"依赖所选的行情区间与成交口径，必须随报告一起声明。

历史版本曾把 `op-002 / op-008 / op-009 / op-012 / op-015` 一律描述为"被证伪"，这是未核对实际成交结果的错误断言；上述表格已按真实回测输出更正。

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
| 冻结基线对照 | `baselines/frozen_baseline.json`：**随包发布的冻结参照**（入库，从 git 安装即得到），`config_hash` 保证可比性；重跑与它逐项比对由 `tests/test_baseline_guard.py` 与 `scripts/compare_baseline.py` 执行。`output/frozen_baseline.json` 只是同一次运行写出的**产物**，不是第二个权威 |
| 输入输出索引 | `references/schema.md` 全字段表 |
| 使用及失败边界 | `SKILL.md`「已知局限」+ `applicability` |
| 交易执行部分可核验 | 日线回放；**开跑前**生成范围声明冻结等价回放范围（本次运行的产物写 `output/scope_declaration.json`，随包发布的冻结副本在 `baselines/scope_declaration.json`），跑完由 `verify_scope` 比对 |

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

离线（内置合成行情，无需任何取数）：

```bash
cd skill-opinion-to-ruler
python3 scripts/build.py
python3 scripts/annotate.py tests/fixtures/labels.json
python3 scripts/annotate.py tests/fixtures/labels_en.json
python3 scripts/evaluate.py --fixture
python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json
python3 scripts/compare_baseline.py
python3.11 -m pytest tests/ -q     # 脚本只用标准库，跑测试才需要 pytest；本机 python3 没有
```

七条命令全部成功（`--check-baseline` 与 `compare_baseline.py` 都是**只读**核对，退出码必须为 0），
且 `evaluate.py` 报告里 `verdict` 有值、`applicability` 非空，即视为通过验收。
锚点核对是独立一条：把 `baselines/frozen_baseline.json` 里任一数字改一位，最后两条命令必须失败——
守卫写成"文件存在即通过"在本节就不成立。

真实行情（先由 agent 取数落盘，脚本不联网；顺序不可颠倒，见 `references/mcp-data.md` 第 1 节）：

```bash
python3 scripts/mcp_landing.py --verify    # 只读诊断：载荷齐不齐、有没有被截断
python3 scripts/mcp_landing.py --build     # 校验先于写文件；拒绝时不留半套产物
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231
```

## 八、不合格情形

- 只输出文章摘要或情绪分数，没有六字段规则
- 只统计方向命中率，没有成本后收益
- 丢弃或未统计不可规则化条目
- 用文章发布之后的行情「补全」或修正观点
- 回测使用未来数据，或缺失 `published_at` 仍强行回测
- 标注样本只保留命中项
- 报告缺少基线对照、成本假设或适用边界
- 把验收锚点放在 `.gitignore` 的运行期目录里（从 git 安装的人拿不到冻结基线，等于没有锚点）
- 守卫只检查基线文件"存在"，不逐字段比对重跑结果——这样的守卫改坏数字也照样绿
- 声称正向结论但样本量低于门槛且未标 `inconclusive`
- 小样本满分当成结论：26 条全对的 95% 置信下界只有 0.8677，必须与 `samples_all_fields_correct_ci95_low` 一起报
- 把策略默认补出来的槽位算成读对（金标准说"文本没写"，抽取器写 `market_on_next_open`，那是政策在批自己的作业）
- 把**逐笔收益**乘 `sqrt(244)` 报成 Sharpe：`244` 是每年日线根数，不是每年回合数。旧版合成锚点因此把 0.759 的逐笔比值报成 11.854（虚高 ~15.6 倍），年化必须用 `sqrt(244 / mean(held_bars))`，并同时给出 `sharpe_per_trade`
- 百分比价位折算成绝对价（`止损3%` → `close < 3` 会在进场当天就触发），或跨子句借价位（把铁矿 840 当螺纹钢的止损）
- 否定措辞被当成反向信号（`不再看多` → 建空仓是把沉默当成主张）
- 随包发布的锚点里写本机绝对路径：换一台机器、换一个安装位置，报告里的溯源就全部对不上
- 产物落点不可写就直接崩溃：算完所有数字却因为写不进包而没有任何输出
- 抽取器新输出的字段不写进 `references/schema.md` 的 rules[] 表（该表与实发对象由守卫双向比对）
- 放行了截断载荷（`data.partial_symbols` 非空）或缺腿降级（`data.shrunk_symbols` 非空）却当作完整数据出结论
- 声明的标的有未被服务者（`data.skipped_symbols` 非空）仍按原样本规模解读结果