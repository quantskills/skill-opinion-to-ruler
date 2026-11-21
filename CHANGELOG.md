# Changelog

All notable changes to `skill-opinion-to-ruler` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

## [0.9.3] — 2026-11-21

套件规模：164 → 249 条用例，累计新增 85 条（本版 0 条，只扩既有守卫的断言）。
**non-breaking**：抽取器、词典、判定规则、两份锚点与 PandaData MCP 取数通道全部
未动；本版把 0.9.2 的规范化口径落进**用户与 agent 的交互流程**，写进运行时适配器。

### Added（交互流程进适配器——agent 执行时真正读到的地方）
- SKILL.md「非标准输入的规范化前置」补完整交互流程图：三要素判定 → 改写（向用户
  展示「原文 → 改写结果」）→ 组装输入（`published_at` 必须真实，缺失就问、绝不
  编造）→ 调用 → 回报（unruleable 的 reason 原样转述）；要素不全走「告知不具备
  分析要点 + 给规范语句示例 + 用户确认后回到判定」。
- `agents/openai.yaml` 新增 `x-interaction-flow`（5 步：triage / normalize /
  refuse_with_template / invoke / report + canonical_template）；
  `agents/cursor-rule.mdc` 新增「Non-standard input: normalize first, refuse
  second, never fabricate」节；`agents/portable-loader.md` 的 Agent Integration
  新增同款流程小节。三个适配器与 SKILL.md 口径一致。
- `tests/test_docs.py::test_agent_normalization_protocol_is_documented` 扩展断言：
  交互流程必须同时存在于三个适配器（防止只写在设计文档里、运行时 agent 读不到）。

## [0.9.2] — 2026-11-21

套件规模：164 → 249 条用例，累计新增 85 条（其中本版 1 条）。**non-breaking**：
抽取器、词典、判定规则、成本、两份锚点与 PandaData MCP 取数通道全部未动；
本版把「非标输入先规范化、规范不了就拒绝」的 agent 行为准则钉进文档。

### Added（非标输入的 agent 前置规范化口径）
- SKILL.md 新增「非标准输入的规范化前置（agent 行为准则）」小节：
  - **分析要点三要素**：白名单品种、明确方向（中性表述归 neutral）、至少一个显式
    价格水平；期限可选，缺失走冻结默认策略并记 `policy_default`。
  - **三条处理路径**：已规范 → 直接传入；非标但要素齐全 → 只调整语序措辞的改写
    （禁止增删改任何价格水平 / 方向 / 品种，凡需猜测一律按缺失处理），
    `published_at` 保持原值、建议用附加字段保留用户原文（管线容忍但不回显）；
    要素不全 → **不调用、不编造**，告知用户「该观点不具备分析要点」、指出缺项、
    给出一条规范语句示例供确认。
  - **责任边界**：抽取准确率验收针对规范语句；规范化忠实度是前置 agent 的责任，
    管线不校验——拿不准就走拒绝路径。
- README.md / README.en.md 的「已知局限」各补对应条目。
- `tests/test_docs.py` 新增 1 例守卫：该口径必须同时存在于 SKILL.md 与两份 README，
  防止日后被删掉后，阅读 agent 拿编造的水平喂抽取器、产出带着干净审计轨迹的假数字。

## [0.9.1] — 2026-11-21

套件规模：164 → 248 条用例，累计新增 84 条（其中本版 1 条）。**non-breaking**：
判定规则、成本、锚点数值与两份基线全部未动；本版只补「无 raw 载荷的第三方如何自证
包内 CSV == 网关数据」的验证口径。

### Added（补交口径闭环：sha256 复取验证）
- `evidence/rb-i-2024H1/checksums.json`：七份派生文件的 SHA-256 清单 +
  **精确到参数的 PandaData MCP 复取配方**（4 次 `mcp__pandadata__call_pandadata` 调用，
  含 symbol / 窗口 / fields / 落盘文件名）+ 重建命令。第三方流程：按配方复取 → `mcp_landing.py --build`
  重建 → 比对 sha256；一致即证明随包 CSV 与网关当前返回逐字节相同。
- 不一致时的口径也写死：说明网关数据在 2026-11-21（取数日）后被修订，应报告差异、
  不默采任何一侧；随包锚点锚定的是取数日那一份。
- `tests/test_baseline_guard.py::test_checksums_match_the_shipped_evidence`（无条件执行，
  不依赖 raw/网络/登录）：核对清单与目录实物一致、覆盖集合不多不少、复取配方的窗口合法、
  provenance 引用的每份载荷都在配方内——防止清单与文件漂移后验证路径静默失效。
- evidence README 新增「无原始载荷时的第三方验证」小节。

## [0.9.0] — 2026-11-21

套件规模：164 → 247 条用例，累计新增 83 条（其中本版 4 条；此处沿用上版起点的
累计口径，按 `pytest --collect-only` 实测）。本次为 **non-breaking**：抽取器、成本、判定阈值、
两份锚点的交易指标与 PandaData MCP 取数通道均未改变；真实结论仍是 `inconclusive`。

### 对应审核要求 1：补交原 12 例的行情只读入口、案例、规则与标签

- 新增随包证据目录 `evidence/rb-i-2024H1/`：六份派生 CSV（I2405/I2409/RB2405/RB2410 日线与
  I/RB 主力映射）、`provenance.json`、证据 README，以及 `cases_rules_labels.json`。
- `cases_rules_labels.json` 按真实锚点 `backtest.trades[].rule_id` 选出 12 个案例，每组保留
  `case`（id / published_at / 原文）、`rule`、`label` 与 `trade`。完整规则由同一观点夹具经
  `build.run(..., apply_defaults=True)` 确定性重建；真实锚点的 `extraction` 段实际只存汇总、
  准确率与 `config_hash`，并未存完整规则对象，证据说明没有伪称从锚点复制规则。
- 原始载荷已按原窗口重新取回用于复核：20240102–20240628；I2405 切片到 20240327、I2409
  从 20240328 起，RB 一次覆盖两个合约，主力映射一次覆盖 I/RB，共 4 份。原始 MCP 响应仍不入库。
- **权限口径收窄并说清**：不发布的是原始响应；随包发布的是派生公开市场日线 OHLCV 与主力映射，
  仅日期、开高低收量、合约代码等字段，不含专有响应字段、凭证、账号信息或账户衍生数据。
  `tests/fixtures/raw/*`、一般 `tests/fixtures/landed/*` 与仿真大赛原始载荷继续被忽略。
- 载荷清单统一为 4 份，删除 raw README 多出的 `RB_DOMINANT.SHF` 项。

### 对应审核要求 2：独立复跑并按证据保留原结论

- 新增**双轨守卫**：有 raw 载荷时，原 raw 守卫重建七份派生产物、逐字节核对随包 evidence，
  再重跑真实锚点；无 raw 时它仍按原契约跳过。新增 evidence 守卫则只使用随包派生产物，
  在干净克隆上**无条件执行**，不登录、不联网。
