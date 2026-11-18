# 仿真大赛核验：把回放的执行口径拿到真实盘口下对账

## 为什么需要这一页

任务原文要求「交易执行部分用期货模拟赛核验；品种或接口不支持时事先明确等价回放范围」。
0.7.x 做的是后半句（`scope.py` 在开跑前冻结范围）。这页处理前半句里**能被观测的那部分**：
回测用的是「次日开盘成交 + 单边 3bp 手续费 + 2bp 滑点」，这三个数是谁也没量过的常数。

`scripts/contest_verify.py` 不重跑回测，它只把那几个常数拿到仿真大赛的实时规格下逐个对账，
并对量不出的部分明确写 `unavailable` / `unverified` / `not_verified`。

## 怎么复现

```bash
# 1) 由 agent 调宿主交易通道取回并落盘（文件名见 tests/fixtures/contest/raw/README.md）
#    需要：resolve / quote / contract-spec（RB、I），account（只留资金字段）
# 2) 只读核验：
python3 scripts/contest_verify.py                       # 人读
python3 scripts/contest_verify.py --json                # 机读，stdout 一个 JSON
python3 scripts/contest_verify.py --out baselines/contest_verify_<date>.json
```

退出码：`0` 规格与成本都可下结论；`1` 成本口径偏离或部分品种量不出；`2` 缺载荷/参数。

## 2026-11-19 实测结果

规格（`rb2701` / `i2701`，行情时间 2026-11-18 23:00，`ready=true`）：

| 项 | RB（螺纹钢） | I（铁矿石） |
|---|---|---|
| 交易所 / 启用 | SHF / 是 | DCE / 是 |
| 合约乘数 | 10 | 100 |
| 多空保证金率 | 7% / 7% | 8% / 8% |
| 每手保证金 | 2,089.50 元 | 5,184.00 元 |
| 最后交易日 | 20270115 | 20270115 |
| 交割日 | **暂无数据**（不用最后交易日顶替） | **暂无数据** |
| 距最后交易日 | 57 个日历日（下限口径，非精确交易日推算） | 57 个日历日 |

执行成本对账（本文件的重点）：

| 项 | RB | I |
|---|---|---|
| 买一 / 卖一 | 2983 / 2985 | 647.5 / 648 |
| 报价全价差 | 6.70 bp | 7.72 bp |
| **单边跨价成本（半价差）** | **3.35 bp** | **3.86 bp** |
| 回测单边滑点假设 | 2.0 bp | 2.0 bp |
| 倍率 | **1.68x** | **1.93x** |
| verdict | `cost_model_below_market` | `cost_model_below_market` |
| 手续费 3bp/边 | `unverified`：没有成交回执；`settlements.commission=0` 只说明还没成交，不等于免费 | 同左 |

## 这条偏离会不会改变结论：不会，但它改变可实现的读数

**配对 edge 对成本假设不敏感，这是设计使然**：基线是同一规则窗口上的配对持有，
两条腿扣的是同一笔成本，所以在 edge 上正好抵消。实测各档成本下 edge 一动不动：

```
python3 scripts/evaluate.py --fixture                          # 3+2
python3 scripts/evaluate.py --fixture --slippage-bps 3.3512    # 实测 RB
python3 scripts/evaluate.py --fixture --slippage-bps 3.8595    # 实测 I
python3 scripts/evaluate.py --fixture --slippage-bps 5.0       # 加倍
```

四种口径下都是 `edge −0.018527  CI [−0.028301, −0.00856]  n=10  verdict INCONCLUSIVE`。

传导到的那一侧是**绝对净收益**（只有两臂成本口径不同才会进 edge）：按 I 的实测单边成本，
`mean net 0.0195 → 0.019128`、`Sharpe 5.411 → 5.307`、`maxDD −0.01378 → −0.014152`。

所以正确的读法是：

- 结论方向与显著性**不因滑点被低估而翻**（两个 verdict 依旧 `inconclusive`，卡点是 n=10 < 12）；
- 但**别把 `mean net` 当成可实现的资金曲线**：真实跨价至少还要多吃 1.4–1.9 bp/边，
  拿它做仓位或 sizing 之前要先按实测口径扣一遍。

## 这一页不算什么

1. **不算撮合核验**。`execution` 一栏在没有成交回执时永远是 `not_verified`；
   规格全绿不等于执行被验证过。
2. **不算手续费核验**。费率必须来自成交/结算回执，`observed: null` 就写 null。
3. 品种覆盖只有 RB 与 I 被真测到；`scope.SUPPORTED_PRODUCTS` 里其余品种标 `not_checked`，
   不猜它们的可交易性。
4. 行情是 23:00 收盘那一刻的快照，跨价成本随时段变；换时点取数就要重新落盘重跑。
5. 载荷与报告都不含账号、手机号、用户名：`contest_verify.py` 输出的每一层都先过一遍
   身份字段剥离，随包的只有 `baselines/contest_verify_*.json`。
