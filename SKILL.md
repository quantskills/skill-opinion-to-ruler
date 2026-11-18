---
name: skill-opinion-to-ruler
description: 当需要把一段主观交易观点转成可回测、可检验的交易规则时，使用此 skill。抽取标的/方向/触发/期限/止损/止盈六字段，标注样本校验抽取准确率，并按冻结基线做成本后评估。
tags: [quant, alpha, opinion, rule-extraction, backtest]
---

## 前置检查（未通过就停：只报告缺什么，不加载后续流程）

本技能**不自行准备数据，也不自行准备模型**：行情来自宿主配置的 PandaData MCP，模型来自宿主。
执行任何流程之前按顺序确认下列各项，**任一不过即停止**，且只输出「缺什么 + 怎么补」，
不得产出任何数字、不得改用其他数据源、不得静默降级：

1. **MCP 会话**：`mcp__pandadata__auth_status` 须 `ok: true` 且 `reauth_required: false`。
   不过 → 告知用户打开 Settings → PandaData 点 Login；不重试登录、不索要密码。
2. **数据权限探针**：调一次最小 `get_trade_cal`（单个交易日）。返回
   `data_permission_required` → 停止并转述返回里的 message 与购买入口，不要换源重试。
3. **模型**：由宿主提供。本技能内**没有任何模型端点地址或密钥，也不读相关环境变量**
   （0.6.0 起整块删除）；需要真实主体时用 `trader=agent` 由宿主逐案例作答。
4. **解释器与依赖**：**脚本本身只用标准库**（`requirements.txt` 声明无三方依赖），
   取数落盘与评测都**不需要 pandas**。需要第三方包的只有**验收测试**：
   `python3 -c "import pytest"` 通过即可。
   本环境实测：默认 `python3` = 3.9.6，**没有 pytest**，所以测试必须显式走带 pytest 的
   解释器（`python3.11 -m pytest tests/ -q`）；`python3` 跑脚本本身是正常的。
   把 pandas 写成闸门，等于在一台按设计完全能跑的机器上报告"依赖缺失"。

另需确认**观点原文来源**（用户提供的文本/表格）已就位；原文缺失即停止，不得凭记忆补写观点。

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
| `direction` | `long` / `short` / `neutral` | 只有价位、无多空措辞时可从**目标位**推断并标记；**否定撤回**（`不再看多`）判 `neutral`，不判反向 |
| `entry_trigger` | 进场条件，价格表达式或市价 | 文本未提**且标的可映射**时，抽取阶段补 `market_on_next_open`，逐条记入 `assumed`（`stage=extraction`）；标的映射不到就**留空**，不给不可执行条目配一张市价单 |
| `horizon` | 期限，交易日 + 到期动作 | 抽取阶段留 `null`；5 个交易日冻结默认**只在** `apply_defaults=True` 时补（`evaluate.py` 会打开，故验收链路包含该补全） |
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