- 两条路径都比较 **1526** 个字段（报告 1448 + 范围声明 78）。独立手工复跑得到
  `1448 field(s) compared, 0 mismatched`、`verdict: CONSISTENT`；n=12、edge/CI 不变，
  结论保持 `inconclusive`，没有为了补交而升级有效性。
- 新增证据内容守卫：12 个 `rule_id` 的顺序与真实成交一一对应；案例与观点/标签夹具逐字段一致；
  完整规则与当前抽取器确定性输出一致；证据 JSON 不得写机器绝对路径。
- 既有打包守卫同步检查真实锚点、派生 CSV 和案例/规则/标签会被 `git add -A` 收进 index，
  raw/landed 则不会，避免“本地能跑、克隆缺证据”。

### 澄清与修正

- **观点文本是合成的，行情是真实的。** 12 个观点来自 `tests/fixtures/opinions.json` 明确自述
  synthetic 的手写夹具，不是历史作者原话；真实的是 2024H1 RB/I 行情。真实锚点与合成锚点的
  `extraction` 对象相同，因为共用观点、标签与抽取配置。12 笔交易只检验规则化与评价流程，
  不检验真实作者的预测能力。
- 真实回测数据量改为 **234 行实际用于回测的合约日线 `bars_used`**（56+61+58+59）+
  234 行主力映射。随包合约 CSV 文件本身共 320 行，包含非主力日；文件行数与回测用量不再混写。
- 真实锚点 `landed_dir_note` 与其生成器同步改为“来源载荷文件名”，不再误称保存了 gateway
  request id；改动后 raw/evidence 两条逐字段守卫均通过。
- `skill.json` 升至 0.9.0，声明真实锚点、证据目录、案例/规则/标签及无条件复跑入口；
  中英 README、SKILL、INSTALL、MCP 数据契约与适配器同步更新。

## [0.8.0] — 2026-11-19

套件规模：164 → 243 条用例，累计新增 79 条（0.8.0 补 `tests/test_contest_verify.py` 17 例；
计数按 `pytest --collect-only` 实测）。本次仍是 **non-breaking**：判定规则、成本默认值、
两个锚点的数字都没动（本包唯一一次 breaking 仍是 0.4.0 移除旧取数通道、改由 agent 经
PandaData MCP 落盘）。

### Added — 把「等价回放」的执行口径拿到期货仿真大赛下对账

任务原文要求「交易执行部分用期货模拟赛核验；品种或接口不支持时事先明确等价回放范围」。
0.7.x 只做了后半句，于是 `次日开盘成交 + 单边 3bp 手续费 + 2bp 滑点` 这三个常数从来没被量过。

- `scripts/contest_verify.py`（纯标准库、只读本地落盘载荷、不下单、不联网）：品种是否真在撮合
  系统启用、合约乘数、四项保证金与每手保证金、半价差实测跨价成本、最后交易日与交割日
  （缺失写 `暂无数据`，**不许**用最后交易日顶替）
- `references/contest_verification.md` + `tests/fixtures/contest/raw/README.md`（落盘契约与脱敏规则）
- `baselines/contest_verify_20261119.json`：随包发布的核验报告（已剥离账号/手机号/用户名）
- `SKILL.md` 新增「仿真大赛核验」小节与前置检查第 5 项；`agents/openai.yaml` 新增
  `contest_verify` 步骤与 `contest_channel` 前置项
- `tests/test_contest_verify.py` 17 例：缺载荷必须报错而不是给绿灯、`ready=false` 不许把 0 当
  最新价、买卖一价同价（锁死盘口）只能算规格核验、手续费无回执一律 `unverified`、
  执行核验在无成交回执时永远 `not_verified`、身份字段不得进报告

### Measured（2026-11-19 实跑，rb2701 / i2701）

- 规格全部对上：SHF/DCE 均启用；乘数 10 / 100；保证金 7% / 8%；每手 2,089.50 元 / 5,184.00 元；
  最后交易日 20270115（距 57 个日历日）；交割日暂无数据
- **滑点被低估**：实测单边跨价成本（半价差）RB 3.35 bp、I 3.86 bp，是 2 bp 假设的
  1.68x / 1.93x → verdict `cost_model_below_market`
- **但结论不因此翻转**：配对基线两臂扣同一笔成本，edge 完全抵消 —— `--slippage-bps` 取
  2 / 3.3512 / 3.8595 / 5.0 四档，`edge −0.018527  CI [−0.028301, −0.00856]  n=10
  verdict INCONCLUSIVE` 一字不变；传导到的是绝对收益侧：`mean net 0.0195 → 0.019128`、
  `Sharpe 5.411 → 5.307`、`maxDD −0.01378 → −0.014152`
- 手续费与撮合执行仍是 `unverified` / `not_verified`：没有成交回执，且下单必须逐笔经用户
  明确确认 —— 这一条没做，报告就不允许声称执行已核验

## [0.7.1] — 2026-11-18

套件规模：164 → 225 条用例，累计新增 61 条（这 61 条随 0.7.0 落盘，0.7.1 只统一
口径与补守卫，未再增删用例；计数按 `pytest --collect-only` 实测）。

文档口径统一，不改任何行为：本次是 **non-breaking**（本包唯一一次 breaking 仍是
0.4.0 移除旧取数通道、改由 agent 经 PandaData MCP 落盘）。

- `SKILL.md` 的「前置检查」点名运行环境为 **QuantStudio**：解释器、模型与数据通道
  都由宿主提供，技能不自行准备数据也不自行准备模型。
- README / INSTALL / references / agents 中残留的「SDK」字样全部清除，
  统一成「取数客户端 / MCP 落盘」表述（已发布版本的历史记述未改动）。
- `tests/test_preflight.py` 的必需项加入 `QuantStudio`；`tests/test_docs.py` 的禁用词
  加入 `SDK`，让这条口径从此由测试守着，而不是靠人记得。
- `agents/openai.yaml` 新增 `x-preflight` 块，把前置检查暴露给只读适配器的 agent；
  `skill.json` 的 `data_source` 标注 QuantStudio 宿主。
- 与另两个 skill（`skill-jev-history-replay`、`skill-constraint-stress-test`）的前置检查
  形态对齐：三者同名小节、同样排在可执行流程之前、同样有反向守卫测试。

## [0.7.0] — 2026-11-18

**这次不是加功能，是把已经交付出去的数字查回来看了一遍。** 0.6.0 的 164 条测试全绿、
`compare_baseline.py` 一致、验收锚点随包发布——然后逐条对抗式探针在同一个包面上挖出 10 个
会改变结论的缺陷。全绿不等于对：测试全部由"词典已经能处理的说法"构造，所以每个缺陷都在
100% 通过率下带着病运行。

