---
name: skill-opinion-to-ruler
description: 当需要把一段主观交易观点转成可回测、可检验的交易规则时，使用此 skill。抽取标的/方向/触发/期限/止损/止盈六字段，标注样本校验抽取准确率，并按冻结基线做成本后评估。
tags: [quant, alpha, opinion, rule-extraction, backtest]
---

# 主观观点转可检验规则（Opinion to Ruler）

## 工具定位

- 工具类型：规则抽取 + 评估型
- 解决问题：一段主观交易观点（文章、评论、讲话）里通常混着标的、方向、价格条件、期限、失效条件。本 skill 把这些**逐条**压成可判定字段，用人工标注样本验收抽取质量，再把这些规则当成交易假设做成本后评估。
- 使用对象：研究者、Alpha 开发者、交易 agent 的上游信号处理

## 它不是什么

- **不是**情感打分器：不输出「看多强度 0.73」这类聚合情绪代理。
- **不是**文章摘要器：摘要不算完成。
- **不是**只统计方向命中率：方向对但规则不可执行，不算完成。

判断完成的标准是「六个字段是否可判定」，而不是「读起来像不像看多」。

## 六个必填字段

| 字段 | 含义 | 不可判定时的处理 |
|---|---|---|
| `instrument` | 标的，映射到品种代码 | 文本没提且上文无指代 → `testability=none` |
| `direction` | `long` / `short` / `neutral` | 只有价位、无多空措辞时可从**目标位**推断并标记 |
| `entry_trigger` | 进场条件，价格表达式或市价 | 无则默认 `market_on_next_open`（记入 `assumed`） |
| `horizon` | 期限，交易日 + 到期动作 | 无则按冻结策略 5 个交易日 |
| `stop_loss` | 止损条件 | 无则 `null`，**不臆造** |
| `exit_rule` | 止盈 / 条件退出 | 无则持有到期 |

## 判定分类

| `testability` | 含义 |
|---|---|
| `full` | 文本自身给出了期限，且至少给出止损或止盈 |
| `partial` | 可交易，但文本缺期限或缺风险出口，由冻结策略补齐 |
| `neutral` | 明确观望/不参与；「不建仓」本身就是信号 |
| `none` | 无标的或无方向，无法交易；单独统计，不参与回测 |

`full` 只由**文本自身**决定，不由默认策略补齐后改写。这样标注才能区分「作者说清楚了」和「我们替他说了」。

## 输入

```python
{
    "documents": [
        {
            "id": "op-001",                              # 可选，缺省 doc001
            "source": "某来源",                           # 可选
            "published_at": "2024-01-05T08:30:00+08:00", # 回测必需，无则拒跑
            "text": "螺纹钢主力站稳3850，未来两周上冲4100，跌破3780止损。"
        }
    ]
}
```

也接受单个字符串、单个文档 dict、文档 list。

## 输出

```python
{
  "schema_version": "rule-v1",
  "documents": [{
      "document_id": "op-001",
      "published_at": "...",
      "original_text": "...",           # 保留原文，不改写
      "rules": [{
          "rule_id": "op-001-r01",
          "instrument": {"raw": "螺纹钢", "symbol": "RB", "exchange": "SHFE",
                         "contract": "main", "mapping_rule": "alias_to_continuous_main"},
          "direction": "long",
          "direction_inferred": false,
          "entry_trigger": {"type": "price_condition", "expr": "close > 3850",
                            "reference": "daily close", "source_phrase": "站稳3850"},
          "horizon": {"value": 10, "unit": "trading_day", "expiry_action": "force_close"},
          "stop_loss": {"type": "price_condition", "expr": "close < 3780"},
          "exit_rule": {"type": "price_condition", "expr": "close >= 4100"},
          "position_size": null,
          "missing_fields": ["position_size"],
          "ambiguity": [{"field": "direction", "issue": "..."}],
          "assumed": [],
          "testability": "full"
      }],
      "unruleable": [ ... ],
      "counts": {"rules_total": 1, "rules_full": 1, "rules_partial": 0,
                 "rules_neutral": 0, "unruleable": 0}
  }],
  "summary": {"documents": 1, "rules_total": 1, "rules_full": 1, "rules_partial": 0,
              "rules_neutral": 0, "unruleable": 0, "ruleable_share": 1.0},
  "config": {...},
  "config_hash": "ef9de697..."
}
```

## 调用方式

