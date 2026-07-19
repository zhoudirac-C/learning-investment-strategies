# Task 0 报告：环境与 vendor 准备

日期：2026-07-18 ｜ 状态：**DONE**

## 执行的步骤

1. **vendor chan.py**：经代理 `gh-proxy.com` 浅克隆 `https://github.com/Vespa314/chan.py`（github.com 直连不通，用 `git ls-remote` 验证代理与源站 HEAD 一致），原样拷贝（含 LICENSE、quick_guide.md、Script/ 等全部内容）到 `third_party/chanpy/`，删除 `.git`。未改动任何 chan.py 源码文件。
2. **安装依赖到 .venv**（Python 3.11.15）：`pip install "czsc==0.10.12" pyyaml baostock ipython`。装前 `--dry-run` 确认 czsc 不触碰 .venv 已有的 numpy 2.3.5 / pandas 3.0.3 / requests 2.34.2，实际安装亦未升降级这三个包；matplotlib 3.11.1 由 czsc 依赖链带入（满足 chan.py requirements）。版本附注已追加到 `third_party/chanpy/VENDORED.txt`。
3. **ADR 骨架**：`docs/design/chanlun-quant-adr.md`，预列 ADR-001..004（77 课"区间"口径 / 新笔旧笔 / 特征序列缺口细节 / 古怪线段），每条含备选解释 A/B、claims 原文依据（claim id）、暂定默认、状态=pending。
4. **导入验证通过**。

## chan.py vendor 信息

- commit sha：`429d6ed3043e27c93a003ba2b10e70a05575e1f5`
- `third_party/chanpy/VENDORED.txt`（source/commit/date + 依赖版本附注）
- `third_party/chanpy/PATCHES.md`（仅表头，M2 填）

## 安装的包及版本（.venv）

| 包 | 版本 | 备注 |
|---|---|---|
| czsc | 0.10.12 | 钉版本安装（调研时 PyPI 最新 stable） |
| pyyaml | 6.0.2 | 沿用 .venv 原有（PyYAML） |
| baostock | 0.9.3 | chan.py 依赖 |
| ipython | 9.15.0 | chan.py 依赖 |
| matplotlib | 3.11.1 | chan.py 依赖（czsc 依赖链带入） |
| numpy | 2.3.5 | 沿用 .venv 原有，未动 |
| pandas | 3.0.3 | 沿用 .venv 原有，未动 |
| requests | 2.34.2 | 沿用 .venv 原有，未动 |

czsc 附带主要依赖：rs_czsc 0.1.26.post260402、TA-Lib 0.7.1、scipy 1.17.1、scikit-learn 1.9.0、polars 1.42.1、streamlit 1.59.2、plotly 6.9.0 等（完整清单见 pip 安装日志）。

## chan.py 导入验证

- **结果：通过**
- 验证命令（仓库根目录）：
  `PYTHONPATH=src:third_party/chanpy .venv/bin/python -c "from Chan import CChan"`
  输出：`import OK: <class 'Chan.CChan'>`
- chan.py 使用包内绝对 import（`from ChanConfig import CChanConfig` 等），因此 vendored 目录本身（`third_party/chanpy`）必须在 PYTHONPATH 上；`Chan` 指目录下的 `Chan.py` 模块，不是包名。
- 依赖验证：`.venv/bin/python -c "import czsc, pandas, numpy, yaml, baostock, matplotlib, IPython"` 全部成功。

## 遇到的问题与阻塞项

- **github.com 直连不通**（curl 28 超时）：通过 `gh-proxy.com` 代理克隆解决，并用 `git ls-remote` 比对两个代理返回的 HEAD 一致，确认为源站真实 HEAD。**阻塞项：无。**
- 注意项：czsc 依赖链较重（streamlit/pywebview/kaleido 等），本次全量安装以满足 `import czsc` 可用；若后续 CI 需要精简环境可再评估。
- 注意项：numpy 2.3.5 / pandas 3.0.3 为新大版本，chan.py/czsc 在 M1 适配器开发时若暴露兼容性问题，届时记录并在 ADR/报告中处理（本任务范围内未改动）。

## 合规确认

- 无任何 git 提交类操作（克隆发生在 /tmp 临时目录，仓库内仅新增未跟踪文件）。
- chan.py 源码零改动（vendor 原样拷贝 + 仅新增 VENDORED.txt / PATCHES.md）。
- 未写任何引擎实现代码。
