"""Render existing single-use holdout outputs; never reevaluate or select candidates."""
import argparse
import json
from pathlib import Path
from html import escape
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def main():
    p=argparse.ArgumentParser(); p.add_argument('--run',type=Path,default=Path('runs/holdout_v2')); a=p.parse_args()
    manifest=json.loads((a.run/'manifest.json').read_text(encoding='utf-8'))
    metrics=pd.read_csv(a.run/'metrics.csv'); daily=pd.read_csv(a.run/'daily.csv.gz',parse_dates=['datetime'])
    selected=manifest['selection']
    figures=[]
    for mode in ('long_short','long_only'):
        fig,ax=plt.subplots(figsize=(11,5))
        for factor in selected:
            d=daily[(daily.factor==factor)&(daily['mode']==mode)]
            ax.plot(d.datetime,d.nav,label=factor)
        if mode=='long_only':
            d=daily[daily.factor=='baseline_equal_weight']; ax.plot(d.datetime,d.nav,label='Equal-weight baseline',color='black',linestyle='--')
        ax.axhline(1,color='grey',lw=.7); ax.grid(alpha=.25); ax.legend(fontsize=8)
        ax.set(title='2021-2025 single-use historical holdout: '+mode,ylabel='NAV (initial = 1)')
        fig.tight_layout(); name=mode+'.png'; fig.savefig(a.run/name,dpi=140); plt.close(fig); figures.append(name)
    text='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>冻结名单：2021–2025 历史留出</title>
<style>body{max-width:1150px;margin:40px auto;padding:0 24px;font:16px/1.7 system-ui;color:#17283a}table{display:block;overflow:auto;border-collapse:collapse;font-size:12px}td,th{padding:8px;border:1px solid #ddd;white-space:nowrap}img{max-width:100%}.note{padding:18px;background:#fff4d6;border-left:4px solid #be8c21}</style>
<h1>2021–2025：冻结名单的单次历史留出</h1>
<p class="note">本报告只展示已完成的单次评价，未再次筛选或修改冻结方法。这些行情发生在冻结之前，不能称作真正冻结后的未来样本。理论多空和只多结果均为研究价格代理，存在股票池、复权、借券和执行约束。</p>
<p>2026-10-09 21:32:59 北京时间冻结；2026-10-10 22:11:51 首次开启留出，访问账本保留。2020-08 起数据仅作暖机，评价区间为 2021–2025，共 1212 个观测日期。名单为 O03、O07、O10。</p>
<p>固定名单的多空净累计收益约 −57.14%、−61.17%、−57.42%；只多也为负，同口径等权基线约 +34.31%。1 日 IC 均值为正不代表扣除费用后的组合有正收益；本实验没有支持稳定净盈利。不能根据这张表重新选择因子。</p>
<p>基准成本为单边佣金 3 bps + 滑点 2 bps，卖出额附加 10 bps，理论空头年化借券费 200 bps。与历史复核使用相同冻结口径，属于假设而非真实费表。完整指标含阻止调仓天数和最终持仓数，本次均为 0；这不能证明涨跌停或开盘流动性已建模。</p>'''
    text+=metrics.to_html(index=False,float_format=lambda x:f'{x:.5f}')
    for name in figures: text+=f'<img src="{name}" alt="{escape(name)}">'
    text+='<h2>原始记录</h2><p><a href="manifest.json">结果清单</a> · <a href="metrics.csv">指标</a> · <a href="daily.csv.gz">每日净值与成本</a> · <a href="ic.csv.gz">逐日 IC</a> · <a href="data_quality.json">数据质量</a> · <a href="../../config/freeze_manifest.holdout_access.json">访问账本</a></p><p>'+escape(manifest['limitations'])+'</p></html>'
    (a.run/'report.html').write_text(text,encoding='utf-8'); print(a.run/'report.html')

if __name__=='__main__': main()
