# 构建产物（本技能自有格式）

`scripts/mcp_landing.py --build` 的输出目录：**由上一层 `raw/` 里的 MCP 载荷构建**，
可复现，因此不入库（见 `.gitignore`）。

| 文件 | 列 | 来自 |
|---|---|---|
| `bars_<SYMBOL>.csv` | `date,open,high,low,close,volume` | `get_future_daily` 载荷，按行内 `symbol` 归组 |
| `dominant_<PRODUCT>.csv` | `date,contract` | `get_future_dominant` 载荷，按 `underlying_symbol` 归组 |
| `provenance.json` | — | 每个文件来自哪些载荷、请求区间、是否 partial |

列结构与本技能顶层 `tests/fixtures/bars_RB.csv` 完全一致，所以同一套
`load_csv` / `--fixture` / 回测代码不用改就能读真实数据。真实数据写在这个子目录里，
是为了**不覆盖**顶层那份合成样例——两条路必须能分辨。

## 用法

```bash
python3 scripts/mcp_landing.py --build \
    --raw-dir tests/fixtures/raw --out-dir tests/fixtures/landed \
    [--start 20240101 --end 20240331] [--symbol RB2405] [--allow-partial]

python3 scripts/mcp_landing.py --verify      # 只读诊断：载荷齐不齐、有没有被截断
python3 scripts/evaluate.py --landed-dir tests/fixtures/landed --start ... --end ...
```

## 语义要点

- **日期归属由主力映射决定**：某个交易日的 bar 只取"那天真正主力"的合约，不按合约
  的 `min..max` 窗口去重（那会在同一合约分两段主力时错误归属）。
- **换月是近似的**：拼接用未复权价，跨换月的价格连续性不做保证，`roll_count` 会记在
  provenance 与报告里。
- **partial 会一路传下去**：`--allow-partial` 构建出来的文件，`provenance.json` 里
  `partial: true`，评测报告里进 `data.partial_symbols` 并触发 `data_quality_warning`。
- **校验先于写文件**：任何载荷不合格都不会留下半套目录；重跑 `--build` 是幂等的
  （产物不含时间戳）。
- 手工放进来的 `bars_*.csv`（没有 `provenance.json`）也能读，但来源不可核验，报告里
  会带 `provenance_missing: true`。