```bash
python3 scripts/build.py                          # 内置示例
python3 scripts/annotate.py tests/fixtures/labels.json   # 标注评分
python3 scripts/evaluate.py --fixture             # 离线验收（CSV bars）
python3 scripts/evaluate.py --panda --start 20240101 --end 20241231
python3 -m pytest tests/ -v
```

```python
import sys; sys.path.insert(0, "scripts")
from build import run
result = run({"text": "铁矿石短线看空，跌破840，止损880。",
              "published_at": "2024-01-08T08:30:00+08:00"})
```

```python
from backtest import evaluate, value_assessment
bt = evaluate(rules, {"RB": bars}, baseline="hold")
print(bt["verdict"], bt["edge"])
```

## 评估设计

- **基线**：`hold`（同标的、同起止日买入持有）为默认；`cash`（零收益）可选。比较是**配对**的，同一笔规则的进出日期上取基线收益，把市场漂移从差值里扣掉。
- **成本**：默认手续费 3bp + 滑点 2bp，双边计。成本参数写进报告。
- **无未来函数**：只使用 `published_at` **严格之后**的 bar；`published_at` 缺失时拒绝模拟而不是猜。
- **判定**：`positive` / `negative` / `inconclusive` 由 `decide_verdict` 按固定阈值给出（≥12 笔且 bootstrap CI 不含 0），不依赖主观判断。

## 输出结果（结果型）

`output/frozen_baseline.json` 由 `evaluate.py` 写出，已加入 `.gitignore`。字段：

| 字段 | 说明 |
|---|---|
| `generated_at` | UTC 生成时间 |
| `data_mode` | `fixture` / `panda` |
| `extraction.accuracy` | 逐字段 precision / recall / exact-match |
| `backtest.metrics` | 笔数、胜率、均值净收益、Sharpe、最大回撤、退出原因分布 |
| `backtest.edge` | 配对 edge 的均值与 bootstrap CI |
| `backtest.verdict` | 三值判定 |
| `value_assessment` | 改变了什么决策、作用多大 |
| `applicability` | 覆盖范围、不在范围、结论失效条件 |

## 验收要求

- 抽取在标注样本上逐字段给出 precision / recall，不许只报一个总准确率
- 标注样本必须包含沉默（观望）、反转（否定词）、错误观点，不能只留命中样本
- 回测必须有冻结基线、成本假设、配对比较
- `verdict` 为 `negative` 或 `inconclusive` 同样算合格交付
- `tests/` 全部通过

## 数据来源

生产通道为 `panda_data`（`get_future_dominant` / `get_future_daily`），凭证只从环境变量读取：

```bash
export PANDA_DATA_USERNAME=<your_username>
export PANDA_DATA_PASSWORD=<your_password>
```

未配置凭证或不希望联网时，用 `--fixture` 读取 `tests/fixtures/bars_*.csv`。两条通道产出的 bar 结构一致，`load_bars` 明确回报 `source`，不会静默降级。

## 已知局限

- **A股个股不在覆盖范围内**。品种白名单只含内盘商品与股指期货；`中科星图`、`寒武纪` 这类股票名无法映射到代码，规则会被判 `none`（抽取本身正确，缺的是标的）。A股需要独立的代码索引与 T+1 / 涨跌停 / 停牌 / 100股整手 的回测层，不能复用期货的日线逻辑。
- 抽取是**规则/词典**实现，不是 LLM 调用；支持中文与英文（可混写）。覆盖的是内盘商品/股指期货常见表述，生僻比喻、反讽、长距离指代会落到 `none` 或产生 `ambiguity` 记录。
- 英文匹配按词边界，`long` 不会命中 `longer`；但同一句里多空措辞并存时仍会记为歧义，需要人工复核。
- 词典是显式白名单。新增表述（含其他语言或新品种）需改 `scripts/common.py`，不改逻辑。
- 品种别名表是白名单；表外品种无法映射，直接记为不可规则化而不是猜。
- 回测为日线收盘口径，不建模盘中触发、涨跌停无法成交、流动性冲击。
- 多条规则同时成立时不建模组合层面的资金竞争，逐条独立评估。
- 报告里的收益是历史回放结果，不代表未来表现。

## 可被 Alpha 调用

- 是
- 调用限制：调用方必须提供 `published_at`，否则该文档的规则会在回测阶段被跳过；`testability=none` 的条目应作为「该来源信息量不足」的统计项保留，不要丢弃。