- **Fixed（抽取语义，会改变规则本身）**：
  - **百分比价位不再当绝对价**。`止损3%` 原来产出 `close < 3` —— 一条进场当天就触发的假止损，
    而回测会把它当成作者声明的风险控制。现在字段留 `null`，百分比进新通道 `percent_levels`
    并记 `ambiguity`。日线收盘撮合无法执行相对价，要在抽取层折算就是猜。
  - **否定不等于反向**。`不再看多` 原来判 **long**（否定扫描命中"不再"，价位扫描又读出看多）。
    现在判 `neutral`：作者撤回观点，没有说出相反观点。`不看空…才转多` 仍判 long，但取的是
    **未被否定**的那个词，并把否定命中记进 `ambiguity` 交人工复核。
  - **跨子句价位不再互相串味**。`螺纹钢多头铁矿空头，RB看3850上方，I看840下方` 原来合成
    **一条**螺纹钢规则、止损取到铁矿的 840 —— 螺纹钢永远跌不到 840，这笔"有风控"的交易实际
    上一直拿到期。现在按标的出现位置切成两条规则，价位只在各自区间内找。
  - **`rule_id` 按规则编号而不是按句子编号**（一句两标的时 `-r01`/`-r02`）。
  - **裸代码与合约号**。`RB看多` 原来整条丢失（代码只在紧邻中文时被识别）；`RB2405…` 原来
    把 `symbol` 填成 `RB2405`，白名单校验永远对不上。现在 `symbol=RB` +
    `contract_code=RB2405` + `mapping_rule=contract_to_product`，交易所由品种反查得到。
    纯英文语境的单字母代码**刻意不认**（否则 "I think…" 变成一笔铁矿交易）。
  - **`看3850上方` 不再同时是进场和止盈**。原来进场 `close > 3850`、止盈 `>= 3850` —— 同一根
    bar 上进场即离场。区间后缀词现在被挡在目标位模式之外。
  - **价位合理性守卫**：止损在进场错误一侧（`站上3850做多，止损3900`）或落在该品种历史价
    5 倍之外（铁矿 3780）时丢弃该字段并记 `ambiguity`，而不是产出一条永远打不到的止损。
  - **映射不到标的的条目不再配一张市价单**（`50ETF购3月2500看多` 原来带着
    `market_on_next_open`，读起来像可执行信号）。默认进场仍以 `instrument` 已解析为前提。
- **Fixed（指标口径，虚高约 15.6 倍）**：`sharpe` 把**逐笔**收益乘 `sqrt(244)` 当年化。
  `244` 是每年日线根数，而收益每年只来 ~50 次（每次覆盖自己的多日期限）。合成锚点因此
  把 0.759 的逐笔比值发布成 **11.854**，真实锚点把 −0.235 发布成 **−3.665**。
  现在年化系数改为 `sqrt(244 / mean(held_bars))`，并同时输出 `sharpe_per_trade`、
  `sharpe_trades_per_year`、`sharpe_basis`、`sharpe_held_bars_coverage`。
  **金融结论（edge / CI / 笔数 / 判定）一个都没变**——错的只是被引用的那个指标。
- **Fixed（准确率诚实度）**：`annotate.py` 不再把**策略默认补出来的槽位**算成读对
  （`policy_default` 单列，`exact_match_text_only` 排除之）。随包金标准里 `op-007/011/012`
  的 `entry_expr` 曾被抄成 `market_on_next_open` —— 那是抽取器的输出被当成了人工标注，
  政策在批自己的作业。现在三处改为 `null`。
  另外新报 Clopper-Pearson 95% 下界：26 条全对的下界只有 **0.8677**，英文集 10 条只有
  **0.6915**，`>=40` 条才打警告解除；`labels` 支持 list 型金标准以核对一句多标的的**条数**
  （原实现静默丢掉第二条规则，正是这个缺陷让它可检）。标注样本 16 → **26**，覆盖上面每一类
  坏掉的写法。
- **Fixed（可移植性）**：随包锚点与 `scope_declaration.json` 里记的是**取数那台机器的绝对路径**
  ——取数那台机器的家目录与临时目录绝对路径），换台机器溯源全对不上；现在只记名称
  （技能根目录内为相对路径，目录外
  记基名 + `landed_dir_outside_skill: true`），且守卫会扫三份锚点的每个字符串值。
  `evaluate.py` 写产物时若目标目录不可写（**安装态技能目录是只读的**）不再裸崩：按
  `请求路径 → 工作目录/output → 技能目录/output → 系统临时目录/output` 依次回退并打印实际落点。
  **这一条也是跑出来的**：第一版只回退到工作目录，而"在只读安装里跑一遍"的场景里工作目录恰好
  就是那个只读目录，于是照样崩——单一回退点不是回退。四处全不可写时才停下，并列出试过的每一处。
  `mcp_landing.py --build` 犯的是**同一类**毛病（只读安装里写 `tests/fixtures/landed/` 直接吐
  traceback）：三处写点现在统一走 `_open_out`，失败即结构化 `landing_not_writable` + rc=3 + 修法。
  这里**故意不自动改写到别处**——landed 数据被悄悄挪走，`evaluate.py --landed-dir` 就找不到它了，
  那比报错更糟。新增的守卫把"代码真会 raise 的错误码必须写进 `api_guide.md`"钉住，当场逮到
  `data_unavailable` 这个一直没人记录的可达错误码（永远 raise 不到的抽象基类则排除在外）。
- **Fixed（前置检查口径颠倒）**：第 4 条要求 `python3 -c "import pandas"`，而**脚本只用标准库**、
  `requirements.txt` 声明无三方依赖 —— 在一台按设计能跑的机器上报"依赖缺失"。真正缺的是跑测试的
  `pytest`。改为要求 `import pytest`，并由 `test_preflight.py` 反向禁止 pandas 出现在闸门里。
- **Changed（显式重冻结）**：`build.py:VERSION` **0.3.0 → 0.4.0**。`config_hash` 是
  `apply_defaults + policy + extractor 版本` 的哈希，而抽取语义这次真的变了；不升版本号，
  0.6.0 的运行会与 0.7.0 的运行看起来"可比"，而它们的规则对象根本不是同一批东西。
  `config_hash` 随之 `557bfc7d… → 4b52a3d4…`。
  **两份锚点（`frozen_baseline.json`、`rb-i-2024H1-real.json`）与 `scope_declaration.json`
  已按新代码重签**，重签前后 edge / CI / 笔数 / 判定逐字段一致，只有 Sharpe 与 `config_hash`
  变——这正是我们想要的变化范围。被核对的字段从 826 个涨到 **1435**（新增的都是守卫本身：
  逐字段 `policy_default`/置信下界、5 个 Sharpe 基数、溯源的可移植路径），核对面变宽不代表
  结论变了。
- **Fixed（我自己引入的回归，被导出验证抓到）**：产物回退链第一版**提前调用 `os.getcwd()`**，
  于是"目标目录完全可写"的正常路径也会因为 cwd 不可读而整体崩——**为防崩溃而建的机制变成了新的崩溃点**。
  现在候选位置逐个防御式解析（`_location_bases()`），点不出名字的位置直接不算候选，
  写报告这件事不再受 cwd 影响。这条是**把包导出到 `/tmp` 实跑**才发现的：工作区里 cwd 正常，
  单元测试全绿也照不出它。补 `test_unnameable_working_directory_does_not_break_the_happy_path`。

