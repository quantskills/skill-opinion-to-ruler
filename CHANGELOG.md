# Changelog

All notable changes to `skill-opinion-to-ruler` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

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