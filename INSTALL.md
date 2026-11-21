# 安装指南（INSTALL）

`skill-opinion-to-ruler` 是纯 Python skill，核心功能零三方依赖。

## 通用前置

| 项 | 要求 |
|---|---|
| Python | 3.8+（核心与取数读取端都是纯标准库；0.4.0 之前那条取数通道的 3.10+ 要求已随该版本移除） |
| 包管理器 | pip |
| 系统 | macOS / Linux / Windows（WSL 亦可） |

```bash
cd skill-opinion-to-ruler
python3 -m pip install -r requirements.txt   # 核心为空依赖，可直接跳过
```

**没有可选依赖，也不需要任何凭证，也不依赖任何其他技能。** 本技能不联网：MCP 工具只能由
agent 调用，所以真实行情由 agent 取回、原样落到**本技能自己的**落点目录，脚本只读构建出来的
本地文件。

```bash
# ①② 由 agent 执行（脚本里没有这条出口，也不该有）
#    调 mcp__pandadata__call_pandadata(method=get_future_daily / get_future_dominant, params=...)
#    把返回载荷原样写成 tests/fixtures/raw/<method>__<label>.json

# ③ 构建成本技能自有格式的 CSV（截断守卫在这一层）
python3 scripts/mcp_landing.py --build

# ④ 之后评估只读构建产物
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231
```

未登录时在 **Settings → PandaData → Login** 处理；不要在脚本里配账号，也不要向用户索要密码。
契约与失败处理见 `references/mcp-data.md`。

**从 git 克隆得到的是完整交付物**：验收锚点 `baselines/frozen_baseline.json`、
`baselines/rb-i-2024H1-real.json` 与 `baselines/scope_declaration.json` 随包入库，
`tests/fixtures/bars_{RB,I}.csv` 与 `tests/fixtures/labels*.json` 也在包里，所以克隆后立刻可以跑
`python3 scripts/compare_baseline.py` 逐字段复核冻结基线（见「验证安装」第 4 步）。
`evidence/rb-i-2024H1/` 同时提供原 12 例的派生真实行情、案例/规则/标签与无条件复跑入口；
观点文本为合成夹具，真实的是行情，原始 MCP 响应仍不进包。
`output/` 不在包里，那是运行期重新生成的落点，不是缺失。

---

## 1. Claude Code

```bash
git clone git@github.com:quantskills/skill-opinion-to-ruler.git
cd skill-opinion-to-ruler
claude
```

在会话内直接说「用 skill-opinion-to-ruler 抽取这段观点」，Claude 会读取根层 `SKILL.md`。无需额外注册：Claude Code 以仓库根目录的 `SKILL.md` 作为入口。

验证：

```bash
python3 scripts/build.py
```

## 2. Codex (OpenAI)

适配器位于 `agents/openai.yaml`。

```bash
cd skill-opinion-to-ruler
codex
```

在会话中引用该文件，或把仓库放到 Codex 的 skills 搜索路径下。示例提示：

```
Read agents/openai.yaml, then run scripts/build.py with the demo document.
```

## 3. Cursor

适配器位于 `agents/cursor-rule.mdc`。

```bash
mkdir -p .cursor/rules
cp agents/cursor-rule.mdc .cursor/rules/opinion-to-ruler.mdc
```

重启 Cursor，在 Rule 面板确认 `opinion-to-ruler` 已加载（`alwaysApply: false`，按需触发）。

## 4. Hermes

适配器位于 `agents/portable-loader.md`。

```bash
# 将仓库放入 Hermes 的 skill 目录，或直接把 portable-loader.md 作为说明喂给 Hermes
cat agents/portable-loader.md
```

Hermes 通过该文件的 Quick Start 与 Agent Integration 段直接获得调用方式。

## 5. OpenClaw

由 `agents/openai.yaml` + `agents/portable-loader.md` 共同覆盖。

```bash
# OpenClaw 读取 skill 目录下的 agents/ 与 SKILL.md
python3 -c "import yaml,sys; print(yaml.safe_load(open('agents/openai.yaml'))['info']['title'])"
```

---

## 验证安装

```bash
# 1. 抽取自检
python3 scripts/build.py

# 2. 标注评分自检
python3 scripts/annotate.py tests/fixtures/labels.json

# 3. 端到端离线验收
python3 scripts/evaluate.py --fixture

# 4. 冻结基线核对（只读）：随包发布的锚点在 baselines/，不在 output/
ls baselines/frozen_baseline.json baselines/scope_declaration.json
python3 scripts/compare_baseline.py

# 5. 测试套件
python3 -m pytest tests/ -v
```