- **Fixed（进场俚语整句被丢）**：`上车` 不在 `LONG_WORDS` 白名单里，
  `螺纹钢突破3900就上车，止损3800。` 判为「无方向措辞」而**整条丢弃**——标的、进场条件、
  止损三样文本里都写清楚了，全没要。现在它出 `RB long / close > 3900 / stop close < 3800`，
  而 `别上车` 仍然走否定→`neutral`（否定优先于词典，不因加词而松动）。
  仓位/持仓管理类（`减仓`、`加到三成仓`）与期权腿**仍判 unruleable**：那是已声明的范围外，
  不是漏判——区别在于范围外的条目会带精确原因进 `unruleable` 统计，不会被当成"作者没说清"。
- **Changed（指纹再进一位）**：`build.py:VERSION` **0.4.0 → 0.4.1**，`config_hash`
  `4b52a3d4… → 8f9058b5…`，两份锚点**第四次重签**。这次重签里 **backtest / extraction 数字一个没动**
  （语料里没有 `上车`），逐字段比对只有 `config_hash` 与其下游 `scope_hash` 变了——
  这正是把词典变更记进指纹的意义：它告诉调用方"抽取语义变了"，哪怕这次变化没有改动任何历史结果。
- **Added（守卫补漏）**：`test_documented_extractor_fingerprint_matches_the_code`。
  `build.VERSION` 是**第二个版本命名空间**（包版本 0.7.0、抽取器 0.4.1），原有的一致性守卫只管包版本，
  于是 `references/schema.md` 抄着的抽取器版本与 `SKILL.md` 里的示例 hash 都会静默过期——
  本次改 VERSION 时就是靠这条新守卫当场逮到的（它先是红了，改完文档才绿）。
  它同时用公开 API 重算 `config_hash` 与随包锚点比对，所以"锚点是不是当前这份代码签的"
  也再不是靠人自觉。

- **Added（会真失败的守卫，164 → 225 条用例）**：
  - `test_real_anchor_reproduces_from_the_raw_payloads`：真实锚点从**授权载荷**重新落盘、
    重新评测、逐字段比对（**1526** 个字段。合成锚点那条路径是 1435 = 报告 1357 +
    范围声明 78）。两个数都由守卫钉死，收窄字段遍历就会当场失败。缺载荷即跳过，不假装通过。
    **已反证它真的会咬**：篡改 I2405 的成交价时因为那几天不成交而毫无反应，遂改为篡改
    **成交当日**的进场价与止损触发的收盘价、以及删掉主力映射行 —— 三次分别令
    `edge.ci_high/ci_low/mean` 报错并非 0 退出，还原后归 0。
  - `test_the_real_anchor_is_self_consistent`：锚点里的 `verdict` 必须等于用**它自己的**
    edge/CI/n 重新判定的结果，`edge.n` 必须等于成交记录条数，CI 必须夹住均值。
  - `test_no_shipped_anchor_records_a_machine_path`：三份锚点里任何字符串值都不得含本机绝对路径。
  - `test_rules_table_matches_the_emitted_rule_object`：`schema.md` 的 rules[] 表与代码实际
    输出的字段**双向**比对。它当场逮到两件事：本次我自己新加的 `source_span` 是
    `source_text` 的逐字重复（已删），以及 4 个从 0.3.0 起就没人记录的字段。
  - 共**新增 61 条**回归与守卫用例（164 → 225）。`tests/test_docs.py` 会核对文档里的
    用例数与 pytest 实际收集数，所以这个数字本身也不会悄悄烂掉。
- **Docs**：`SKILL.md` / 中英 `README` / `references/*` 的每个数字与口径同步。真实行情表不再
  写"待重测"而同时被 `SKILL.md` 引用具体数字（两份文档互相矛盾）；`validation.md` 里
  "否定词翻转"的机制说明改为实际语义；Sharpe 一栏同时给逐笔与年化两个基数。
- **Breaking**：抽取输出新增 `percent_levels`；`instrument.symbol` 对具体合约改为品种代码
  （原为 `RB2405`），合约号移到 `instrument.contract_code`；`sharpe` 数值口径变更；
  `annotate` 报告新增 `policy_default` / `*_ci95_low` / `rule_count_mismatches` 等键。
  一句多标的句子现在产出多条规则，`counts.rules_total` 可大于句子数。

**数据通道没有变化**：仍然是 **MCP** 取数 → 载荷原样落盘 → 脚本只读本地文件，脚本零网络、
零凭证；本次没有恢复 0.4.0 删掉的 SDK 直连通道，也没有引入任何新的取数入口。

**价值结论不变**：机制已在真实行情上跑通，价值仍未验收（V=0.60）。真实重跑 n=12 达到门槛，
但 CI `[−0.004511, +0.028479]` 跨 0 → `inconclusive`；合成锚点同一套规则给 **−0.0185**，
符号与真实相反。达标 ≠ 有效应，合成证据不能封顶分数。

---

## [0.6.0] — 2026-11-18
- **Fixed（真跑出来的缺陷，非纸面推演）**：`mcp_landing.payload_rows()` 只在**顶层**找
  `rows/data/records`，而网关把表包在 `{"ok":…, "result": {"columns":…, "rows":…}}` 信封里。
  于是**按本技能契约"原样落盘"的真实载荷一律 `payload_unreadable`（rc=3）**——文档写明的
  真实取数路径从未跑通过，此前只在"顶层 rows"形状的测试替身上绿过。现解包 `result/data/
  payload/response` 信封，回归守卫 `test_payload_rows_reads_the_verbatim_mcp_envelope`
  已过变异测试（关掉解包即红）。用例 163 → **164**。
- **未修，已记边界**：真实回测按**声明范围**要求每个品种的主力映射 + 每个具体合约的日线
  （`dominant_RB.csv` / `dominant_I.csv`），单条连续主力日线（`RB_DOMINANT.SHF`）会被
  **诚实拒绝**而非硬算：`[warn] 2 declared symbol(s) were NOT served … fix the data and
  re-run` + `[error] no bars available for any declared symbol`。拒绝行为正确；缺的是文档
  从没说清"一个品种要几次取数"，已补进 `references/mcp-data.md`。
- **补上规约要求的「价值验收」小节**（`SKILL.md`）：此前缺失（`grep -c 价值` = 0），四问里
  「作用多大」只散落在回测说明中。新增小节直接引用随包锚点里的实测数——edge 均值 -0.018527、
  95% CI [-0.028301, -0.00856]、成交 **10** 笔 < 自身门槛 `backtest.MIN_TRADES` = 12 →
  `verdict=inconclusive`，并写明这是**门槛判定不是效果判定**、V 停在 0.60 及抬到 0.80 的前置条件。
  纯文档，无行为变更，故不虚增版本号。

### Breaking

