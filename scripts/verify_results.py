"""Independently reconcile archived inputs/selection/daily NAV; no holdout reevaluation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from research_core import ROOT,file_hash
from research_control import verify_freeze
from report_v2 import selected_names

def reconcile(daily,metrics):
    checked=0
    keys=['factor','mode'] if 'mode' in metrics else ['factor']
    for _,metric in metrics.iterrows():
        d=daily.copy()
        for key in keys: d=d[d[key]==metric[key]]
        d=d.sort_values('datetime')
        if len(d)!=int(metric['observations']): raise ValueError('Observation count mismatch')
        if d.datetime.duplicated().any(): raise ValueError('Duplicate NAV date')
        np.testing.assert_allclose((1+d.net).cumprod(),d.nav,rtol=1e-10,atol=1e-11)
        np.testing.assert_allclose(d.net,d.gross-d.cost,rtol=1e-9,atol=1e-11)
        np.testing.assert_allclose(d.nav.iloc[-1]-1,metric.total_return,atol=1e-11)
        if int(d.held_count.iloc[-1])!=int(metric.terminal_held_count): raise ValueError('Terminal position metric mismatch')
        checked+=1
    return checked

def main():
    frozen=verify_freeze(ROOT/'config/freeze_manifest.json'); checks={}
    if selected_names(ROOT/'config/selected_factors.json')!=frozen['selection']: raise ValueError('Published list differs from frozen list')
    if file_hash(ROOT/frozen['config']['input'])!=frozen['history_input_sha256']: raise ValueError('History input changed')
    history=ROOT/frozen['development_run']
    m=pd.read_csv(history/'all_metrics.csv'); d=pd.read_csv(history/'all_daily_returns.csv.gz')
    checks['history_candidate_nav_series']=reconcile(d,m[m.phase=='history'])
    run=ROOT/'runs/holdout_v2'
    if run.exists():
        manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8'))
        ledger=json.loads((ROOT/'config/freeze_manifest.holdout_access.json').read_text(encoding='utf-8'))
        source=json.loads((ROOT/'data/holdout_2021_2025.manifest.json').read_text(encoding='utf-8'))
        actual=file_hash(ROOT/'data/holdout_2021_2025.csv')
        if not actual==source['input_sha256']==ledger['input_sha256']==manifest['input_sha256']: raise ValueError('Holdout input hash mismatch')
        freeze_hash=file_hash(ROOT/'config/freeze_manifest.json')
        if not freeze_hash==ledger['freeze_sha256']==manifest['freeze_sha256']==source['freeze_sha256']: raise ValueError('Holdout freeze mismatch')
        if manifest['selection']!=frozen['selection'] or manifest['reselected']: raise ValueError('Holdout selection changed')
        checks['holdout_nav_series']=reconcile(pd.read_csv(run/'daily.csv.gz'),pd.read_csv(run/'metrics.csv'))
    print(json.dumps({'passed':True,'checks':checks,'scope':'archived artifact consistency only; no rerun or reselection'},indent=2))

if __name__=='__main__': main()
