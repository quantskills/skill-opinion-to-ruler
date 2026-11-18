# 数据接口（api_guide）

本 skill 的行情一律来自**本地文件**，产出结构完全相同，调用方通过参数选择，绝不静默切换：

| 通道 | 入口 | 来源 |
|---|---|---|
| 落盘构建产物（真实行情） | `load_bars(sym, start, end, fixtures_dir=...)` | agent 经 PandaData MCP 取回载荷后由 `scripts/mcp_landing.py --build` 构建的 CSV |
| 调用方 CSV（离线 / CI） | `load_bars(sym, start, end, csv_path=...)` | 使用者自备的 `date,open,high,low,close[,volume]` |

**脚本内没有任何在线取数出口**：不 import 任何取数组件、不登录、不读凭证环境变量、不开网络连接。
这不是风格选择，而是环境约束——MCP 工具只能由 agent 调用，Python 脚本调不到。

## 1. PandaData MCP + 本技能自有落盘（真实行情通道）

```
① agent: mcp__pandadata__call_pandadata(method=get_future_daily / get_future_dominant, params=...)
② agent: 返回载荷原样写入 tests/fixtures/raw/<method>__<label>.json
③ python3 scripts/mcp_landing.py --build
     → tests/fixtures/landed/bars_<SYMBOL>.csv      (date,open,high,low,close,volume)
     → tests/fixtures/landed/dominant_<PRODUCT>.csv (date,contract)
     → tests/fixtures/landed/provenance.json
④ scripts/data_loader.py → scripts/evaluate.py      # 全部只读
```

| 项 | 值 |
|---|---|
| MCP 方法 | `get_future_daily`、`get_future_dominant` |
| 关键参数 | `start_date` / `end_date`，加 `symbol`（日线）或 `underlying_symbol`（主力映射） |
| parquet 通道上限 | 2000 行；超限是**静默截断**（`truncated: true`、`row_count < total_rows`） |
| JSON 通道 | 返回完整数组，不带上述字段，缺字段不是截断信号 |
| 建议切片 | 日线 ≤5 个合约 × ≤1 年；宁可多切几片 |
| 构建端 / 读取端 | `scripts/mcp_landing.py` / `scripts/data_loader.py`（都是纯标准库） |
| 完整契约 | `references/mcp-data.md` |

### 使用的接口

| 接口 | 用途 | 实测参数 |
|---|---|---|
| `get_future_dominant` | 查每个交易日的主力合约代码 | `start_date`, `end_date`（必填）, `underlying_symbol?` |
| `get_future_daily` | 取具体合约日线，也是唯一的价格来源 | `start_date`, `end_date`（必填）, `symbol?`（可列表）, `fields?` |

主力连续序列的构造方式（**逻辑在脚本里，只有输入换成了本技能的本地文件**）：先用
`get_future_dominant` 拿到逐日主力合约映射，再把各合约自己的 `get_future_daily` 行情按日期拼起来。
日期→合约的归属**以映射表为准**，不会把非主力日的 bar 记到别的合约上。

**为什么不用复权连续序列**：复权会整体平移历史价格。实测 RB 在 2024-01-10 的合约收盘是 3887，
而复权序列给的是 4776。观点里的价位是作者当时看到的实价，用复权价去比较会让 `close > 3850`
这类条件在错误的位置触发。因此本 skill 只用未复权的合约行情。

代价是换月处不连续：主力换月当天，价差会原样保留。这一点写进报告的 `applicability`，不做隐藏。
若要做严格的连续合约回测，需要另接复权序列，并同步调整规则里的价位口径。

### 字段映射

载荷里的列名解析是大小写不敏感、且按候选列回退的（MCP 返回的列顺序不保证稳定）：

| 载荷字段（候选） | 内部 / 产物字段 |
|---|---|
| `date` / `trade_date` / `datetime` / `nature_date` | `date`（`YYYYMMDD`） |
| `symbol` / `code` / `ts_code` / `instrument` | 行身份：归到哪份 `bars_<SYMBOL>.csv` |
| `open/high/low/close` | 同名（空值或 0 一律拒绝，不补零） |
| `volume` | `volume`（缺失记 0） |
| `symbol` / `trading_code` / `dominant_id` / `contract` / `code` | `dominant_<PRODUCT>.csv` 的 `contract` |
| `underlying_symbol` / `underlying` / `product` | `dominant_<PRODUCT>.csv` 的品种名（分组键） |

`get_future_daily` 必须带上 `symbol` 列，否则行无法归到具体合约；`get_future_dominant`
落盘时不要裁掉 `symbol` 与 `underlying_symbol`。

### 构建端与读取端会拦什么

全部是结构化报错（带 `code` 与 `hint`），且都是 `DataUnavailable` 的子类，所以旧的
`except DataUnavailable` 依然兜得住。`--build` 的校验**全部先于写文件**：拒绝时不会留下
半套 `landed/` 目录。