- **验收锚点从 gitignore 的运行期目录移入随包发布的 `baselines/`。** 0.5.0 及之前，
  `skill.json` 把验收物声明成 `output/frozen_baseline.json`，而 `.gitignore` 里就有
  `output/` 这条规则——从 git 安装/克隆本技能的人拿不到冻结基线，规约要求的
  「冻结基线对照」交付项在干净检出上等于不存在。现在：
  - `baselines/frozen_baseline.json` = **冻结参照**（验收锚点，入库、随包发布）；
  - `baselines/scope_declaration.json` = 它的范围声明副本（入库）；
  - `output/` 仍然是**重新生成产物的落点**（运行期、继续 gitignore），不是第二个权威；
  - `skill.json` 的 `outputs.acceptance_report` → `outputs.acceptance_anchor` /
    `acceptance_anchor_scope` + `regenerated_report` / `regenerated_scope`，
    并新增 `acceptance_anchor_is_gitignored: false`。依赖旧键名的调用方需改读新键。
  - `.gitignore` 用 `!baselines/*.json` 显式给锚点开洞，**没有**放宽 `output/`
    （写成 `!output/*` 会把运行期产物放回包里，让两份文件都自称权威）。锚点的
    tracked 属性由 `tests/test_baseline_guard.py` 钉住，并用 `git add -A` +
    `git ls-files` 交叉验证——注意 `git check-ignore -v` 在这里**不能**用作判据：
    它对「被否定规则匹配到」的路径同样返回 0，会把已入库的锚点说成被忽略。

### Added

- **逐字段一致性守卫 `scripts/compare_baseline.py`（只读、不联网）**：从确定性夹具
  （`data_mode: fixture`，`tests/fixtures/bars_{RB,I}.csv`）重跑一遍完整链路，把结果与
  `baselines/frozen_baseline.json`（826 个叶子字段）与 `baselines/scope_declaration.json`
  （78 个字段）**逐项判等**。不一致就结构化报出哪个字段变了（`frozen=<旧值> -> generated=<新值>`）
  并非 0 退出：`0` 一致 / `1` 字段变了 / `2` 锚点缺失或用法错误（锚点缺失是打包事故，不算通过）。
  覆盖 `extraction.summary.*`、`extraction.accuracy.fields.*` 的 tp/fp/fn/tn 与
  precision/recall/exact_match_rate、`backtest` 的 edge/CI/n/metrics/逐笔成交、
  `cost_model`、`min_trades_for_verdict`、`scope_declaration.replay_equivalence`、
  `applicability`（含 `in_scope`/`out_of_scope`/`fails_when` 逐条）与 `value_assessment`。
  浮点容差 `5e-7`（报告按 6 位小数发布，这是最小发布位的半格，只吸收二进制浮点噪声），
  整数/字符串/布尔/列表长度/键集合一律精确判等；豁免字段只有 `generated_at`（运行时间戳），
  且这条豁免本身被测试钉死，防止有人靠扩大豁免把守卫掏空。
- **`evaluate.py --check-baseline PATH`**：在同一条验收命令里做只读核对，
  `python3 scripts/evaluate.py --fixture --check-baseline baselines/frozen_baseline.json`，
  不一致退出码 1；`--json` 时核对结论走 stderr。配套新增 `--scope-output`（默认仍是
  `output/scope_declaration.json`），使锚点核对可以在不落任何运行期产物的前提下完成。
- **`tests/test_baseline_guard.py`（39 个用例）**：重跑与锚点的全字段比对、按规范列出的
  必需字段覆盖率断言、以及**负路径**——改一位 `backtest.edge.mean`、改 tp、改成本参数、
  改 `min_trades_for_verdict`、翻转 `replay_equivalence` 文本、删一条 `fails_when`、
  增删字段、交换两条边界文本，全部必须报错并指名道姓；再加 CLI 退出码、
  守卫只读性（跑完比对 `baselines/` 字节未变）、以及 `.gitignore` 两个方向的打包断言。
- `tests/test_docs.py` 9 → 12 个用例：逐文件用例数守卫扩到 4 个测试文件并覆盖中英两份 README，
  另加「文档里的**用例总数**等于 pytest 实际收集」「文档 `tests/` **文件清单**等于真实模块」
  「所有版本声明（skill.json + 声明版本的适配器 + CHANGELOG 顶部）必须一致」——此前只逐个
  文件核对中文 README，总数、清单与适配器版本会静默过期。

### Changed
- **前置检查成为加载前的硬闸门**（SKILL.md 顶部新小节）：本技能不自行准备数据、也不自行
  准备模型——行情来自宿主配置的 PandaData MCP，模型来自宿主。加载前依次确认 MCP 会话
  （`auth_status` 的 `ok` / `reauth_required`）、最小权限探针（`get_trade_cal` 单日）、
  模型由宿主提供、解释器与依赖；**任一不过即停止，只报告缺什么与怎么补**，不产出数字、
  不换源、不静默降级。`tests/test_preflight.py` 3 例反向守这份契约（小节存在且含四项、
  排在一切可执行流程之前、SKILL.md 内不得出现自备数据/模型的符号）。

- 文档中凡把 `output/frozen_baseline.json` 当验收物的表述，一律改指
  `baselines/frozen_baseline.json`，并写明 `output/` 只是重新生成的落点：
  `SKILL.md`、`README.md`、`README.en.md`、`INSTALL.md`、`references/validation.md`、
  `references/api_guide.md`、`agents/portable-loader.md`、`agents/openai.yaml`、
  `agents/cursor-rule.mdc`、`skill.json`。
  `references/validation.md` 的复现命令从 5 条增加到 7 条（加入两条锚点核对），
  并把「锚点放在 gitignore 目录里」「守卫只查文件存在而不逐字段比对」列入不合格情形。
  `INSTALL.md` 的「验证安装」加了锚点核对一步（从 git 克隆后必须跑得通），退出码约定
  补上「核对不一致 = 1」，并修正「`evaluate.py` 只接受 `--fixture` 或 `--landed-dir`」
  这句已被新开关打破的话——行情来源仍是二选一，其余开关不决定数据来源。
  文档里写死的用例数与 `tests/` 清单按实跑刷新（118 → 160）。
- `.github/workflows/validate.yml` 新增三步（都在干净检出上跑，不取数、不联网）：
  ① 用 `git ls-files` + `git status --porcelain --ignored` 断言两份锚点**确实入库**、
  `output/` 仍被排除——这正是 0.5.0 缺失的那道门；② `compare_baseline.py` 与
  `evaluate.py --fixture --check-baseline` 逐字段复核；③ 反向验证：把锚点拷到临时目录、
  把 `backtest.edge.mean` 改一位，守卫必须非零退出**且指名该字段**，否则视为空守卫，
  同时校验 `baselines/` 的 sha256 未被核对过程改动。
  三处都写明：`git check-ignore` 的退出码**不能**当判据（它是否定匹配也返回 0），
  真正的判据是索引。CLI smoke 补上 `compare_baseline.py --help`。
- `tests/test_docs.py::_run_fixture` 同时传 `--scope-output`，跑文档守卫不再写运行期目录。

### Fixed

- `scripts/evaluate.py` 用了 `Optional` 注解却没从 `typing` 导入（靠
  `from __future__ import annotations` 才没在运行期炸），补齐导入。

### Notes

