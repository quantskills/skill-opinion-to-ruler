# `raw/` — MCP 落盘载荷（**故意不随包发布**）

本目录存放 agent 通过 `mcp__pandadata__call_pandadata` 取回并**原样**写入的响应载荷，
命名规则 `<method>__<label>.json`（见 `references/mcp-data.md`）。

这些是**付费授权数据**，所以 `.gitignore` 里 `tests/fixtures/raw/*` 把它们全部排除，
只用 `!README.md` 留本说明。导出的包、以及从 git 安装的副本，这里都应该是空的。

## 空目录不是错误

`tests/test_baseline_guard.py::test_real_anchor_reproduces_from_the_raw_payloads`
在没有载荷时**跳过（skip）而不是失败**，也**不会假装通过**：跳过原因里会提示可以用
环境变量指向载荷目录。因此新装副本少一条用例属于正常状态，不代表验收降级。

## 复现随包的真实行情锚点

产出 `baselines/rb-i-2024H1-real.json` 需要这 5 份载荷（RB、I，2024-01-02..2024-06-28；
文件名里的 label 只是标识，保留 `<method>__` 前缀即可）：

```
get_future_dominant__I_RB_20240102_20240628.json
get_future_daily__I2405_20240102_20240327.json
get_future_daily__I2409_20240328_20240628.json
get_future_daily__RB_20240102_20240628.json
get_future_daily__RB_DOMINANT.SHF_20240101_20250103.json
```

取数与写入由 **agent** 完成（脚本不联网、不调 MCP），然后：

```bash
python3 scripts/mcp_landing.py --build --raw-dir tests/fixtures/raw --out-dir <可写目录>/real_landed
OPINION_TO_RULER_RAW_DIR=tests/fixtures/raw python3.11 -m pytest tests/ -k reproduces
```

落点目录名必须就叫 `real_landed`：报告与锚点里记录的是**文件名而非绝对路径**，
名字对不上就比不上。窗口也要与锚点一致（20240102–20240628）——换窗口是另一次测量，
不能拿来对这张表。