| 情况 | 报错 | `code` |
|---|---|---|
| 落点目录不存在 / 里面没有任何载荷 | `RawDirMissing` | `landing_not_found` |
| 载荷不是原样返回体（读不出行、JSON 坏、形态不对） | `PayloadUnreadable` | `payload_unreadable` |
| 载荷正常但零行 / 过滤后无可用行 | `PayloadEmpty` | `payload_empty` |
| parquet 载荷不完整且未给 `--allow-partial` | `PayloadTruncated` | `payload_truncated` |
| 行缺日期、价格为空/为 0、价格列非数值 | `BarRowError` | `bad_bar_row` |
| 产物落点不可写（**安装态技能目录是只读的**） | `OutputNotWritable` | `landing_not_writable` |
| CSV 缺列 / 坏行 / 零行（调用方自备行情直接不可用） | `DataUnavailable` | `data_unavailable` |
| 命令行写错（如日期不是 8 位） | `BadArguments` | `invalid_arguments` |
| 本地没有该标的的文件 | `FixtureNotFound` | `fixture_not_found` |
| 文件存在但不覆盖请求窗口 | `CoverageError` | `coverage_missing` |

退出码：**0 正常 / 2 用法错误 / 3 数据不可用**。`--allow-partial` 放行不完整载荷时，
`provenance.json` 会留下 `partial: true` + `partial_payloads`，评测报告据此写
`data.partial_symbols` 与 `data_quality_warning`——截断数据不能支撑正式结论。

### 调用示例

```python
from data_loader import load_bars

loaded = load_bars("RB", "20240101", "20241231",
                   fixtures_dir="tests/fixtures/landed")
print(loaded["source"])           # "landed"
print(loaded["data"]["method"])   # "get_future_dominant+get_future_daily"
print(loaded["data"]["partial"])  # 截断标记，必须进报告
```

## 2. 调用方 CSV（离线通道）

用于无网络、CI 或自带数据的场合。`--fixture` 走的就是这条：`tests/fixtures/bars_*.csv`
是随仓库发布的**合成**样例，列结构与 `--build` 的产物完全一致，两条路径写在不同的目录里，
所以真实数据不会覆盖合成样例，也不会互相污染。

文件要求：表头为 `date,open,high,low,close[,volume]`，`date` 为 `YYYYMMDD` 或 `YYYY-MM-DD`。

```python
loaded = load_bars("RB", "20240101", "20241231", csv_path="tests/fixtures/bars_RB.csv")
print(loaded["source"])   # "csv"
```

`load_csv` 会校验列缺失、数值可解析、非空行；任何一条不满足都抛 `DataUnavailable` 并指出具体原因。
手工放进 `landed/` 的 CSV（没有 `provenance.json`）也能读，但来源不可核验，报告里带 `provenance_missing: true`。
## 3. 观点文本输入

观点文本不来自行情接口，由调用方提供。契约见 `references/schema.md`。

必备字段：

| 字段 | 必需 | 说明 |
|---|---|---|
| `text` | 是 | 观点原文 |
| `published_at` | 回测必需 | ISO-8601，抽取阶段可为 null |
| `id` | 否 | 缺省 `doc001` |
| `source` | 否 | 来源标识 |

## 4. 合法性与时间戳前提

- 观点来源必须**合法可用**：公开网页、公开报告、获得授权的终端数据。本 skill 不提供任何抓取实现，也不内置任何来源。
- 时间戳必须是**首次发布时间**，不是最后编辑时间。若来源只能给出编辑时间，必须在上游显式修正，不能靠本 skill 猜。
- 同一观点被多处转载时，应在上游去重，只保留首次发布那条。本 skill 不做跨来源去重，重复输入会被当成多条独立观点。
- 覆盖要求：样本必须包含**沉默（未表态）、反转（否定/修正）、错误观点**，不能只留命中的。

## 5. 市场范围

| 项 | 范围 |
|---|---|
| 支持 | 内盘商品期货、股指期货（日线） |
| 品种映射 | 白名单，见 `scripts/common.py::INSTRUMENTS` |
| 不支持 | 表外品种、外盘合约、期权、股票（本版本） |
| 频率 | 日线，收盘口径 |

期货模拟赛核验时，若某品种或接口不可用，应在**开跑之前**生成范围声明写死等价回放范围（本次运行的产物落 `output/scope_declaration.json`；随包发布的冻结副本在 `baselines/scope_declaration.json`，由 `scripts/compare_baseline.py` 逐字段核对），再执行回测，而不是跑完再挑范围。`scripts/scope.py` 实现了这个顺序：

1. `declare_scope()` 只读输入（观点、参数、冻结配置），看不到任何成交；
2. 声明落盘并计算 `scope_hash`；
3. 回测执行；
4. `verify_scope()` 比对"声明的范围"与"实际发生的范围"，不符记为 violation。

报告中 `scope_verification.honoured` 为 `false` 时，结论作废。