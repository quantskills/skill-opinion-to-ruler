# PandaData MCP 取数与落盘（本技能的数据访问契约）

本技能**没有**任何在线取数代码：脚本里不存在任何取数组件 import、没有登录流程、不读任何凭证环境
变量、没有网络出口。原因是环境性的：**MCP 工具只能由 agent 调用，Python 脚本调不到 MCP**。
数据到达的唯一方式是"文件中介、单向"。

## 1. 唯一正确的操作顺序（agent 照此执行）

```
① 调工具：mcp__pandadata__call_pandadata(method=get_future_daily / get_future_dominant, params=...)
② 落盘：把返回载荷**原样**写入 tests/fixtures/raw/<method>__<label>.json
③ 构建：python3 scripts/mcp_landing.py --build
         → tests/fixtures/landed/bars_<SYMBOL>.csv
         → tests/fixtures/landed/dominant_<PRODUCT>.csv
         → tests/fixtures/landed/provenance.json
④ 评测：python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start ... --end ...
```

第 ③④ 步只读文件，不联网。`--fixture` 走的是仓库顶层的合成样例
（`tests/fixtures/bars_RB.csv`），与第 ①② 步无关。落盘目录与产物目录的约定同时写在
`tests/fixtures/raw/README.md` 与 `tests/fixtures/landed/README.md` 里，三份文档不得互相矛盾。

| 角色 | 谁做 | 说明 |
|---|---|---|
| 取数 | agent | 只有 agent 能调 MCP 工具 |
| 落盘 | agent | 载荷原样写盘，不转述、不摘要、不手抄 |
| 构建 / 读取 / 回测 | 脚本 | 只读本地文件，零凭证零网络 |

## 2. 两个响应通道与各自的完整性语义

| 通道 | 方法 | 载荷形态 | 完整性 |
|---|---|---|---|
| parquet（预览） | `get_future_daily` | 对象，行在 `rows` / `data` / `records` 之一 | 单次上限 **2000 行**，超出**静默截断** |
| JSON（完整） | `get_future_dominant`、`get_trade_cal` | 完整数组 | 无上限字段，返回即为全量 |

**截断只发生在 parquet 通道。** 判据只有两条，都来自载荷自身：

- `truncated: true`；
- `row_count < total_rows`（预览被切但没人写 flag 的那种）。

JSON 通道**不带这些字段**，所以"缺字段"不是截断信号，本技能不去发明一个。
`preview_rows` 是**请求参数**，不是行数，绝不能拿来当完整性判据。

日线是 `1 标的 1 日`，所以一次调用控制在 **≤5 个合约 × ≤1 年**，宁可多切几片；拿不准是否
被截断就切小范围（更短区间 / 更少标的 / 更少 `fields`）重取。

## 3. 落盘命名约定

`<method>__<label>.json`，双下划线分隔，`<method>` 必须是真实 MCP 方法名：

| 落盘文件 | MCP 调用（实测签名） | 通道 |
|---|---|---|
| `get_future_daily__<CONTRACT>[_<起>_<止>].json` | `get_future_daily(start_date, end_date, symbol?, fields?)` | parquet |
| `get_future_dominant__<PRODUCT>.json` | `get_future_dominant(underlying_symbol?, start_date, end_date)` | JSON |
| `get_trade_cal__<EXCHANGE>.json` | `get_trade_cal(start_date, end_date, exchange?, is_trading_day?)` | JSON |

行归组依据：`get_future_daily` 的行按 `symbol` 归到 `bars_<SYMBOL>.csv`，
`get_future_dominant` 的行按 `underlying_symbol` 归到 `dominant_<PRODUCT>.csv`，
落盘时不要裁掉这两列。`get_trade_cal` 的日期字段是 `nature_date`；解析器认它，
但 `--build` 目前只转换上面两个期货方法（日历不是出 bar 所必需的）。

## 4. 构建产物（本技能既有格式）

| 文件 | 列 | 来自 |
|---|---|---|
| `tests/fixtures/landed/bars_<SYMBOL>.csv` | `date,open,high,low,close,volume` | `get_future_daily` 载荷 |
| `tests/fixtures/landed/dominant_<PRODUCT>.csv` | `date,contract` | `get_future_dominant` 载荷 |
| `tests/fixtures/landed/provenance.json` | — | 每个文件来自哪些载荷、请求区间、是否 partial |

列结构与仓库顶层的合成 `tests/fixtures/bars_RB.csv` 完全一致，同一套
`load_csv` / `--fixture` / 回测代码不用改就能读真实数据。真实数据写在 `landed/` 子目录，
是为了**不覆盖**顶层合成样例——两条路必须能分辨。