**否定不等于反向。** `不再看多`、`不建议参与`、`先不做` 落 `neutral`：作者撤回了观点，并没有
说出相反观点，替他建一笔空仓等于把沉默当成主张。同一句里若还有未被否定的多空措辞，按**陈述**
的那部分判方向，并把否定命中写进 `ambiguity` 交人工复核。

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
  "config_hash": "8f9058b5..."
}
```

## 调用方式

```bash
python3 scripts/build.py                          # 内置示例
python3 scripts/annotate.py tests/fixtures/labels.json   # 标注评分
python3 scripts/evaluate.py --fixture             # 离线验收（内置 CSV bars）
python3 scripts/mcp_landing.py --build            # 落盘载荷 → 本技能自有 CSV
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231
python3 scripts/compare_baseline.py               # 重跑夹具并逐字段核对 baselines/ 锚点（只读）
python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json
python3 -m pytest tests/ -v
```

验收锚点在 `baselines/`（入库），重新生成的产物在 `output/`（不入库）。
`compare_baseline.py` 不一致时打印「哪个字段变了 + 旧值→新值」并非 0 退出。

真实行情不经脚本联网：MCP 工具只能由 **agent** 调用，所以顺序固定为
agent 调 `mcp__pandadata__call_pandadata` → 把返回载荷**原样**写入
`tests/fixtures/raw/<method>__<label>.json` → `python3 scripts/mcp_landing.py --build`
（截断守卫在这一层）→ `evaluate.py --landed-dir` 只读构建出来的本地文件（契约见
`references/mcp-data.md`）。

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

`baselines/frozen_baseline.json` 是**随包发布的冻结参照**（验收锚点），`baselines/scope_declaration.json`
是它的范围声明副本；两者都入库，从 git 安装就能拿到。`evaluate.py` 每次运行把**重新生成的产物**写到
`output/`（仍在 `.gitignore` 里）——参照只有一个权威，产物不是第二个权威。字段：

| 字段 | 说明 |
|---|---|
| `generated_at` | UTC 生成时间 |
| `data_mode` | `fixture` / `landed` |
| `data` | 本次读了哪些本地文件：逐标的 `method`/`files`/`source_payloads`/请求与实际窗口、`partial_symbols`、`shrunk_symbols`、`skipped_symbols`、`all_complete`（`landed` 模式另记 `landed_dir` 与 `coverage_policy`） |
| `extraction.accuracy` | 逐字段 precision / recall / exact-match |
| `backtest.metrics` | 笔数、胜率、均值净收益、Sharpe、最大回撤、退出原因分布 |
| `backtest.edge` | 配对 edge 的均值与 bootstrap CI |
| `backtest.verdict` | 三值判定 |
| `value_assessment` | 改变了什么决策、作用多大 |
| `applicability` | 覆盖范围、不在范围、结论失效条件（**由本次运行的 `scope` 生成**，不是通用模板） |
| `scope_declaration` | 开跑前冻结的范围声明，含 `scope_hash`、声明品种、未映射规则 |
| `scope_verification` | 声明范围与实际成交范围的比对结果，`honoured=false` 时结论作废 |

## 验收要求

- 抽取在标注样本上逐字段给出 precision / recall，不许只报一个总准确率
- 满分必须与**样本量和置信下界**一起报（`samples_all_fields_correct_ci95_low`）。26 个样本
  全对，95% 下界也只有 ~0.87；只报 "accuracy 1.0" 是把小样本说成结论
- **策略默认值补上的字段单独计 `policy_default`**，不算读对：金标准说"文本没写"，
  抽取器写出 `market_on_next_open`，那是政策在批自己的作业
- 标注样本必须包含沉默（观望）、反转（否定词）、错误观点，不能只留命中样本
- 标注样本还必须覆盖**已修掉的坑**：百分比止损、裸品种代码、合约号、一句两标的、
  仓位管理动词、期权——漏掉一类，那类就会重新坏掉而测试全绿
- 回测必须有冻结基线、成本假设、配对比较
- 冻结基线必须**随包发布**（`baselines/`，不是 `.gitignore` 里的运行期目录），并且有一条会真失败的
  守卫把重跑结果与它逐字段比对（`tests/test_baseline_guard.py`）
- `verdict` 为 `negative` 或 `inconclusive` 同样算合格交付
- `tests/` 全部通过

## 价值验收

按规约四问逐条回答。**下列数字全部取自随包锚点 `baselines/frozen_baseline.json`**，
由 `tests/test_baseline_guard.py` 逐字段守住，文档里不另存第二份口径。

| 规约之问 | 当前回答 | 依据 |
|---|---|---|
| 相对冻结基线改变了什么 | 重跑与锚点逐字段一致；不一致时 `evaluate.py --check-baseline` 会点名变化的具体路径并非 0 退出 | `tests/test_baseline_guard.py` |
| 作用多大 | **仍不可判定，但已在真实行情上判定**。合成锚点：n=10 < `MIN_TRADES`=12，edge **-0.018527**，CI [-0.028301, -0.00856]。真实行情重跑（`baselines/rb-i-2024H1-real.json`，2024-01-02..06-28，品种 I+RB，234 行主力映射 + 320 行具体合约日线，`scope honoured` 无降级）：n=**12** 达标，edge **+0.012154**，CI [-0.004511, +0.028479] **跨 0** → `verdict=inconclusive` | 两份锚点 `backtest.edge` |
| 适用边界 | 期货模拟撮合 / 自带撮合器的竞赛口径，不含实盘；真实重跑仅覆盖 2024H1 与 I、RB 两品种；4 条失效情形见 `baselines/scope_declaration.json` 与「已知局限」 | 同上 |
| 价值验收结论 | **机制已在真实行情上跑通、价值仍未验收**（V=0.60） | — |

两条实测事实比结论本身更有用：

1. **`MIN_TRADES` 是必要不充分条件**：真实重跑把样本补到 n=12、门槛达标，`verdict` 依然是
   `inconclusive`——因为 CI 跨 0。达标 ≠ 有效应，别把"补够样本"当成"必出结论"。
2. **合成数据连符号都可能是错的**：同一套规则与撮合器，合成锚点 edge **-0.0185**（CI 不含 0，
   看起来像"负面效果已确立"），真实 2024H1 是 **+0.0122**。这正是 V 不给 synthetic 证据封顶的理由。

`inconclusive` 是**门槛与显著性判定**，不是效果判定。抬到 V=0.80 需要 CI 稳定不含 0：按 n=12 的
SE≈0.0084 粗估，需 n≈21 才有显著性余量（补齐 2024H2 约 n≈24，属临界；9 月底行情会改变效应本身）。
在此之前，任何"该观点规则有效/无效"的表述都无证据支撑。

## 数据来源

**脚本不联网、不要凭证。** MCP 工具只能由 agent 调用，Python 脚本调不到 MCP，所以在线取数
只有一条路，且是文件中介、单向的（契约见 `references/mcp-data.md`）：

```
① agent: mcp__pandadata__call_pandadata(method=get_future_daily / get_future_dominant, params=...)
② agent: 返回载荷原样写入 tests/fixtures/raw/<method>__<label>.json
③ python3 scripts/mcp_landing.py --build
     → tests/fixtures/landed/bars_<SYMBOL>.csv     (date,open,high,low,close,volume)
     → tests/fixtures/landed/dominant_<PRODUCT>.csv (date,contract)
     → tests/fixtures/landed/provenance.json
