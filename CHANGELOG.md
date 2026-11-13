# Changelog

All notable changes to `skill-opinion-to-ruler` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

---

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