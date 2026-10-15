"""Reproducible historical development run. Never reads a held-out dataset."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from research_core import (ROOT,load_panel,build_features,rank_ic,simulate,nav_metrics,
                           ic_metrics,select_candidates,wide,file_hash)

def json_write(path,value):
    def clean(x):
        if isinstance(x,dict): return {str(k):clean(v) for k,v in x.items()}
        if isinstance(x,(list,tuple)): return [clean(v) for v in x]
        if isinstance(x,(np.integer,)): return int(x)
        if isinstance(x,(np.floating,float)): return float(x) if np.isfinite(x) else None
        return x
    path.write_text(json.dumps(clean(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def source_hashes():
    return {str(p.relative_to(ROOT)).replace('\\','/'):file_hash(p) for p in sorted((ROOT/'scripts').glob('*.py'))}

def run(config_path,output,input_override=None):
    config=json.loads(config_path.read_text(encoding='utf-8'))
    path=Path(input_override) if input_override else ROOT/config['input']
    output.mkdir(parents=True,exist_ok=False)
    log=(output/'events.jsonl').open('w',encoding='utf-8')
    def event(kind,**data):
        log.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'event':kind,**data})+'\n'); log.flush()
        print(kind, json.dumps(data,ensure_ascii=False),flush=True)
    try:
        event('started',method=config['method_version'])
        panel,quality=load_panel(path)
        panel=panel.loc[config['history']['start']:config['history']['end']]
        # Source can contain later data but this command never evaluates or selects on it.
        features=build_features(panel)
        json_write(output/'data_quality.json',quality)
        names=[c for c in features if c.startswith('O')]
        coverage=features[names].notna().groupby(level='datetime').sum()
        coverage.to_csv(output/'factor_coverage.csv')
        registry=[]
        for name in names:
            registry.append({'factor':name,'version':'corrected_interaction_v2' if 'v2_' in name else 'original_formula_v2_calendar',
                             'valid_rows':int(features[name].notna().sum()),'higher_score':'predicted stronger rebound; interaction baselines may disagree with this hypothesis'})
        json_write(output/'candidate_registry.json',registry)
        phases={key:config[key] for key in ('development_train','development_validation','historical_review','history')}
        metrics=[]; all_daily=[]; all_ic=[]
        for name in names:
            for phase,bounds in phases.items():
                daily=simulate(features,name,**bounds,cost=config['cost'],fraction=config['quantile_fraction'],minimum=config['minimum_cross_section'])
                ic=rank_ic(features,name,**bounds,minimum=config['minimum_cross_section'])
                metrics.append({'factor':name,'phase':phase,**nav_metrics(daily),**ic_metrics(ic)})
                if phase=='history':
                    all_daily.append(daily); all_ic.append(ic.reset_index().assign(factor=name))
            event('candidate_evaluated',factor=name)
        table=pd.DataFrame(metrics)
        ranked,selected=select_candidates(table[table.phase=='development_validation'],config['selection_count'])
        ranked.to_csv(output/'development_selection.csv',index=False)
        table.to_csv(output/'all_metrics.csv',index=False)
        pd.concat(all_daily).to_csv(output/'all_daily_returns.csv.gz',index=False,compression='gzip')
        pd.concat(all_ic).to_csv(output/'all_ic.csv.gz',index=False,compression='gzip')
        selection={'method':config['method_version'],'selected_on':'2019 development validation; already inspected historical data',
                   'factors':[{'factor':name,'reason':'top development score, experimental candidate, not confirmed effectiveness'} for name in selected]}
        json_write(output/'selected_factors.json',selection)
        details=[]; sensitivity=[]; annual=[]
        for name in selected:
            for mode in ('long_short','long_only'):
                d=simulate(features,name,**config['history'],cost=config['cost'],mode=mode)
                details.append(d)
                for bps in config['sensitivity_all_in_bps']:
                    cost={'commission_bps':bps,'slippage_bps':0.,'sell_extra_bps':0.,'short_borrow_annual_bps':0.}
                    scenario=simulate(features,name,**config['history'],cost=cost,mode=mode)
                    sensitivity.append({'factor':name,'mode':mode,'symmetric_all_in_bps':bps,**nav_metrics(scenario)})
                for year in range(2017,2021):
                    dyear=simulate(features,name,f'{year}-01-01',f'{year}-12-31',config['cost'],mode=mode)
                    annual.append({'factor':name,'year':year,'mode':mode,**nav_metrics(dyear)})
            for group in range(1,6):
                details.append(simulate(features,name,**config['history'],cost=config['cost'],mode='long_only',group=group))
        # Same cost/timing model for two transparent baselines.
        details.append(simulate(features,'O06_return_3d',**config['history'],cost=config['cost'],mode='long_only').assign(factor='baseline_reversal_3d'))
        details.append(simulate(features,'O02_low_location_3d',**config['history'],cost=config['cost'],mode='equal_weight').assign(factor='baseline_equal_weight'))
        diagnostics=pd.concat(details,ignore_index=True)
        diagnostics.to_csv(output/'diagnostic_daily.csv.gz',index=False,compression='gzip')
        pd.DataFrame(sensitivity).to_csv(output/'cost_sensitivity.csv',index=False)
        pd.DataFrame(annual).to_csv(output/'annual_metrics.csv',index=False)
        wide(features,selected[0]).stack().to_frame('signal').head(100).to_csv(output/'signal_sample.csv') if selected else None
        if selected:
            correlations=pd.DataFrame({n:features[n] for n in selected}).corr(method='spearman')
            correlations.to_csv(output/'signal_correlations.csv')
            pd.concat(all_daily).pivot(index='datetime',columns='factor',values='net')[selected].corr().to_csv(output/'return_correlations.csv')
        manifest={'started_source':str(path.resolve()),'input_sha256':file_hash(path),'config':config,
                  'config_sha256':file_hash(config_path),'source_sha256':source_hashes(),
                  'generated_at':datetime.now(timezone.utc).isoformat(),'python':platform.python_version(),
                  'dependencies':{n:importlib.metadata.version(n) for n in ('pandas','numpy','scipy','matplotlib')},
                  'git_base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  'git_worktree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                  'history_previously_inspected':True,'holdout_accessed':False,'forward_status':'not_started_not_frozen',
                  'selection':selected,'candidate_count':len(names),'status':'complete'}
        json_write(output/'run_manifest.json',manifest)
        event('completed',selected=selected,output=str(output))
        return output
    except Exception as exc:
        event('failed',error_type=type(exc).__name__,detail=str(exc))
        raise
    finally: log.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',type=Path,default=ROOT/'config/research_v2.json')
    p.add_argument('--input',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'runs/revised_v2')
    a=p.parse_args(); run(a.config,a.output,a.input)

if __name__=='__main__': main()
