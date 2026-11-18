# tests/fixtures/contest/raw/ — 仿真大赛载荷落盘位（不入库）

这里放**由阅读本 skill 的 agent** 调用宿主交易通道取回的原始 JSON。脚本只读这里，
永远不会自己去取数：本包内没有交易客户端、没有网络出口、没有凭证。

## 该放哪些文件（文件名是硬约定）

| 文件 | 来源（由 agent 执行的宿主交易通道查询） | 用于 |
|---|---|---|
| `resolve__RB.json` / `resolve__I.json` | 品种解析（螺纹钢 / 铁矿石） | 该品种在撮合系统里是否启用、归属哪个交易所 |
| `quote__RB.json` / `quote__I.json` | 单品种最新行情快照 | 最新价、买一卖一（算跨价成本）、`ready`、`tradeDate` |
| `contract_spec__RB.json` / `contract_spec__I.json` | 合约规格 | 合约乘数、四项保证金、最后交易日、交割日 |
| `account.json` | 账户资金（**只保留资金字段**） | 判断 1 手是否负担得起 |
| `orders__<yyyymmdd>.json` / `trades__<yyyymmdd>.json` | 当日委托 / 成交 | 执行核验：只有这里有料，`execution` 才允许下结论 |

只保存响应里的 `data` 段（外层 `{"ok": true, "data": {...}}` 取 `{...}`），
与 `tests/fixtures/raw/` 的口径一致。

## 落盘前必须脱敏

账户与身份类响应含账号 ID、手机号、用户名、头像等字段。**不要**把这些写进来。
`scripts/contest_verify.py` 会对输出的每一层再剥一次身份键（`accountId`、`contestId`、
`username`、`phone`、`name`、`intro`、`image`），但那是最后一道防线，不是把原始响应
直接扔进目录的理由。随包发布的只有 `baselines/contest_verify_*.json`（已脱敏）。

## 为什么这里通常没有真实成交

撮合核验要真的下单。下单前必须由用户**逐笔明确确认**；没有确认、没有成交回执时，
`execution` 只能是 `not_verified`，手续费一栏只能是 `unverified`。
规格与成本对账**不等于**执行核验，这条不许含糊。

## 复现步骤

```bash
# 1) 由 agent 取回并落盘上述文件
# 2) 只读核验
python3 scripts/contest_verify.py --raw tests/fixtures/contest/raw --json
python3 scripts/contest_verify.py --out baselines/contest_verify_<yyyymmdd>.json
```