- **守卫的默认路径是夹具，不是 MCP 取数。** `compare_baseline.py` 不带 `--report` 时从
  确定性夹具重跑，与 `baselines/` 里的夹具参照（`data_mode: fixture`）比对；真实行情要先由
  agent 调 `mcp__pandadata__call_pandadata` 取数、原样落盘、`mcp_landing.py --build`，那条路
  径的数据不在包里，所以核对它得用 `--report <该次产物>` 对照**同一批数据**冻结出来的参照。
  夹具参照与 landed 参照不能互比——报告里的 `data_mode` 字段就是用来分辨这一点的，跨模式
  比对在本守卫下必然报不一致，而不是悄悄通过。
- **冻结数字一位未改**：documents 16 / rules_total 15 / full 6 / partial 7 / neutral 2 /
  none 1 / ruleable_share 0.9375；`instrument_symbol` tp15 fp0 fn0 tn1；RB 260、I 260 根；
  edge −0.018527，CI [−0.028301, −0.008560]，n=10，判 `inconclusive` 的原因是 n 未达
  12 笔门槛（该 CI 两端皆负，不是跨 0）。本条变更**只搬锚点的位置、只加守卫**，
  没有重刷任何基线值。
- `scripts/build.py::VERSION`（抽取器指纹，参与 `config_hash`）**没有**跟随包版本升到 0.6.0：
  它是算法指纹，一改 `config_hash` 就变，等于改动冻结基线。
- 用例数 118 → **160**（`test_ruler.py` 74 + `test_mcp_landing.py` 35 + `test_docs.py` 12 +
  `test_baseline_guard.py` 39）。

- 真实行情重跑并固化第二份锚点 `baselines/rb-i-2024H1-real.json`（2024-01-02..06-28，品种 I+RB，
  234 行主力映射 + 234 行实际用于回测的具体合约日线 `bars_used`（对应合约 CSV 文件共 320 行，
  含非主力日），全部经 `mcp_landing.py --build` 与完整性校验落盘）：
  **n=12 达标但 CI [-0.0045, +0.0285] 跨 0 → `verdict` 仍为 `inconclusive`**。
  由此确立两条口径：`MIN_TRADES` 是必要不充分条件；合成锚点 edge -0.0185 与真实 +0.0122 **符号相反**，
  即合成数据不仅样本量不足、方向也可能是错的——`SKILL.md` 的「价值验收」已按此改写，V 仍为 0.60。
- 记录一次数据完整性事故与由此暴露的信任缺口：探针载荷曾被误写为自洽但虚构的行情，`--build` 报
  `partial:false` 而未拦截（它只能校验 `row_count==total_rows==len(rows)` 的内部自洽，无法证明行来自网关）。
  已改为**逐笔回查真实返回**后才继续；结论：取数方与判定方不可为同一角色，且落盘载荷应保留 `request_id` 与
  `sha256` 以便人工回查。本技能不在包内自动校验该项（无法离线证伪），仅在文档中写明。
---

## [0.5.0] — 2026-11-18

### Breaking

- **删除对其他技能的依赖。** 0.4.0 把取数落盘委托给 `skill-quant-data-pipeline` 的
  写入端脚本，并沿用它的目录约定（某个 `data/raw/` 下的 cache 目录 + 逐行清单
  `_manifest.jsonl`）。那是错误的设计：一个技能不该需要另一个技能安装在某个位置才能
  工作。现在本技能自带完整链路，`grep` 全目录已无跨技能引用（本条历史除外）。
  - `scripts/mcp_cache.py` → **`scripts/mcp_landing.py`**：自己读 agent 落盘的载荷，
    自己把数据转成**本技能既有**的格式。
  - `evaluate.py` 的 `--cache-dir` → **`--landed-dir`**；`--allow-partial` 从评测阶段
    移到 **`mcp_landing.py --build`**（截断只在取数载荷这一层判定，评测只读已构建的
    本地 CSV，留在那里既判不准也没有意义）。
  - `load_bars(..., cache_dir=, allow_partial=)` → `load_bars(..., fixtures_dir=)`；
    `cache_provenance()` → **`data_provenance()`**；`data_mode` 取值
    `mcp-cache` → **`landed`**；返回值键 `cache` → `data`。
  - 依赖清单与 `skill.json` 不再指向任何外部技能路径。

### Added

- **本技能自有的取数落点**：`tests/fixtures/raw/<method>__<label>.json` 存 agent 从
  `mcp__pandadata__call_pandadata` 拿回的**原样**载荷；`scripts/mcp_landing.py --build`
  转成 `tests/fixtures/landed/bars_<SYMBOL>.csv`（`date,open,high,low,close,volume`，
  与随仓库发布的合成 fixture 同一套命名与列结构）与 `dominant_<PRODUCT>.csv`
  （`date,contract`），并写 `provenance.json` 记录每个文件来自哪些载荷、是否 partial。
  真实数据因此不会覆盖 `tests/fixtures/` 顶层的合成样例，`--fixture` 与真实数据两条路
  径不会互相污染。
- **截断守卫（本技能内实现，不 import 任何外部模块）**：parquet 通道的载荷若
  `truncated` 为真或 `row_count < total_rows`，`--build` 结构化报错并非 0 退出，
  **且校验全部先于写文件**——拒绝时不会留下半套 landed 目录。`--allow-partial` 可放行，
  但 `provenance.json` 与后续报告的 `data.partial_symbols` / `data_quality_warning`
  都会留下痕迹。JSON 通道（`get_future_dominant`）返回完整数组、没有这些字段，
  缺字段不算截断信号，代码不去发明一个。
- `--verify` / `--inspect` 两个只读诊断入口；`data.skipped_symbols`：被声明却没拿到
  数据的标的现在写进报告，不再只是 stderr 上的一行 `[skip]`（否则样本悄悄变小，
  `partial_symbols: []` 会被误读成"数据都齐了"）。

### Changed

- 主力合约拼接保持迁移前的**逐日归属**语义：某天的 bar 只来那天真正主力的合约。
  旧的按合约 `min..max` 窗口去重会在"同一合约分两段主力"时错误归属，回归用例
  `test_a_date_never_borrows_bars_from_the_wrong_contract` 钉住这一点。
- 覆盖率策略仍是 `error`（默认，缺区间即结构化报错）/ `shrink`（用已覆盖子区间并把
  缺口记进 `coverage_missing` / `missing_contract_segments`）。
- 错误码随实现改名：`cache_not_found`→`landing_not_found`、`shard_unreadable`→
  `payload_unreadable`、`partial_refused`→`payload_truncated`，新增 `payload_empty`、
  `fixture_not_found`、`invalid_arguments`。退出码统一为 0 正常 / 2 用法错误 /
  3 数据不可用。
- 文档中的绝对安装路径清零：`output/frozen_baseline.json` 里记录的行情文件路径改为
  相对技能根目录（安装位置不是溯源信息）。
- `tests/test_docs.py` 新增两条文档守卫：文档不得再描述被删除的跨技能设计，且必须
  写清"agent 调 MCP → 原样落盘 → --build → 评测"这条唯一正确的顺序。

## [0.4.0] — 2026-11-17

### Breaking