④ python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start ... --end ...  # 只读
```

- 实测签名：`get_future_daily(start_date, end_date, symbol?, fields?)`（parquet 通道，行身份列
  `symbol`）、`get_future_dominant(underlying_symbol?, start_date, end_date)`（JSON 通道，返回
  `date,symbol,trading_code,underlying_symbol`）。调用顺序固定：`auth_status` → `search_methods`
  → `get_method_doc` → `call_pandadata`。
- 主力换月与连续价拼接**仍在脚本里**（`data_loader._stitch_dominant`）：按日取主力合约、
  用该合约自身的未复权 bar 拼段；换月处保留基差跳空，`roll_count` 记录在案，已在
  `applicability` 声明。
- 构建端强制三件事：**校验全部先于写文件**（拒绝时不会留下半套 landed 目录）；parquet 通道的
  预览上限 2000 行、超出是静默截断，判据为载荷自身的 `truncated: true` 或
  `row_count < total_rows`，不完整默认拒绝（`payload_truncated`，退出码 3），只有显式
  `--allow-partial` 才放行，且 `provenance.json` 留下 `partial: true` + `partial_payloads`，
  报告里 `data.partial_symbols` 与 `data_quality_warning` 会标出来；请求区间未被文件覆盖时报
  `coverage_missing`，只有 `--coverage shrink` 才降级并在报告里记录缺口。JSON 通道返回完整
  数组、不带这些字段，**缺字段不算截断信号**；`preview_rows` 是请求参数，不是行数。
- `--fixture` 语义不变：读 `tests/fixtures/bars_*.csv` 这份**合成**样例，列结构与构建产物
  完全一致，所以两条路径可分辨、互不覆盖。`load_bars` 始终回报 `source`，不静默降级；
  声明了却没有文件可服务的标的进 `data.skipped_symbols`，不会悄悄从样本里消失。
- 覆盖不到时不要换厂商：未登录 → Settings → PandaData → Login；无权限 → 按返回的
  `message` 与购买页 https://www.pandaaiquant.com/ 处理，不要重试该方法（详见
  `references/mcp-data.md`）。

## 已知局限

- **A股个股不在覆盖范围内**。品种白名单只含内盘商品与股指期货；`中科星图`、`寒武纪` 这类股票名无法映射到代码，规则会被判 `none`（抽取本身正确，缺的是标的）。A股需要独立的代码索引与 T+1 / 涨跌停 / 停牌 / 100股整手 的回测层，不能复用期货的日线逻辑。
- 抽取是**规则/词典**实现，不是 LLM 调用；支持中文与英文（可混写）。覆盖的是内盘商品/股指期货常见表述，生僻比喻、反讽、长距离指代会落到 `none` 或产生 `ambiguity` 记录。
- 英文匹配按词边界，`long` 不会命中 `longer`；但同一句里多空措辞并存时仍会记为歧义，需要人工复核。
- 词典是显式白名单。新增表述（含其他语言或新品种）需改 `scripts/common.py`，不改逻辑。
- 品种别名表是白名单；表外品种无法映射，直接记为不可规则化而不是猜。
- 回测为日线收盘口径，不建模盘中触发、涨跌停无法成交、流动性冲击。
- 多条规则同时成立时不建模组合层面的资金竞争，逐条独立评估。
  **一句多标的会拆成多条规则**（`螺纹钢多头铁矿空头…` → RB 一条、I 一条），
  价位只在**自己那一段**里找，跨子句借价会造出一条永远打不到的止损。
- **期权与现货股票不在标的白名单内**。`50ETF购3月2500` 能识别出"这不是期货品种"，
  但映射不到代码，判 `none`（抽取正确，缺的是标的索引）。
- **仓位管理动词不是方向信号**。`减仓`、`平仓`、`加到三成仓` 描述已有持仓的增减，
  不生成新的多空信号；`三成仓` 这类比例落到 `position_size=null` + `missing_fields`。
- **百分比价位在当前契约下不可执行**。`止损3%` 不折算成绝对价——折算会造出一条
  第一天就触发的假止损。字段留 `null`，百分比记进 `percent_levels` 并写 `ambiguity`；
  要支持相对止损得先在撮合层实现相对价，而不是在抽取层猜。
- **单字别名不在白名单**：`铜`、`原油` 这类不会映射。裸代码 `RB`/`I`/`HC` 已支持，
  但纯英文语境里的单字母代码**刻意不认**（`I` 只在紧邻中文时才当铁矿），
  否则 "I think rebar looks cheap" 会变成一笔铁矿交易。
- 回测为日线收盘口径，不建模盘中触发、涨跌停无法成交、流动性冲击；`held_bars` 只到"天"，
  所以 `sharpe` 的年化按**逐笔口径** `sqrt(244 / mean(held_bars))` 算，并同时给出
  `sharpe_per_trade`——直接乘 `sqrt(244)` 是把"每年多少根日线"当成"每年多少笔交易"，
  旧版因此把 0.76 的逐笔比值报成了 11.85。
- 报告里的收益是历史回放结果，不代表未来表现。

## 可被 Alpha 调用

- 是
- 调用限制：调用方必须提供 `published_at`，否则该文档的规则会在回测阶段被跳过；`testability=none` 的条目应作为「该来源信息量不足」的统计项保留，不要丢弃。