# 主观观点转可检验规则

把一段主观交易观点（评论、日报、讲话）逐条转成**可回测的交易规则**，再用人工标注样本验收抽取质量，最后对照冻结基线做成本后评估。

这个 skill 关心的是「观点能不能变成可判定的规则」，不是「观点听起来多空」。

---

## 核心问题

一段典型的主观观点长这样：

> 螺纹钢主力如果站稳 3850，未来两周有望上冲 4100，跌破 3780 则看错了。

人读完能理解，但机器没法直接检验。要真正检验它，必须先把这句话压成六个可判定字段：

| 字段 | 这句话里的值 |
|---|---|
| 标的 | 螺纹钢 → `RB`（主力连续） |
| 方向 | 多（由目标位在上方推断，并标记为推断） |
| 进场触发 | `close > 3850` |
| 期限 | 两周 = 10 个交易日 |
| 止损 | `close < 3780` |
| 止盈 | `close >= 4100` |

六个字段齐了，这句话才从「看法」变成「假设」。

---

## 目录结构

```
skill-opinion-to-ruler/
├── SKILL.md
├── README.md / README.en.md
├── LICENSE / INSTALL.md / requirements.txt / skill.json / CHANGELOG.md
├── scripts/
│   ├── build.py         ← run() / validate_input() / 抽取四层
│   ├── common.py        ← 品种、方向、期限、价位词典与解析
│   ├── data_loader.py   ← 只读本地 bars：构建产物或调用方 CSV
│   ├── mcp_landing.py   ← 取数落点构建端（载荷解析 / 截断守卫 / provenance）
│   ├── backtest.py      ← 无未来函数回测 + 配对基线 + 判定
│   ├── annotate.py      ← 逐字段标注评分
│   ├── evaluate.py      ← 端到端验收与报告落盘
│   ├── scope.py           ← 开跑前冻结范围声明（等价回放口径，跑完不许改）
│   ├── contest_verify.py  ← 仿真大赛执行口径对账（只读落盘载荷，不下单）
│   └── compare_baseline.py ← 只读守卫：重跑结果逐项核对冻结锚点
├── baselines/           ← 冻结参照（验收锚点，随包发布、入库）
│   ├── frozen_baseline.json
│   ├── rb-i-2024H1-real.json
│   └── scope_declaration.json
├── evidence/rb-i-2024H1/ ← 原 12 例派生真实行情 + provenance + 案例/规则/标签（入库）
├── output/              ← 重新生成的落点（运行期产物，不入库）
├── tests/
│   ├── test_ruler.py          ← 113 个用例（抽取 / 回测 / 范围）
│   ├── test_mcp_landing.py    ← 39 个用例（落盘载荷解析、截断守卫、provenance 与拼接归属）
│   ├── test_docs.py           ← 19 个用例（文档数字=实跑结果）
│   ├── test_baseline_guard.py ← 58 个用例（重跑逐字段核对 baselines/ 锚点 + raw/evidence 双轨 + 负路径 + 打包守卫）
│   ├── test_preflight.py      ← 3 个用例（前置检查契约：MCP 会话 / 权限探针 / 模型归宿主 / 不过就停并报告缺什么）
│   ├── test_contest_verify.py ← 17 个用例（仿真大赛口径对账：缺证据必须不结论、锁死盘口不算成本已核验、交割日不许顶替、身份字段不外泄）

│   └── fixtures/
│       ├── bars_*.csv      ← 内置合成行情（--fixture 用）
│       ├── raw/            ← agent 落盘的 MCP 原样载荷（不入库）
│       └── landed/         ← --build 的产物（不入库）
├── references/
│   ├── schema.md        ← 字段契约
│   ├── api_guide.md     ← 数据接口
│   ├── mcp-data.md      ← MCP 取数与落盘契约
│   └── validation.md    ← 验收口径
└── agents/              ← Cursor / Hermes / OpenClaw 适配器
```

---

## 快速开始

