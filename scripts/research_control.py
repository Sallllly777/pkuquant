"""Local experiment freeze, single-use historical holdout and forward signal ledger.

This is an auditable local workflow, not a tamper-proof external timestamp service.
Never relabel previously inspected history as genuinely future data.
"""
import argparse
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import pandas as pd
from research_core import ROOT, file_hash, load_panel, build_features, simulate, rank_ic, nav_metrics, ic_metrics, weights
from research_pipeline import json_write
from report_v2 import selected_names

NUMERIC_SOURCES = ['scripts/research_core.py','scripts/factor_definitions.py','scripts/research_pipeline.py']
CONTROL_SOURCES = ['scripts/research_control.py','scripts/download_holdout.py']

def utc_now(): return datetime.now(timezone.utc)

def freeze(run, target, root=ROOT):
    if target.exists(): raise ValueError('Freeze already exists; preserve it and create a new experiment version')
    manifest=json.loads((run/'run_manifest.json').read_text(encoding='utf-8'))
    if manifest['status']!='complete': raise ValueError('Cannot freeze incomplete run')
    config=root/'config/research_v2.json'
    if file_hash(config)!=manifest['config_sha256']: raise ValueError('Configuration changed after run')
    for relative in NUMERIC_SOURCES:
        if file_hash(root/relative)!=manifest['source_sha256'][relative]: raise ValueError('Numeric source changed after run: '+relative)
    names=selected_names(run/'selected_factors.json')
    if names!=manifest['selection']: raise ValueError('Selection does not match completed run')
    source_hash={p:file_hash(root/p) for p in NUMERIC_SOURCES+CONTROL_SOURCES}
    value={'schema':1,'frozen_at_utc':utc_now().isoformat(),'method_version':manifest['config']['method_version'],
           'selection':names,'source_sha256':source_hash,'config':manifest['config'],'config_sha256':file_hash(config),
           'history_input_sha256':manifest['input_sha256'],'development_run':str(run.resolve().relative_to(root.resolve())).replace('\\','/'),
           'development_manifest_sha256':file_hash(run/'run_manifest.json'),
           'development_selection_sha256':file_hash(run/'selected_factors.json'),
           'git_base_commit':manifest['git_base_commit'],'worktree_dirty_at_run':manifest['git_worktree_dirty'],
           'disclosure':'2017-2020 already inspected; later historical holdout is not post-freeze future data. Local timestamp is not independently notarized.',
           'forward_status':'awaiting_actual_post_freeze_signals_and_outcomes'}
    target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('x',encoding='utf-8') as f: json.dump(value,f,ensure_ascii=False,indent=2)
    return value

def verify_freeze(path,root=ROOT):
    f=json.loads(path.read_text(encoding='utf-8'))
    for relative,expected in f['source_sha256'].items():
        if file_hash(root/relative)!=expected: raise ValueError('Frozen source changed: '+relative)
    if file_hash(root/'config/research_v2.json')!=f['config_sha256']: raise ValueError('Frozen configuration changed')
    run=root/f['development_run']
    if file_hash(run/'run_manifest.json')!=f['development_manifest_sha256']: raise ValueError('Development manifest changed')
    if file_hash(run/'selected_factors.json')!=f['development_selection_sha256']: raise ValueError('Selection changed')
    if utc_now()<datetime.fromisoformat(f['frozen_at_utc']): raise ValueError('Freeze timestamp is in the future')
    return f

def claim_holdout(ledger,freeze_hash,input_hash):
    # O_EXCL via mode x makes simultaneous or repeated unlocks fail before reading prices.
    ledger.parent.mkdir(parents=True,exist_ok=True)
    with ledger.open('x',encoding='utf-8') as out:
        json.dump({'opened_at_utc':utc_now().isoformat(),'freeze_sha256':freeze_hash,'input_sha256':input_hash,
                   'status':'access_consumed','rule':'Even failed evaluation consumes access; no repeated tuning on this period.'},out,indent=2)

