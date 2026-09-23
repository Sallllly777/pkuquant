import argparse
from pathlib import Path
import json
import pandas as pd
import matplotlib.pyplot as plt

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--metrics',default='runs/experiment/oversold_factor_metrics.csv'); ap.add_argument('--daily',default='runs/experiment/oversold_daily_returns.csv'); ap.add_argument('--output',default='runs/final'); a=ap.parse_args()
    out=Path(a.output); out.mkdir(parents=True,exist_ok=True)
    metrics=pd.read_csv(a.metrics).sort_values('selection_score',ascending=False).head(3); names=metrics.factor.tolist(); daily=pd.read_csv(a.daily); daily=daily[daily.factor.isin(names)]
    metrics.to_csv(out/'selected_top3_metrics.csv',index=False); daily.to_csv(out/'selected_top3_daily_returns.csv',index=False)
    fig,ax=plt.subplots(figsize=(12,7))
    for n in names:
        d=daily[daily.factor==n].sort_values('datetime'); ax.plot(d.datetime,(1+d.net).cumprod(),label=n)
    ax.grid(alpha=.3); ax.legend(); fig.tight_layout(); fig.savefig(out/'selected_top3_equity.png',dpi=160); plt.close(fig)
    (out/'report.html').write_text('<html><meta charset="utf-8"><title>Final oversold rebound report</title><h1>Final oversold rebound factors</h1>'+metrics.to_html(index=False,float_format=lambda x:f"{x:.4f}")+'</html>',encoding='utf-8')
if __name__=='__main__': main()
