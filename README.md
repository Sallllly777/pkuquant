# pkuquant

北京大学量化交易课程作业：基于 BaoStock 日线数据研究低位反弹信号。

## 研究问题

当股票连续数日收盘价接近日内低点时，是否代表短期恐慌情绪达到极端，并对下一交易日的反弹收益具有预测能力？本项目以三日低位收盘公式为原型，扩展出 16 个候选因子，按预测能力、换手率和多空净 Sharpe 筛选出最终 3 个因子。

## 最终因子

- `O03_low_location_5d`：5 日收盘价在日内区间中的平均位置取负。
- `O13_low_close_high_vol`：低位收盘强度与相对波动率结合。
- `O02_low_location_3d`：3 日低位收盘，直接对应核心假设。

最终指标见 [`runs/final/report.html`](runs/final/report.html) 和 [`config/selected_factors.json`](config/selected_factors.json)。

## 目录

- `data/`：BaoStock 前复权日线数据及数据说明。
- `scripts/`：因子计算、横截面评估和报告生成脚本。
- `config/`：最终因子、样本和成本配置。
- `runs/final/`：最终 HTML 报告、指标、收益明细和净值图。
- `docs/`：研究方法、实验边界和复现说明。

## 复现

```powershell
pip install -r requirements.txt
python scripts/run_oversold_rebound_backtest.py `
  --input data/baostock_hs300_daily.csv `
  --output runs/experiment
```

脚本默认使用 2017–2020 日线、5 bps 成本和多空各 20% 分组。数据样本使用 2020-12-31 冻结的 50 只 HS300 成分股，存在生存偏差；结果用于课程研究，不代表实盘收益。

## 安全说明

仓库不包含 GitHub 密码、Tushare token 或其他凭据。
