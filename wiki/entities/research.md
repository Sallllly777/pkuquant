---
title: 因子研究源码导航
type: architecture
status: reviewed
updated: 2026-10-09
sources:
  - "[[本地研究版本与实验记录]]"
tags: [quant, reproducibility]
---

# 因子研究源码导航

| 入口 / 函数 | 源码 | 职责 |
| --- | --- | --- |
| run / main | [research_pipeline.py](../../scripts/research_pipeline.py) | 读取配置，全部候选分段，开发段选取，生成审计明细与清单 |
| load_panel | [research_core.py](../../scripts/research_core.py) | 校验重复/异常数据，构造完整日期×股票表 |
| build_features / factor_values | 同上；[factor_definitions.py](../../scripts/factor_definitions.py) | 先建固定日期标签，再算原 16 及 5 个新版本 |
| rank_ic | research_core | 横截面平均秩、边界标签剔除、最低样本数 |
| weights / fees / simulate | research_core | 确定性分组、真实成交绝对额费用、自融资逐开盘净值 |
| nav_metrics / select_candidates | research_core | 含初始净值的回撤，固定开发段选择规则 |
| selected_names / render | [report_v2.py](../../scripts/report_v2.py) | 按指定名单绘图，不依据展示期指标重选 |
| freeze / verify_freeze / holdout / forward | [research_control.py](../../scripts/research_control.py) | 哈希冻结、单次留出访问、当天前向记录 |
| recorded_features | [evaluate_forward.py](../../scripts/evaluate_forward.py) | 只使用事前登记的信号与后续价格，不补算缺失信号 |

调用链：CSV → load_panel → build_features → simulate 与 rank_ic → 开发段固定排名 → 清单/报告 → freeze → 单次历史留出与真实前向。下载器只获取数据，不选择因子。

关联：[DEMO](../code/research-v2.md)、[原则](../concepts/experiment.md)、[来源](../sources/local-records.md)。测试使用手算边界/扰动未来数据等方式校验行为，避免只重复实现。
