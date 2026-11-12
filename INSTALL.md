# 安装指南（INSTALL）

`skill-opinion-to-ruler` 是纯 Python skill，核心功能零三方依赖。

## 通用前置

| 项 | 要求 |
|---|---|
| Python | 3.8+（核心）；使用 panda_data 通道需 3.10+ |
| 包管理器 | pip |
| 系统 | macOS / Linux / Windows（WSL 亦可） |

```bash
cd skill-opinion-to-ruler
python3 -m pip install -r requirements.txt   # 核心为空依赖，可直接跳过
```

可选依赖（仅 `--panda` 真实行情需要）：

```bash
python3 -m pip install "panda-data==1.0.6"
export PANDA_DATA_USERNAME=<your_username>
export PANDA_DATA_PASSWORD=<your_password>
```

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

# 4. 测试套件
python3 -m pytest tests/ -v
```

四条命令均应成功。若第 3 步报 `DataUnavailable`，说明 `tests/fixtures/bars_*.csv` 缺失。

## 常见问题

| 现象 | 处理 |
|---|---|
| `ModuleNotFoundError: panda_data` | 仅 `--panda` 通道需要；改装或改用 `--fixture` |
| `panda_data login failed: 用户未注册` | 账号或密码错误，检查 `PANDA_DATA_USERNAME` / `PANDA_DATA_PASSWORD` |
| `DataUnavailable: CSV missing columns` | CSV 表头须含 `date,open,high,low,close` |
| `BacktestError: published_at is required` | 观点缺发布时间；补 `published_at` 后再回测 |
| 抽取结果大量 `none` | 观点缺少标的或方向；属预期行为，见 `references/validation.md` |