各步均应成功（退出码 0），且全程无需联网、无需凭证。若第 3 步报 `DataUnavailable`，说明
`tests/fixtures/bars_*.csv` 缺失。

第 4 步是从 git 安装后**必须能跑通**的一条：`baselines/` 随包发布，重跑的数字与它逐项比对。
如果这里退出码是 1，说明代码改了但冻结基线没跟着改（或反过来）——报错会指名哪个字段变了、
旧值与新值各是多少；**不要为了让它变绿去改 `baselines/` 里的数字**，先查实现为什么变了。
若报 `frozen reference not found`，说明拿到的是不完整的包（锚点没入库）。

原真实 12 例可直接从随包派生证据验收（无需原始载荷）：

```bash
python3.11 -m pytest tests/test_baseline_guard.py -k shipped_evidence -q
```

如持有原始载荷，还可选做 `raw -> landed -> evaluate` 全链路复核（先由 agent 按上面的 ①② 落盘）：

```bash
python3 scripts/mcp_landing.py --verify    # 只读诊断：载荷齐不齐、有没有被截断
python3 scripts/mcp_landing.py --build     # 落盘载荷 → landed CSV + provenance.json
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start 20240101 --end 20241231
OPINION_TO_RULER_RAW_DIR=tests/fixtures/raw python3.11 -m pytest tests/test_baseline_guard.py -k raw_payloads -q
```

## 常见问题

报错分三层，取数与评测的退出码统一为 **0 正常 / 2 用法错误 / 3 数据不可用**。
冻结基线核对另用 **1 表示"数字与锚点不一致"**（`compare_baseline.py`，以及
`evaluate.py --check-baseline`）：这是验收结论，不是崩了；`2` 留给锚点缺失或用法错误，
免得"包里没有锚点"被误读成"数字变了"。

| 现象 | 处理 |
|---|---|
| `landing_not_found` | 还没有任何落盘载荷：按上文 ①② 由 agent 取数并原样写入 `tests/fixtures/raw/`，或改用 `--fixture` |
| `payload_unreadable` | 存进去的不是原样返回体（转述、摘要、手抄几行、JSON 被改）：重新落盘，**不要手改行数据** |
| `payload_empty` | 载荷解析正常但零行：区间可能落在非交易日，或参数写错，核对后重取 |
| `payload_truncated` | parquet 通道的预览被截断（`truncated: true` 或 `row_count < total_rows`）：切小请求重取；确实要在残缺数据上试跑才给 `--build` 加 `--allow-partial`（产物会留 `partial` 标记） |
| `bad_bar_row` | 行缺日期或价格为空/为 0：重取，`fields` 至少含 `date,open,high,low,close` |
| `invalid_arguments` | 命令行写错（如 `--start` 不是 8 位 `YYYYMMDD`） |
| `fixture_not_found` | 本地没有该标的的文件：补取，或确认你该用 `--fixture` |
| `coverage_missing` | 文件没覆盖请求区间：按报错里的缺口补取，或显式 `--coverage shrink`（报告会记录降级） |
| `unrecognized arguments`（`evaluate.py` 上提到某个目录开关） | 指向**数据目录**的旧开关已删除：行情来源仍然只有 `--fixture` 或 `--landed-dir <path>` 二选一，其余开关（`--check-baseline`、`--baseline-output`、`--scope-output`、成本与门槛参数）都不决定数据来源，也不会去联网 |
| `unrecognized arguments: --allow-partial`（`evaluate.py` 上） | `--allow-partial` 只属于 `mcp_landing.py --build`：截断是取数载荷的属性，不是回测的开关 |
| MCP 未登录 / HTTP 401 / `reauth_required` | 停下，到 Settings → PandaData → Login；不循环重试，不索要密码 |
| MCP 返回 `data_permission_required` | 按返回的 `message` 提示到 https://www.pandaaiquant.com/ 购买该数据权限；**不要重试该方法，也不要改用其他厂商** |
| `DataUnavailable: CSV missing columns` | CSV 表头须含 `date,open,high,low,close` |
| `BacktestError: published_at is required` | 观点缺发布时间；补 `published_at` 后再回测 |
| 抽取结果大量 `none` | 观点缺少标的或方向；属预期行为，见 `references/validation.md` |