# pkuquant：低位反弹因子实验

课程研究项目。已修正标签生成、信号交易时点、成本与样本划分纪律，保留旧版结果供追溯。**实验可以得出负结果；不将历史回测描述为可执行或盈利策略。**

## 当前结果

21 个候选（原 16 个公式族 + 5 个方向修正版本），只用 2019 开发验证段排序，冻结名单为 O03、O07、O10。2017–2020 已在旧实验中被查看，重新分段仍属于历史复核。

- [新版历史报告](runs/revised_v2/report.html)、[全部候选指标](runs/revised_v2/all_metrics.csv)、[选择过程](runs/revised_v2/development_selection.csv)。
- 三个候选的 2017–2020 多空净累计收益分别约为 −31.27%、−35.41%、−53.71%。按修正后的费用和时点，历史结果不支持“稳定盈利”的结论。
- [2021–2025 单次历史留出报告](runs/holdout_v2/report.html)：已评价，冻结候选多空净累计收益约 −57.14%、−61.17%、−57.42%，未重选。
- [真实冻结记录](config/freeze_manifest.json)：2026-10-09 21:32:59 北京时间，固定名单、方法、代码及数据哈希。
- [实验与验收说明](docs/research_notes.md)、[公式清单](docs/factors.md)、[源码 WIKI](wiki/overview.md)、[本地测试记录](docs/checks/local_checks.json)。

## 复现历史研究

本地已验证 Python 3.13.8；顶层依赖固定在 `requirements.txt`，运行清单保留实际版本。

```powershell
python -m pip install -r requirements.txt
python -B -m unittest discover -s tests -v
python -B scripts/run_checks.py
python -B scripts/run_oversold_rebound_backtest.py --output runs/my_reproduction
python -B scripts/build_final_report.py --run runs/my_reproduction
python -B scripts/research_control.py verify
```

输出目录必须不存在，避免覆盖既有实验。报告读取指定运行中的 `selected_factors.json`，不会从展示结果重新挑 Top 3。原脚本和原选择保存在 `legacy/`；旧报告 `runs/final/` 仅是历史基线，不能当作新版结果。相同输入、版本和参数才可比较复现。

## 留出集与未来样本

当前冻结在开发实验结束后进行。`download_holdout.py` 获取相同 50 只股票的 2020 暖机及 2021–2025 历史行情；`research_control.py holdout` 在读取并评价价格前写入只开启一次的访问记录，只报告冻结名单。失败也消耗访问权，不可以删除记录后反复调参。

```powershell
# 仅供新的、尚未开启留出集的实验版本使用
python -B scripts/download_holdout.py
python -B scripts/research_control.py holdout --input data/holdout_2021_2025.csv --output runs/holdout_v2
# 后续真实交易日收盘后，用含足够暖机历史的最新日线记录当日信号
python -B scripts/research_control.py forward --input data/latest_daily.csv --asof YYYY-MM-DD --output runs/forward_v2
```

`forward` 不下单，只固化当日信号与下一开盘目标；拒绝冻结之前、未来时刻或事后补填的日期。数据必须是当日收盘后取得、相同股票池，实际未来成交和收益仍需随后积累。[前向观察协议](docs/forward_protocol.md)明确何时能称为未来证据。历史留出收益不能替代冻结后的未来样本。

## 已知边界

股票池固定为 2020 年末沪深 300 中 50 只，未重建点时成分，存在生存偏差；完整日期表为输入日期并集。前复权版本、停牌/退市报价、涨跌停、整手、借券和开盘流动性均限制真实可执行性。理论多空与只多、等权基线分别报告，不能把理论空头当作可借券。详见[方法说明](docs/research_notes.md)。

本次未提交或上传 GitHub；已加入离线 CI 配置，但远端 CI 尚未运行。

首次整批取数超时后，已用 `fetch_holdout_cached.py` 的逐股票缓存与有限重试取得完整数据；请求参数和冻结数值方法不变。当前留出已消耗访问权，正常复核应读取已归档报告与原始指标，不重新执行留出评价。

## 本地交付与提交

[教师要求逐项对照](docs/acceptance.md) · [文件整理和自行提交步骤](docs/submission.md)。

## 2026-10-13–15 前向样本计划

已取得首份真实行情快照，日线截止 10 月 12 日；它只作观测和暖机，未补填旧信号。13、14、15 日每天 21:00 按[操作说明](docs/forward_operations.md)记录当天信号，15 日再整理阶段最终提交版本。[实时进度](docs/checks/forward_status.json)明确事前信号和成熟样本数量，尚未成熟的收益保留 pending。

2026-10-13 晚间更新：21:42 已登记[首日事前信号](runs/forward_v2/2026-10-13.json)，来源核验通过；三个冻结因子的目标已保存，收益仍待成熟。[当晚运行记录](docs/forward_operations.md)。

## [2026-10-14] ingest | 第二日前向信号

北京时间 2026-10-14 21:22:52–21:23:26 完成采集，21:23:25 登记当日事前信号。沿用冻结方法和 50 股票池，119 交易日矩阵共 5,950 行（5,712 行供应商报价、238 个退市无报价位置）。累计 13、14 日两个信号日期，成熟收益日期为 0；未运行收益评价、未下单。 [运行证据](docs/forward_operations.md)。本次由当前聊天启动，保留实际生成时间；15 日阶段最终整理仍待执行。

## 2026-10-15 阶段最终结果

10 月 13、14、15 日三个同日事前信号均已生成并保留实际登记时间。15 日采集于北京时间 21:19:42–21:20:22 完成，来源为 BaoStock；50 股票、119 日、5,950 行矩阵，其中 5,712 行真实供应商报价、238 个退市无报价位置。 目前只有 10 月 13 日信号具有一段完整的 14 日开盘至 15 日开盘收益代理；14、15 日信号仍未成熟。三天登记与一段收益用于验证前向流程，不能证明统计显著性、策略有效性或老师全部研究要求已通过。

[阶段报告](docs/forward_review_20261015.md) · [自行提交说明](docs/submission.md)。本轮采集结束，未执行 Git 提交或推送。
