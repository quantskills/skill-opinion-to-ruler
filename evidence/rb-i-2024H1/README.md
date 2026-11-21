# RB / I 2024H1 复跑证据

本目录是原 12 例真实行情试验的**只读证据入口**，随包发布。它让干净克隆不必重新调用数据接口，也能重跑 `baselines/rb-i-2024H1-real.json`。

## 什么是真实的，什么是合成的

- **行情是真实的**：2024-01-02 至 2024-06-28 的 RB、I 具体合约日线与逐日主力映射来自 PandaData MCP 的真实返回，经 `scripts/mcp_landing.py --build` 确定性派生。
- **观点文本是合成的**：12 个案例来自 `tests/fixtures/opinions.json`；该文件明确自述为 hand-written synthetic fixture，不是历史作者的原话。`cases_rules_labels.json` 中保留了对应 `id`、`published_at` 与原文。
- 因真实锚点与合成行情锚点使用同一观点夹具、标注集和抽取配置，两者的 `extraction` 对象相同。这里不把它包装成真实作者样本。
- 12 笔交易的有效性结论只依赖抽取规则、真实行情以及冻结的基线/成本/门槛，不依赖观点是否由真实作者发表。本次复跑保留 `inconclusive`，它检验的是规则化与评价流程，不是某位作者的历史预测能力。

## 权限边界

原始 MCP 响应仍**不随包发布**，继续留在被忽略的 `tests/fixtures/raw/`。随包入库的是派生后的公开市场日线 OHLCV 与主力映射 CSV：只有日期、开高低收量、合约代码等字段，不含专有响应字段、凭证、账号信息或账户衍生数据。`provenance.json` 只记录来源文件名、窗口、行数、完整性与换月信息，不记录 request id 或机器绝对路径。

## 文件清单

| 文件 | 内容 |
|---|---|
| `bars_I2405.DCE.csv` | 56 行，`date,open,high,low,close,volume` |
| `bars_I2409.DCE.csv` | 61 行，同上 |
| `bars_RB2405.SHF.csv` | 86 行，同上 |
| `bars_RB2410.SHF.csv` | 117 行，同上 |
| `dominant_I.csv` | 117 行，`date,contract` |
| `dominant_RB.csv` | 117 行，同上 |
| `provenance.json` | 派生产物的来源文件名、窗口与完整性记录 |
| `cases_rules_labels.json` | 12 个成交案例的 `case` / `rule` / `label` / `trade` |

六份 CSV 的原始文件行数分别为 56、61、86、117、117、117；其中四份合约日线共 320 行，包含非主力日。真实锚点只使用主力映射覆盖的 **234 行**合约日线（`bars_used` = 56+61+58+59），主力映射合计 **234 行**（117+117）。这两个口径不能混写。`cases_rules_labels.json` 的 12 条由真实锚点 `backtest.trades[].rule_id` 选出；完整规则由 `build.run(..., apply_defaults=True)` 对同一观点夹具确定性重建，配置哈希与真实锚点一致。真实锚点的 `extraction` 段本身只存汇总、准确率与配置哈希，不存完整规则对象。

## 独立复跑（不需要原始载荷）

直接把本目录七份行情/溯源文件复制到名为 `real_landed` 的工作目录。目录名是既有便携溯源契约的一部分，报告只记录 basename；改名会使 `data.landed_dir` 与锚点不同。

```bash
work="$(mktemp -d)"
mkdir "$work/real_landed"
cp evidence/rb-i-2024H1/bars_*.csv "$work/real_landed/"
cp evidence/rb-i-2024H1/dominant_*.csv "$work/real_landed/"
cp evidence/rb-i-2024H1/provenance.json "$work/real_landed/"

python3 scripts/evaluate.py \
  --landed-dir "$work/real_landed" --start 20240102 --end 20240628 \
  --baseline-output "$work/report.json" --scope-output "$work/scope.json"
python3 scripts/compare_baseline.py \
  --report "$work/report.json" --frozen baselines/rb-i-2024H1-real.json \
  --scope "$work/scope.json"
```

预期：报告与真实锚点 1448 个字段零差异，连同范围声明的守卫共比较 1526 个字段；`verdict: CONSISTENT`，交易结论仍为 `inconclusive`。也可以直接跑无条件执行的机器守卫：

```bash
python3.11 -m pytest tests/test_baseline_guard.py -k shipped_evidence -q
```

## 可选：从原始载荷复核派生关系

数据持有者可用下列四份原始响应复核 `raw -> landed` 派生关系；缺文件时原 raw 守卫会跳过，但上面的 evidence 守卫始终执行：

```text
get_future_daily__I2405_20240102_20240327.json
get_future_daily__I2409_20240328_20240628.json
get_future_daily__RB_20240102_20240628.json
get_future_dominant__I_RB_20240102_20240628.json
```

```bash
python3 scripts/mcp_landing.py --build \
  --raw-dir tests/fixtures/raw --out-dir "$work/real_landed" \
  --start 20240102 --end 20240628
python3.11 -m pytest tests/test_baseline_guard.py -k raw_payloads -q
```

raw 守卫还会逐字节核对新建产物与本目录七份派生产物，因此证据目录不能脱离原载荷单独漂移。

## 无原始载荷时的第三方验证：sha256 复取口径

没有 raw 载荷的审核方也能自证「包内 CSV == 网关数据」：`checksums.json` 给出七份派生文件的
SHA-256 与**精确到参数的复取配方**（4 次 `mcp__pandadata__call_pandadata` 调用，含 symbol /
窗口 / fields）。流程：

1. 在 QuantStudio 宿主按 `checksums.json.refetch_params` 逐条调用 MCP，把返回载荷**原样**写入
   `tests/fixtures/raw/<lands_as>`；
2. 跑 `checksums.json.rebuild_command` 重建派生产物；
3. 对重建出的七份文件算 `shasum -a 256`，与 `checksums.json.files` 比对。

一致 → 随包 CSV 与网关当前返回逐字节相同，派生链闭环。
不一致 → 说明网关数据在 2026-11-21（取数日）之后被修订过；此时应报告差异而不是默采任何一侧，
随包锚点仍然锚定 2026-11-21 取到的那一份数据。

机器守卫：`tests/test_baseline_guard.py::test_checksums_match_the_shipped_evidence`
（无条件执行）核对 `checksums.json` 与目录内实物一致，防止清单与文件漂移。