```bash
# 1. 抽取演示
python3 scripts/build.py

# 2. 标注样本评分（逐字段 precision / recall）
python3 scripts/annotate.py tests/fixtures/labels.json

# 3. 端到端验收（离线，用内置 CSV 行情）
python3 scripts/evaluate.py --fixture

# 4. 用真实行情：脚本不联网。MCP 工具只能由 agent 调用，链路是
#    agent 调 mcp__pandadata__call_pandadata → 载荷原样写入 tests/fixtures/raw/ →
#    本脚本构建成本技能自有格式 → 评测只读本地文件（见 references/mcp-data.md）
python3 scripts/mcp_landing.py --build
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231

# 5. 核对冻结基线（只读）：从确定性夹具重跑一遍，与 baselines/ 逐项比对
# 执行口径核验：先由 agent 落盘仿真大赛载荷，再只读对账（references/contest_verification.md）
python3 scripts/contest_verify.py --out baselines/contest_verify_$(date +%Y%m%d).json

python3 scripts/compare_baseline.py
python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json

# 6. 测试
python3 -m pytest tests/ -v          # 249 个用例（113 + 39 + 19 + 58 + 3 + 17，见下方 tests/ 目录树）
```

验收锚点是**随包发布的交付物**：`baselines/frozen_baseline.json`（冻结参照）与
`baselines/scope_declaration.json`（范围声明副本）都入库，从 git 克隆就能拿到并核对。
`evaluate.py` 运行时会把**重新生成的产物**写到 `output/scope_declaration.json`（开跑前）与
`output/frozen_baseline.json`（跑完）——`output/` 仍在 `.gitignore` 里，它是落点，不是第二个权威。
不一致时 `compare_baseline.py` 指名哪个字段变了（旧值→新值）并非 0 退出，守卫在
`tests/test_baseline_guard.py`。

---

## 设计要点

### 1. 不臆造字段

文本没说止损，`stop_loss` 就是 `null`，同时出现在 `missing_fields` 里。这样做有两个原因：标注时可以惩罚「凭空补全」，回测时也不会把作者没说的风险控制算成他的功劳。

要区分两个层次：进场条件的默认值在**抽取阶段**就补（前提是标的映射成功），并逐条记入
`assumed`（带 `stage: "extraction"`）；期限的 5 个交易日默认**只在** `apply_defaults=True` 时补
（`evaluate.py` 会打开，所以验收链路包含它）。标的映射不到时**不配市价单**——给一条无法执行的
条目配一张 `market_on_next_open`，读起来像一个可以照着下单的信号。

### 2. 推断必须留痕

只有价位、没有「看多/看空」字样时，可以从**目标位方向**推断多空。这种推断会写进 `ambiguity`，并在 `direction_inferred` 标记为 `true`。歧义不被隐藏，而是作为数据交给标注者判断。

### 3. 不可规则化也要输出

「明年大宗商品整体环境应该比今年好」这类句子没有标的、没有条件、没有期限。它不会消失，而是进 `unruleable` 并统计 `ruleable_share`。**如果一份来源里大部分观点都不可规则化，这本身就是有价值的结论。**

### 4. 回测不允许未来函数

只用 `published_at` 严格之后的 bar，且成交在下一根 bar 的开盘价。`published_at` 缺失时直接拒跑，不做「假设当天收盘」这类会引入前视的妥协。

### 5. 与简单基线配对比较

默认基线是**同标的、同起止日期的买入持有**。每条规则交易的收益减去同期基线收益，得到配对 edge。这样扣掉的是「那段时间行情本身」，剩下的才可能是观点带来的增量。

判定不看单笔收益高低，看：

```
≥12 笔成交 且 bootstrap CI 下界 > 0  → positive
≥12 笔成交 且 CI 上界 ≤ 0            → negative
其他                                  → inconclusive
```

**负结果是合格交付。** 如果一份来源的观点规则化后扣费也打不过买入持有，把这件事测出来、说清楚适用边界，同样是有效成果。

---

## 当前状态

### A. 内置 fixture（离线，合成行情）

下表的每一个数字都是 `python3 scripts/evaluate.py --fixture` 的**实际输出**（`tests/test_docs.py`
会断言它们与实跑一致，改代码后忘了改文档会直接测出来），并且同一批数字被冻结在随包发布的
`baselines/frozen_baseline.json` 里，由 `tests/test_baseline_guard.py` 逐项重跑核对：

