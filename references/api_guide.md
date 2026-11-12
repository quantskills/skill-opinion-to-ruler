# 数据接口（api_guide）

本 skill 有两条行情通道，产出结构完全相同，调用方通过参数选择，绝不静默切换。

## 1. panda_data（生产通道）

| 项 | 值 |
|---|---|
| 包名 | `panda-data==1.0.6` |
| Python | 实测 3.10+（SDK 自身声明） |
| 入口 | `scripts/data_loader.py::load_panda` |
| 认证 | `panda_data.init_token(username=..., password=..., base_url=..., country="CN")` |
| 默认服务地址 | `https://pandadata.pandaaiquant.com` |

### 凭证

解析顺序（优先级从高到低，任一层命中即用，绝不写入仓库）：

| 顺序 | 变量 | 说明 |
|---|---|---|
| 1 | `PANDA_DATA_USERNAME` / `PANDA_DATA_PASSWORD` / `PANDA_DATA_BASE_URL` | 项目推荐命名 |
| 2 | `DEFAULT_USERNAME` / `DEFAULT_PASSWORD` / `JAVA_SERVICE_BASE_URL` | 上游 SDK 历史命名 |
| 3 | `~/.pandadata/pandadata.env` | `KEY=VALUE` 每行一条，允许 `export` 前缀 |

三个字段（username / zinfoid / base_url）**都必需**。缺任一项时 `load_panda` 抛 `DataUnavailable` 并列出缺的是哪个，不做任何降级。`credentials_source()` 返回实际生效的层（`env` / `legacy_env` / `env_file` / `missing:*`），便于在报告里溯源。

### 使用的接口

| 接口 | 用途 | 关键参数 |
|---|---|---|
| `get_future_dominant` | 查每个交易日的主力合约代码 | `underlying_symbol`, `start_date`, `end_date` |
| `get_future_daily` | 取具体合约日线，也是唯一的价格来源 | `symbol`（list）, `start_date`, `end_date` |

主力连续序列的构造方式：先用 `get_future_dominant` 拿到逐日主力合约映射，再把各合约自己的 `get_future_daily` 行情按日期拼起来。

**为什么不直接用 `get_future_daily_post`**：它的复权序列会整体平移历史价格。实测 RB 在 2024-01-10 的合约收盘是 3887，而复权序列给的是 4776。观点里的价位是作者当时看到的实价，用复权价去比较会让 `close > 3850` 这类条件在错误的位置触发。因此本 skill 只用未复权的合约行情。

代价是换月处不连续：主力换月当天，价差会原样保留。这一点写进报告的 `applicability`，不做隐藏。若要做严格的连续合约回测，需要另接复权序列，并同步调整规则里的价位口径。

### 字段映射

| panda_data 列 | 内部字段 |
|---|---|
| `trade_date` / `date` | `date`（`YYYYMMDD`） |
| `open/high/low/close` | 同名 |
| `volume` | `volume`（缺失记 0） |

### 调用示例

```python
from data_loader import load_bars

loaded = load_bars("RB", "20240101", "20241231")
print(loaded["source"])   # "panda"
print(loaded["bars"][0])
```

## 2. CSV fallback（离线通道）

用于无凭证、无网络或 CI 环境。

文件要求：表头为 `date,open,high,low,close[,volume]`，`date` 为 `YYYYMMDD` 或 `YYYY-MM-DD`。

```python
loaded = load_bars("RB", "20240101", "20241231", csv_path="tests/fixtures/bars_RB.csv")
print(loaded["source"])   # "csv"
```

`load_csv` 会校验列缺失、数值可解析、非空行；任何一条不满足都抛 `DataUnavailable` 并指出具体原因。

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

期货模拟赛核验时，若某品种或接口不可用，应在报告 `applicability.out_of_scope` 中明确写出等价回放范围，而不是替换成别的品种继续跑。