`scripts/mcp_landing.py` 命令行：

| 项 | 值 |
|---|---|
| 模式（互斥，必选其一） | `--build` / `--verify`（只读诊断） / `--inspect <payload.json>` |
| `--raw-dir` | 落点目录，默认 `tests/fixtures/raw` |
| `--out-dir` | 产物目录，默认 `tests/fixtures/landed` |
| `--start` / `--end` | `YYYYMMDD`，只保留窗口内的行 |
| `--symbol` | 只构建该合约，可重复 |
| `--allow-partial` | 放行不完整载荷（见第 5 节） |
| `--json` | 机器可读输出 |

`--build` 幂等：产物不含时间戳，重跑覆盖即可。同一 `(标的, 日期)` 被两份载荷给出不同值时
**保留先出现的一份**并在 `warnings` 里说明，不平均、不静默覆盖。窗口外的行计入
`rows_outside_window`。


## 5. 一次真实回测到底要取几次数（实测，别照第 1 节字面理解）

第 1 节那条 4 步流程**不是一步就能出 verdict 的**：`evaluate.py` 按 `--scope` 声明的**品种**
找文件，所以要跑通一个品种，至少需要

1. `get_future_dominant(underlying_symbol=[<品种>])` → 建出 `dominant_<品种>.csv`；
2. `get_future_daily(symbol=[<该期间每一个主力合约>])` → 建出每个**具体合约**的 `bars_<合约>.csv`。

只落一条连续主力（例如 `bars_RB_DOMINANT.SHF.csv`）**不会**被当成该品种的数据，而是被拒绝：

```
[skip] RB: fixture_not_found: 找不到主力合约映射文件：…/dominant_RB.csv
[warn] 2 declared symbol(s) were NOT served and are missing from these numbers: I, RB —
       the sample is smaller than declared, fix the data and re-run
[error] no bars available for any declared symbol; nothing to backtest.
```

这是**期望行为**：宁可不出数，也不拿不足样本硬算 verdict。但也意味着真实重跑的成本是按
品种 × 合约数量级增长的，规划取数预算时按这个算，别按"调一次就行"算。

## 5. 截断守卫与 `--allow-partial` 的留痕路径

`--build` 在**写任何文件之前**完成全部校验：拒绝时不会留下半套 `--out-dir`。

| 情况 | `code` | 处理办法 |
|---|---|---|
| 落点目录不存在 / 里面没有任何 `<method>__<label>.json` | `landing_not_found` | 按第 1 节由 agent 取数落盘 |
| `--out-dir` 不可写（安装态技能目录只读） | `landing_not_writable` | 用 `--out-dir` 指到可写目录，`evaluate.py --landed-dir` 指同一个地方；**不会**悄悄改写到别处 |
| 载荷不是原样返回体（无行字段、JSON 坏、行形态不对） | `payload_unreadable` | 重新调用并原样落盘，禁止手改行 |
| 载荷解析正常但零行 | `payload_empty` | 空结果 ≠ 没数据，核对参数（非交易日？） |
| parquet 载荷不完整（`truncated` / `row_count < total_rows`） | `payload_truncated` | 切小请求重取；确要在残缺数据上试跑才加 `--allow-partial` |
| 行缺日期 / 价格为空或为 0 / 非数值 | `bad_bar_row` | 重取，`fields` 至少含 `date,open,high,low,close` |
| 命令行本身写错（如 `--start` 不是 8 位） | `invalid_arguments` | 用法错误 |
| 本地没有该标的的文件 | `fixture_not_found` | 补取该标的，或改用 `--coverage shrink` |
| 文件存在但没覆盖请求窗口 / 主力日缺 bar | `coverage_missing` | 补缺口后重建，或显式 `--coverage shrink` |

退出码：**0 正常 / 2 用法错误 / 3 数据不可用**。

`--allow-partial` 放行后必须留痕，一路传到底：`provenance.json` 里 `partial: true` +
`partial_payloads: [<file>, ...]`（逐文件，不是一刀切），评测报告里进
`data.partial_symbols` 并触发 `data_quality_warning`。残缺数据不能支撑正式结论。

## 6. 实测方法签名（不要照搬记忆里的签名）

调用顺序固定：`auth_status` → `search_methods` → `get_method_doc` → `call_pandadata`。