| 项 | 结果 |
|---|---|
| 标注样本 / 逐字段 exact-match | 26 个样本（27 条判定）/ 1.00 |
| 规则产出 | 15 条（full 6 / partial 7 / neutral 2 / none 1） |
| 可规则化比例 | 0.9375 |
| 回测成交 | 10 笔（跳过 5） |
| 净收益均值 / 胜率 | +0.0195 / 0.80 |
| Sharpe（逐笔 / 年化） | 0.759 / 5.411 |
| 配对 edge vs 持有 | **−0.018527，CI [−0.028301, −0.008560]，n=10** |
| 判定 | `inconclusive` |

判读要说准：edge 的 CI **两端都为负**，即这批合成行情上的规则扣费后稳定跑输持有；判成
`inconclusive` 是因为 n=10 没到 12 笔的冻结门槛，**不是**因为 CI 跨过 0。合成行情的作用只是
把链路跑通，不构成任何市场证据。

### B. 真实行情（经 PandaData MCP 取数并落盘到本技能）

数字来自真实 RB/I 行情，冻结在 `baselines/rb-i-2024H1-real.json`。**原始 MCP 响应不进包；
派生的公开市场日线 OHLCV 与主力映射 CSV 随包发布**在 `evidence/rb-i-2024H1/`，只含日期、
开高低收量和合约代码，不含专有响应字段、凭证或账号信息。链路没变：**agent 取数 → 载荷原样
落盘 → 脚本只读本地文件**，脚本本身从未联网。

| 项 | 结果 |
|---|---|
| 区间 / 品种 | 2024-01-02 – 2024-06-28 / RB、I |
| 数据量 | 每品种 117 根拼接日线；234 行主力映射 + 234 行实际用于回测的具体合约日线（`bars_used`） |
| 主力换月 | 每品种各 1 次（`roll_count`），换月处的基差跳空**保留**不抹平 |
| 回测成交 | 12 笔（跳过 3） |
| 净收益均值 / 胜率 / 最大回撤 | −0.008188 / 0.50 / −0.1453 |
| Sharpe（逐笔 / 年化） | −0.235 / −1.612 |
| 配对 edge vs 持有 | **+0.012154，CI [−0.004511, +0.028479]，n=12** |
| 判定 | `inconclusive` |

**观点文本是合成的，行情是真实的。** 12 个案例的观点原文来自 `tests/fixtures/opinions.json` 中
明确自述 synthetic 的手写夹具，并非历史作者原话；真实的是 2024H1 RB/I 行情。真实锚点与
`baselines/frozen_baseline.json` 的 `extraction` 对象相同，因为二者使用同一观点夹具、标注集与
抽取配置。12 笔交易的有效性结论只依赖规则、真实行情和冻结的基线/成本/门槛，不依赖观点是否
由真实作者发表；它检验规则化与评价流程，不检验某位作者的历史预测能力。

随包 `evidence/rb-i-2024H1/cases_rules_labels.json` 按 12 个成交 `rule_id` 提供案例、完整规则、
人工标签与成交记录。完整规则由同一夹具确定性重建；真实锚点的 `extraction` 段只存汇总、准确率
和配置哈希，并不保存完整规则对象。

这张表不是抄下来的，且有双轨机器证明：
`tests/test_baseline_guard.py::test_real_anchor_reproduces_from_shipped_evidence` **始终执行**，
只从随包派生证据重跑并逐字段比对，不需要原始载荷；有原始载荷时，
`test_real_anchor_reproduces_from_the_raw_payloads` 还会从载荷重建、逐字节核对随包证据后再复跑，
缺少载荷时只有这条 raw 用例跳过。两条路径均比较 1526 个字段并保留 `inconclusive`。

真实重跑同时纠正了两件事。其一，n=12 达到冻结门槛但 **CI 跨过 0**，所以判定仍是 `inconclusive`
——达标不等于有效应。其二，合成锚点上同一套规则的 edge 是 **−0.0185**，与真实行情**符号相反**：
这正是文档不给合成证据封顶分数的理由。