- **移除 `panda_data` Python SDK 取数通道。** 脚本里不再有 SDK import、登录流程或
  `init_token` 调用；`load_panda()` / `credentials()` / `credentials_source()` /
  `_fetch_raw_dominant()` 全部删除。
  - **不再需要 Python 3.10+**：SDK 才是 3.10+ 的唯一理由，现在核心与取数读取端都是
    纯标准库，`python>=3.8` 即可（实测系统 Python 3.9 在**不装任何三方包**的情况下
    跑通全部测试）。
  - **不再需要任何凭证环境变量**：`PANDA_DATA_USERNAME` / `PANDA_DATA_PASSWORD` /
    `PANDA_DATA_BASE_URL` 与 `~/.pandadata/pandadata.env` 均不再被读取，报告里也没有
    `credentials_source` 字段了。
  - `evaluate.py` 的 `--panda` 开关被删除，改为 `--cache-dir <path>`；`requirements.txt`
    与 `skill.json` 的 `optional_dependencies` 去掉 `panda-data`。用 `--panda` 的调用方
    需改成 `--cache-dir`（`--fixture` 语义不变）。

### Changed

- **取数改为「agent 经 PandaData MCP → 落本地 cache → 脚本只读 cache」。** 这是环境约束
  决定的形态（MCP 工具只能由 agent 调用，Python 脚本调不到 MCP），动机有三条：
  ① 本环境的脚本没有任何合法在线出口，留着 SDK 就是留着一个跑不通的分支；
  ② SDK 通道的凭证在本环境从未验证通过（见 0.3.0 的 Known gaps），而 MCP 落盘带
  `params` / `request_id` / `sha256` 的 manifest 让"这批数字从哪来"第一次可审计；
  ③ 离线可用性从"要靠测试守住"变成**结构上不可能破坏**——进程内根本没有取数代码。
- 新增 `scripts/mcp_cache.py`：cache 读取端，校验分片完整性（文件存在、sha256、行数、
  列集）、区间覆盖与截断标记。`partial: true`（被 MCP 单次 2000 行上限截断）的分片
  **默认拒绝**，只有显式 `--allow-partial` 才放行，且放行后 `data.partial_symbols` 与
  `data_quality_warning` 会标出来。可复用的报错码：`cache_not_found` /
  `shard_unreadable` / `partial_refused` / `coverage_missing` / `bad_bar_row`。
- `data_loader.py` 只换输入，不换算法：主力换月与未复权连续价拼接仍在脚本内
  （`_stitch_dominant`）。取数写入端**不复制进本技能**，统一指向
  `skill-quant-data-pipeline/scripts/fetch_pandadata_mcp.py`。
- `evaluate.py`：`--fixture` / `--cache-dir` 二选一（不给就报错而不是猜）；报告新增
  `data` 段（cache_dir、逐标的分片与 request_id、partial/shrunk 清单）；标的全部无数据时
  退出码 2，不再输出半空报告。
- 文档全面改为 MCP-only（中英双份）：删掉凭证导出示例、`pip install panda-data`、
  `panda_data login failed` / `ModuleNotFoundError: panda_data` 排障条目，替换为
  「未登录 → Settings → PandaData → Login」「无权限 → 按返回 `message` + 购买页处理，
  不重试、不换厂商」。新增 `references/mcp-data.md`。
- **README 结果数字按实跑更正**：A 组（fixture）此前写 `−0.0032, CI [−0.0096, 0.0]`，
  实跑是 `−0.018527, CI [−0.028301, −0.008560], n=10`；并说明判 `inconclusive` 的原因是
  **n=10 未到 12 笔门槛**，而不是 CI 跨 0（该 CI 两端均为负）。
- B 组（真实行情）的旧数字标注为**未在本版本复现**：它们由已删除的 SDK 通道产出，本迁移
  环境不执行真实取数，因此不假称已验证，只给出可复现步骤。

### Fixed

- **主力换月的合约归属**：旧实现按每个合约主力日的 `min..max` 窗口取数再按日期去重
  （`keep="first"`），当同一合约分两段主力（A→B→A）时，中间那几天会被错记成 A 的 bar。
  现在日期→合约一律以 `get_future_dominant` 的映射为准。
- 完整性错误（`shard_unreadable`）不再被包装成 `coverage_missing`，也不会被
  `--allow-partial` / `--coverage shrink` 跳过：污染的分片是"不可信"，不是"少一点数据"。
- `roll_count` 改为统计实际拼接序列上的换月次数（A→B→A 记 2 次，原先记 1 次）。

### Added

- `tests/test_mcp_cache.py`（27 例）：覆盖 cache 读取端全部拒绝路径——无 manifest、
  分片缺失、sha256 不符、行数不符、截断拒绝与显式放行、覆盖不足与 `shrink`、
  空价拒绝、合约归属回归；并**结构性断言** `scripts/` 内不存在任何取数出口。
- `tests/test_docs.py`（7 例）：README 的 fixture 结果表、中英双份 edge 数字、文档写死的
  用例数、`skill.json` 与 CHANGELOG 版本一致性，全部由**真实运行**推导，防止再出现
  「文档绿灯而数字是错的」这类假验证。
- 用例总数 74 → 108（`test_ruler.py` 74 + `test_mcp_cache.py` 27 + `test_docs.py` 7）。
  历史条目（含 0.3.0 的「数据双通道」与「未完成凭证验证」）照原样保留。

### Known gaps

- 本版本**没有**新的真实行情结果：MCP 取数需要 agent 会话与有效权限，不在本次迁移的执行
  范围内。README B 组表格待按 `references/mcp-data.md` 第 1–4 节重测后填写。
- cache 的默认目录取 `<skill>/data/raw/mcp_cache`，该目录不入库（`.gitignore`）；
  跨项目复用同一份 cache 需要显式传 `--cache-dir`。

## [0.3.0] — 2026-11-13

### Added

- **开跑前范围声明**（`scripts/scope.py`）：`declare_scope()` 只读输入生成 `output/scope_declaration.json` 并计算 `scope_hash`，**在任何成交发生之前**落盘。满足「品种或接口不支持时**事先**明确等价回放范围」。
- **范围校验**：`verify_scope()` 比对声明与实际（品种、成交区间、未映射规则），不符写入 `violations`；`honoured=false` 时结论作废。
- **运行时 applicability**：`applicability()` 在拿到 `scope` 时按本次运行生成，不再输出通用模板文本。新增 `replay_equivalence` 段，明确「本实现是日线回放，不是期货模拟赛撮合」，并列出等价成立的理由与失效情形。
- CLI 新增 `--commission-bps` / `--slippage-bps` / `--min-trades`，成本与门槛进入声明与 `scope_hash`。
- 新增 7 个测试（声明稳定性、未映射规则前置、越界检测、清白运行），总数 74。

### Changed

- **README 措辞更正**：B 组结果原写「2024 全年 242 根日线」，容易被读成全年都有成交。实际取数跨全年，但成交区间是 2024-01-09 ~ 2024-03-12。已改为分行列出「取数范围 / 实际成交区间」，并说明这不构成跨行情周期的长期检验。
- `references/api_guide.md` 与 `references/validation.md` 同步改为「开跑前声明 + 跑完校验」。

### Known gaps