| 方法 | 参数 | 通道 | 关键返回字段 |
|---|---|---|---|
| `get_future_daily` | `start_date`, `end_date`（必填）、`symbol?`、`fields?` | parquet | `date`, `symbol`（行身份）, `open/high/low/close`, `volume` |
| `get_future_dominant` | `start_date`, `end_date`（必填）、`underlying_symbol?` | JSON | `date`, `symbol`, `trading_code`, `underlying_symbol` |
| `get_trade_cal` | `start_date`, `end_date`、`exchange?`、`is_trading_day?` | JSON | `nature_date`（日期字段） |

## 7. 主力连续序列的语义

- **逐日归属**：某个交易日的 bar 只取**那天真正主力**的合约，由 `dominant_<PRODUCT>.csv`
  决定；不按合约自身的 `min..max` 窗口去重（那会在同一合约分两段主力时错误归属）。
- **未复权**：拼接用的是各合约自己的实价，所以观点里的价位确实是有人交易过的价格。
  代价是跨换月的价格连续性只是近似，换月当天的基差跳空原样保留，`roll_count` 记在
  provenance 与报告里，并写进 `applicability`。
- **缺腿是失败，不是静默丢段**：主力映射要求的合约日线缺失时，默认报
  `coverage_missing`；显式 `--coverage shrink` 才降级，缺口记进
  `missing_contract_segments` / `missing_dates`，报告里进 `data.shrunk_symbols`。

## 8. 报告里与取数有关的字段

`data_mode` 取值 `fixture` / `landed`（评测只读已构建的本地文件，`--allow-partial`
属于第 ③ 步，评测阶段没有这个开关）。`data` 段：

| 字段 | 含义 |
|---|---|
| `data.symbols.<标的>` | 该标的的溯源：`method` / `files` / `source_payloads` / `partial` / 请求与实际窗口 |
| `data.partial_symbols` | 由不完整载荷构建出来的标的 |
| `data.shrunk_symbols` | 窗口被缩到已覆盖子区间的标的 |
| `data.skipped_symbols` | 声明了却没有任何本地文件能服务的标的（带错误码）——样本因此比声明的小 |
| `data.all_complete` | 以上三者皆空才为真 |
| `data.landed_dir` / `data.coverage_policy` | `landed` 模式下记录的目录**名**与覆盖策略 |
| `data.landed_dir_outside_skill` / `landed_dir_note` | 落点在技能目录之外时为真，并说明记录的是名称而不是路径 |
| `data_quality_warning` | 只要 partial / shrunk / skipped 任一非空就出现 |

`data.skipped_symbols` 是必需的：否则一个标的静默消失后，`partial_symbols: []` 会被误读成
"数据都齐了"，而实际上样本已经悄悄变小。

技能根目录以内的文件路径一律记为**相对技能根目录**（安装位置不是溯源信息）；技能目录之外的
显式 `--landed-dir` 及其文件**只记名称**，并置 `landed_dir_outside_skill: true`。
原因很实际：随包发布的锚点里若写着取数那台机器的**家目录或临时目录绝对路径**，换一台机器
就全部对不上，而这些报告本来就是要给别人复现的。重跑真实锚点时把落点目录命名为 `real_landed`，
记录下来的名称才对得上 `baselines/rb-i-2024H1-real.json`。

复现守卫（授权载荷不随包发布，缺目录时该用例**跳过**而不是假装通过）：

```bash
OPINION_TO_RULER_RAW_DIR=/path/to/raw python3.11 -m pytest tests/test_baseline_guard.py -k reproduces
# 或直接把载荷放在 tests/fixtures/raw/（.gitignore 已排除，README.md 说明约定）
```

手工放进 `landed/` 的
`bars_*.csv`（没有 `provenance.json`）也能读，但来源不可核验，报告里带
`provenance_missing: true`。

## 9. 失败处理（不要绕路）

| 现象 | 做法 |
|---|---|
| 未登录 / `reauth_required` / HTTP 401 | **停下**，让用户打开 Settings → PandaData → Login。不循环重试，**永远不要索要密码**。 |
| `error == "data_permission_required"` | 原样转述返回的 `message`，并给出购买页 https://www.pandaaiquant.com/ 。**不要重试该方法**，也不要换厂商。 |
| 返回带 `trial` | MCP 免费试用 5 分钟，`expires_at` 是毫秒时间戳；重连和重试都不会延长。 |
| 载荷被截断 | 按第 2 节切小范围重取；确实只要这一截才用 `--allow-partial`，并接受报告里的 partial 标记。 |
| 超时 / JSON 过大 | 更少合约、更短区间重取，别整市场硬拉。 |
| 载荷与自身声明的行数不符 | 视为污染，重取覆盖该文件；**不要手改行数据**。 |

换厂商（AkShare / Yahoo / Tushare 等）必须由用户明确点名，不得因为取数失败就自动替换。