**独立复跑（干净克隆即可，无需取数）**：

1. `python3.11 -m pytest tests/test_baseline_guard.py -k shipped_evidence -q`：复制随包七份派生行情/溯源文件到临时 `real_landed`，重跑并与真实锚点比较 1526 个字段。
2. 手工等价步骤见 `evidence/rb-i-2024H1/README.md`：运行 `evaluate.py --landed-dir <可写目录>/real_landed --start 20240102 --end 20240628`，再用 `compare_baseline.py --frozen baselines/rb-i-2024H1-real.json` 对账。落点目录名必须叫 `real_landed`，因为报告只记录 basename。

**可选的 raw 全链路复核（前两步由 agent 执行，脚本不联网）**：

1. `mcp__pandadata__auth_status` 确认已登录（未登录 → Settings → PandaData → Login）。
2. 调 `mcp__pandadata__call_pandadata`，按 `references/mcp-data.md` 的切片表取
   `get_future_dominant` / `get_future_daily`（RB、I，**20240102–20240628**，与随包锚点同一窗口；
   换窗口就是另一次测量，不能再拿来对这张表），把四份返回载荷**原样**写成
   `tests/fixtures/raw/<method>__<label>.json`。
3. `python3 scripts/mcp_landing.py --build --raw-dir tests/fixtures/raw --out-dir <可写目录>/real_landed --start 20240102 --end 20240628`
   （截断守卫在这里：`row_count < total_rows` 或 `truncated: true` 的载荷会被拒绝并非 0 退出）。
4. `OPINION_TO_RULER_RAW_DIR=tests/fixtures/raw python3.11 -m pytest tests/test_baseline_guard.py -k raw_payloads -q`
   会重跑并核对派生证据。
5. 若产物落点不可写（**安装态技能目录是只读的**），`evaluate.py` 按
   `请求路径 → 工作目录/output → 技能目录/output → 系统临时目录/output` 依次尝试，
   **打印真正写入的位置**，不会算完所有数字后因写不进包而崩溃。
   只读安装往往连工作目录一起只读，所以单一回退点等于没有回退。

`provenance.json` 记录每个文件来自哪些载荷与请求区间；报告里的 `landed_dir` 与 `files` 只记
**名称**而不是本机绝对路径，否则随包发布的锚点会带上取数那台机器的目录结构。

已知的一处口径提醒：即使取全年数据，成交也只会落在观点文本覆盖的那一两个月里（这批夹具的
观点集中在 1–2 月），**不能称为跨周期检验**。

---

## ⚠️ 免责声明

- 本 skill 仅供研究与教育用途，不构成任何投资建议，不提供买卖信号或仓位推荐。
- 不回测保证、不承诺收益。报告中的历史回放结果不代表未来表现。
- 回测为日线收盘口径，未建模盘中触发、涨跌停无法成交、流动性冲击与保证金变化；实盘执行必须由使用者独立复核。
- 本仓库为 QuantSkills 社区项目，未经任何监管机构、交易所、券商或 QuantSkills 官方认证或背书。

---

## 已知局限

- 抽取基于词典与正则，不是 LLM；**支持中文与英文（可混写）**，覆盖常见期货表述，反讽、长距离指代、生僻比喻会落到 `none` 或产生 `ambiguity`。
- 英文按词边界匹配（`long` 不命中 `longer`），但同句多空并存仍记为歧义。
- 词典是白名单，新增语言或新品种需改 `scripts/common.py`，不动逻辑。
- 非标观点文本由阅读本 skill 的 agent 先规范化再调用（见 SKILL.md「非标准输入的规范化前置」）：只调整语序措辞，禁止增删改水平 / 方向 / 品种；凑不齐三要素（品种、方向、显式价格水平）时必须告知用户「该观点不具备分析要点」、指出缺项并给出一条规范语句示例，不得编造输入调用抽取。
- 品种别名是白名单，表外品种不猜。
- 组合层面的资金竞争未建模，规则逐条独立评估。
- 样本量门槛（12 笔）是按上界保守设定的，并不代表 12 笔就有统计功效。

---

## 许可

GPL-3.0-only。见 `LICENSE`。