def holdout(freeze_path,input_path,output,root=ROOT):
    frozen=verify_freeze(freeze_path,root)
    ledger=freeze_path.with_name(freeze_path.stem+'.holdout_access.json')
    if output.exists(): raise ValueError('Output already exists')
    claim_holdout(ledger,file_hash(freeze_path),file_hash(input_path))
    output.mkdir(parents=True,exist_ok=False)
    try:
        panel,quality=load_panel(input_path)
        cfg=frozen['config']; bounds=cfg['historical_holdout']
        source_symbols=set(pd.read_csv(root/cfg['input'],usecols=['symbol']).symbol.unique())
        if set(panel.index.get_level_values('symbol'))!=source_symbols: raise ValueError('Frozen universe must be unchanged')
        actual=panel.loc[bounds['start']:bounds['end']]
        if actual.empty or actual.index.get_level_values('datetime').max().year!=pd.Timestamp(bounds['end']).year:
            raise ValueError('Historical holdout is missing or incomplete')
        features=build_features(panel.loc[:bounds['end']])
        metrics=[]; details=[]; ics=[]
        for name in frozen['selection']:
            ic=rank_ic(features,name,**bounds,minimum=cfg['minimum_cross_section'])
            ics.append(ic.reset_index().assign(factor=name))
            for mode in ('long_short','long_only'):
                daily=simulate(features,name,**bounds,cost=cfg['cost'],minimum=cfg['minimum_cross_section'],fraction=cfg['quantile_fraction'],mode=mode)
                details.append(daily); metrics.append({'factor':name,'mode':mode,**nav_metrics(daily),**ic_metrics(ic)})
        benchmark=simulate(features,frozen['selection'][0],**bounds,cost=cfg['cost'],mode='equal_weight').assign(factor='baseline_equal_weight')
        details.append(benchmark); metrics.append({'factor':'baseline_equal_weight','mode':'equal_weight',**nav_metrics(benchmark)})
        pd.DataFrame(metrics).to_csv(output/'metrics.csv',index=False)
        pd.concat(details).to_csv(output/'daily.csv.gz',index=False,compression='gzip')
        pd.concat(ics).to_csv(output/'ic.csv.gz',index=False,compression='gzip')
        json_write(output/'data_quality.json',quality)
        json_write(output/'manifest.json',{'status':'complete','completed_at_utc':utc_now().isoformat(),'freeze_sha256':file_hash(freeze_path),
                   'input_sha256':file_hash(input_path),'bounds':bounds,'selection':frozen['selection'],'reselected':False,
                   'genuinely_post_freeze_data':False,'limitations':cfg['universe_note']+' '+cfg['execution_note']})
    except Exception as exc:
        json_write(output/'failure.json',{'status':'failed_access_still_consumed','error':str(exc)}); raise
    return output

def validate_forward_date(asof,frozen_at,now):
    tz=timezone(timedelta(hours=8))
    cutoff=datetime.combine(pd.Timestamp(asof).date(),datetime.min.time(),tz).replace(hour=15)
    if not datetime.fromisoformat(frozen_at)<cutoff<=now:
        raise ValueError('Signal close must occur after freeze and before current time; no backfilled future claims')
    if now.astimezone(tz).date()!=cutoff.date(): raise ValueError('Only today after close may be recorded prospectively')

def forward(freeze_path,input_path,asof,output,root=ROOT):
    f=verify_freeze(freeze_path,root); now=utc_now()
    validate_forward_date(asof,f['frozen_at_utc'],now)
    data,_=load_panel(input_path); date=pd.Timestamp(asof)
    if data.index.get_level_values('datetime').max()!=date: raise ValueError('Require data ending exactly on signal date')
    expected=set(pd.read_csv(root/f['config']['input'],usecols=['symbol']).symbol.unique())
    if set(data.index.get_level_values('symbol'))!=expected: raise ValueError('Frozen universe must be unchanged')
    features=build_features(data)
    today=features.xs(date,level='datetime'); selections={}
    for name in f['selection']:
        w=weights(today[name].to_numpy(),today.volume.gt(0).to_numpy(),fraction=f['config']['quantile_fraction'],minimum=f['config']['minimum_cross_section'])
        selections[name]=[{'symbol':s,'score':None if pd.isna(v) else float(v),'target_weight':float(x)} for s,v,x in zip(today.index,today[name],w)]
    output.mkdir(parents=True,exist_ok=True); target=output/(str(date.date())+'.json')
    with target.open('x',encoding='utf-8') as out:
        json.dump({'recorded_at_utc':now.isoformat(),'signal_date':str(date.date()),'freeze_sha256':file_hash(freeze_path),
                   'input_sha256':file_hash(input_path),'signals':selections,'execution':'proposed next-open target; no orders submitted; actual next-open eligibility still required',
                   'outcomes':'pending; never substitute historical backfill'},out,indent=2,allow_nan=False)
    return target

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('freeze'); a.add_argument('--run',type=Path,default=ROOT/'runs/revised_v2'); a.add_argument('--output',type=Path,default=ROOT/'config/freeze_manifest.json')
    for cmd in ('verify','holdout','forward'):
        a=sub.add_parser(cmd); a.add_argument('--freeze',type=Path,default=ROOT/'config/freeze_manifest.json')
        if cmd!='verify': a.add_argument('--input',type=Path,required=True); a.add_argument('--output',type=Path,required=True)
        if cmd=='forward': a.add_argument('--asof',required=True)
    a=p.parse_args()
    if a.command=='freeze': print(json.dumps(freeze(a.run,a.output),ensure_ascii=False,indent=2))
    elif a.command=='verify': print(json.dumps({'verified':True,'selection':verify_freeze(a.freeze)['selection']}))
    elif a.command=='holdout': print(holdout(a.freeze,a.input,a.output))
    else: print(forward(a.freeze,a.input,a.asof,a.output))

if __name__=='__main__': main()
