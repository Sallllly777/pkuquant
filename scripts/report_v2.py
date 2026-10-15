"""Render the specified selection; never rerank or reselect using reported data."""
import argparse
from html import escape
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

def selected_names(path):
    selection=json.loads(Path(path).read_text(encoding='utf-8'))
    rows=selection.get('factors',selection.get('selection',[]))
    names=[r['factor'] if isinstance(r,dict) else r for r in rows]
    if not names or len(set(names))!=len(names): raise ValueError('Selection must contain unique factor IDs')
    return names

def render(run,selection,output):
    names=selected_names(selection)
    m=pd.read_csv(run/'all_metrics.csv')
    daily=pd.read_csv(run/'diagnostic_daily.csv.gz',parse_dates=['datetime'])
    manifest=json.loads((run/'run_manifest.json').read_text(encoding='utf-8'))
    quality=json.loads((run/'data_quality.json').read_text(encoding='utf-8'))
    available=set(m.factor)
    if not set(names)<=available: raise ValueError('Selection does not match experiment results')
    output.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':10})
    figures=[]
    for mode in ['long_short','long_only']:
        fig,ax=plt.subplots(figsize=(11,5))
        for name in names:
            d=daily[(daily.factor==name)&(daily['mode']==mode)&(daily.group==0)]
            ax.plot(d.datetime,d.nav,label=name)
        if mode=='long_only':
            d=daily[daily.factor=='baseline_equal_weight']
            ax.plot(d.datetime,d.nav,label='Equal-weight baseline',linestyle='--',color='black')
        ax.set(title=f'Frozen-list historical diagnostic: {mode}',ylabel='NAV (initial = 1)')
        ax.axhline(1,color='grey',lw=.7); ax.grid(alpha=.2); ax.legend(fontsize=8)
        fig.tight_layout(); filename=f'{mode}_equity.png'; fig.savefig(output/filename,dpi=150); plt.close(fig); figures.append(filename)
    fig,axes=plt.subplots(1,len(names),figsize=(5*len(names),4),squeeze=False)
    group_rows=[]
    for ax,name in zip(axes[0],names):
        values=[]
        for group in range(1,6):
            d=daily[(daily.factor==name)&(daily.group==group)]
            value=d.nav.iloc[-1]-1
            values.append(value); group_rows.append({'factor':name,'quintile':group,'net_total_return':value})
        ax.bar(range(1,6),values,color='#336699'); ax.axhline(0,color='grey'); ax.set(title=name.replace('_','\n'),xlabel='Quintile (1=low score)',ylabel='Net total return')
    fig.tight_layout(); fig.savefig(output/'quintile_returns.png',dpi=150); plt.close(fig); figures.append('quintile_returns.png')
    pd.DataFrame(group_rows).to_csv(output/'quintile_metrics.csv',index=False)
    selected=m[m.factor.isin(names)]
    fmt=lambda x:f'{x:.5f}'
    warning='2017–2020 已参与早期筛选。本页为修正方法后的历史复核；不能称作新样本外测试。未来前向样本尚未产生。'
    content=f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>超跌反弹研究 · v2 历史复核</title>
<style>body{{max-width:1200px;margin:40px auto;padding:0 24px;font:16px/1.65 system-ui,sans-serif;color:#17283a}}h1,h2{{line-height:1.3}}table{{border-collapse:collapse;font-size:12px;display:block;overflow:auto}}td,th{{padding:8px;border:1px solid #ddd;white-space:nowrap}}img{{max-width:100%}}.notice{{background:#fff4d6;padding:18px;border-left:4px solid #be8c21}}code{{word-break:break-all}}</style></head><body>
<h1>超跌反弹研究：方法修正与历史复核</h1><p class="notice">{warning}</p>
<p>报告严格读取 <code>{escape(str(selection.name))}</code> 中的名单，没有利用展示期指标重新排名或筛选。实验版本 {escape(manifest['config']['method_version'])}，候选 {manifest['candidate_count']} 个。</p>
<h2>样本与方法</h2><p>样本日期 {quality['start']} 至 {quality['end']}，{quality['symbols']} 只股票，输入 {quality['input_rows']} 行。缺少换手率的 {quality['missing_turn_source_rows']} 行保留价格记录；不再删除后跨行生成标签。</p>
<p>标签先在日期主表上生成 1/3/5 日收盘收益，IC 在每段尾部剔除跨段标签。信号 t 日收盘后形成，t+1 日开盘调仓，逐开盘净值计量；纳入初次建仓、价格漂移后的实际成交额、最终退出费用。3/5 日标签仅用于描述性 IC，不复利成年化组合收益，不将其视为独立显著性样本。</p>
<p>基础成本是假设的单边佣金 3 bps、滑点 2 bps、卖出额附加 10 bps；理论空头另假设年化借券费 200 bps。不是某券商实际费表。敏感性表的 0/5/10/20 bps 是对称全包场景，不能与分项基准混淆。</p>
<h2>明确限制</h2><p>{escape(manifest['config']['universe_note'])}</p><p>{escape(manifest['config']['execution_note'])}</p>
<p>股票池为事后冻结名单、行情为复权历史数据，未重建点时成分与公司行为版本。缺失持仓报价使用过去最近价格估值并阻止调仓，完整保留日期和告警；涨跌停、开盘成交能力、最小交易单位及真实借券数据不足，因此所有净值均为研究代理，不能据此认定实盘可执行或盈利。</p>
<h2>指定名单的分段结果</h2>{selected.to_html(index=False,float_format=fmt)}
<h2>净值与分组</h2>'''
    for name in figures: content+=f'<img src="{name}" alt="{escape(name)}">'
    for name,title in [('annual_metrics.csv','分年复核'),('cost_sensitivity.csv','预设成本压力情景'),('development_selection.csv','全部候选的开发段选择记录')]:
        content+=f'<h2>{title}</h2>'+pd.read_csv(run/name).to_html(index=False,float_format=fmt)
    content+='<h2>审计文件</h2><p>data_quality.json、run_manifest.json、events.jsonl、all_metrics.csv、all_daily_returns.csv.gz、all_ic.csv.gz、factor_coverage.csv 保存质量、版本、过程和明细。旧口径结果保留在 runs/final 与 runs/legacy_reproduced；新旧收益时点和费用不同，不应把差异解释为策略突然改进。</p></body></html>'
    (output/'report.html').write_text(content,encoding='utf-8')
    return names

def main():
    p=argparse.ArgumentParser(); p.add_argument('--run',type=Path,default=Path('runs/revised_v2')); p.add_argument('--selection',type=Path); p.add_argument('--output',type=Path)
    a=p.parse_args(); render(a.run,a.selection or a.run/'selected_factors.json',a.output or a.run)

if __name__=='__main__': main()