- 与**期货模拟赛**的差异已明确写入 `replay_equivalence.what_this_is_not`，但本版本仍未接入任何模拟赛平台；日线回放是等价替代的声明，不是模拟赛本身。
- 观点样本仍是手写 fixture，不是真实的单一来源历史观点。

## [0.2.2] — 2026-11-13

### Fixed

- **「涨到 / 跌到」不识别为目标位**：形如「螺纹钢涨到4100」「铁矿石跌到800」的表述原先整条落 `none`。已补目标词典：中英文各 4–6 个变体（涨到/涨至/升至/反弹至，跌到/跌至/降至/回落至，rises to / rallies to / climbs to / falls to / drops to / slides to）。
  - 修复后：「螺纹钢涨到4100，跌破3850止损」→ `partial RB long`，`exit close >= 4100`，`stop close < 3850`。

### Added

- `tests/test_ruler.py` 新增 2 个用例：涨到/跌到目标识别、A股名称无符号的行为固化。测试总数 67。

### Clarified

- **A股名称不在品种白名单内，这是既有设计而非缺陷**。实测 `中科星图` = `688568.SH`、`寒武纪` = `688256.SH`，抽取层能把规则完整解出（方向、目标、止损、期限），但 `instrument` 为空 → `testability = none`。A股需要单独的代码索引与 T+1 / 涨跌停 / 停牌回测层，见 README「已知局限」。

## [0.2.1] — 2026-11-13

### Fixed

- **配对基线口径错误（影响所有多头结论）**：`baseline_return` 原先用规则自己的**出场日期**计算持有收益，导致多头规则的基线与交易完全重合，`edge` 恒等于 0。实测 12 笔真实成交中，6 笔多头 edge 全为 `±0.0000`，掩盖了真实差异。
  - 修复：基线改为按**事先固定的期限窗口**（`entry_date` → `horizon_end_date`）计算；规则的止损/止盈只能让交易提前结束，不能改变基线。
  - 交易记录新增 `horizon_end_date` / `horizon_end_price`，使"实际出场"与"期限终点"可核对。
  - 修正后真实数据结果：edge `+0.0122`，CI `[−0.0045, 0.0285]`（原误报 `+0.0162`，CI `[0.0021, 0.0328]`）。
- **「两周看4100」抽不出止盈位**：目标位词典不认光秃秃的 `看+数字`，已补 `看(到|至|高至)?NUM`。
- **`references/validation.md` 存在未核对的断言**：曾把 5 条空头样本一律描述为"已被证伪"，实际其中 4 条盈利。已按真实回测输出改为盈亏对照表，并注明该判定依赖所选行情区间。

### Added

- 回归测试：`test_baseline_spans_the_horizon_not_the_actual_exit`、`test_bare_target_verb_is_recognised`、`test_a_share_news_paragraph_is_not_ruleable`。测试总数 65。

---

## [0.2.0] — 2026-11-13

### Added

- **英文支持**：品种别名（`rebar` / `iron ore` / `copper` / `crude oil` …）、方向词（`bullish` / `bearish` / `long` / `short` / `buy` / `sell`）、期限（`two weeks` / `next month` / `three months` …）、价位语义（`holds` / `breaks below` / `targets` / `stop-loss` / `pullback`）全部并入同一套词典。
- **英文句子分句**：独立的正则，避免把 `78000.5` 这类小数从中间切断；中英混写时按中文规则分句。
- **词边界匹配**：ASCII 词汇按 `\b` 匹配，`long` 不再命中 `longer`，`corn` 不再命中 `corner`。
- **英文否定**：`not / no / never / avoid / won't` 等识别为否定，使 `not bearish` 正确翻转成多头。
- **英文标注集**：`tests/fixtures/labels_en.json`，10 条样本，7 个字段 exact-match 均 1.00。
- **测试**：新增 12 个英文用例（含词边界、小数、混写、否定、期限变体），总数 62。

### Changed

- `references/validation.md` 增加语言覆盖要求，复现命令同步加入英文标注评分。
- 版本号统一升至 `0.2.0`（`skill.json` / `agents/openai.yaml` / `VERSION`）。

### Unchanged

- 中文行为零回归：中文标注集 exact-match 仍为 1.00，`config_hash` 因抽取器版本变化而更新。

---

## [0.1.0] — 2026-11-12

### Added

- **抽取层**：`scripts/build.py` 提供 `run()` / `validate_input()`，把一段观点按句拆解为六字段规则（标的 / 方向 / 进场触发 / 期限 / 止损 / 止盈）。
- **品种映射**：`scripts/common.py` 内置内盘商品与股指期货白名单，支持 `主力/主连/连续` 识别与显式合约代码。
- **方向与否定**：识别多空措辞、否定词翻转（「不看空」→ 多）、无措辞时按目标位推断并标记 `direction_inferred`。
- **价位语义**：区分触发位（站稳/突破/跌破）、目标位（上看/目标）、失效位（止损）、回踩进场位。
- **不可规则化分类**：`testability` 四值（`full` / `partial` / `neutral` / `none`），`none` 进 `unruleable` 并计入 `ruleable_share`。
- **冻结默认策略**：`DEFAULT_POLICY`（`frozen-1`），补全项逐条记入 `assumed`，并计入 `config_hash`。
- **标注评分**：`scripts/annotate.py` 逐字段输出 precision / recall / exact-match，`null` 标签下预测值计为假阳性。
- **无未来函数回测**：`scripts/backtest.py` 仅用 `published_at` 之后的 bar，下一根 bar 开盘成交，缺失时间戳拒跑。
- **配对基线**：默认 `hold`（同标的同日期买入持有），可选 `cash`；成本参数默认双边 3bp + 2bp 滑点。
- **三值判定**：`decide_verdict` 使用固定阈值（≥12 笔 + bootstrap CI），负结果视为合格产出。
- **端到端验收**：`scripts/evaluate.py` 一次跑完抽取 → 标注评分 → 回测 → 报告，写 `output/frozen_baseline.json`。
- **数据双通道**：`scripts/data_loader.py` 支持 `panda_data`（`get_future_dominant` / `get_future_daily`）与本地 CSV，失败抛 `DataUnavailable`，不静默降级。
- **测试**：`tests/test_ruler.py` 50 个用例，覆盖正常输入、边界值、异常输入、无未来函数、成本核算、判定逻辑。
- **交付文件**：`SKILL.md`、`README.md`、`README.en.md`、`LICENSE`（GPL-3.0 全文）、`INSTALL.md`、`requirements.txt`、`skill.json`、`CHANGELOG.md`、`references/`（schema / api_guide / validation）、`agents/` 三件套。

### Known gaps

- 抽取为词典 + 正则实现，未接入 LLM；反讽、长距离指代、生僻比喻会落到 `none` 或产生 `ambiguity`。
- 内置 fixture 仅 16 条观点、2 个品种、10 笔成交，样本量低于判定门槛，`verdict` 为 `inconclusive`，只能证明链路可运行。
- panda_data 真实数据通道已实现但未在本环境完成凭证验证（登录返回「用户未注册」），需在实际账号下复跑 `evaluate.py --panda`。
- 组合层面的资金竞争未建模。