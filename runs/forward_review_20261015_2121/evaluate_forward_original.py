"""Evaluate only prospectively recorded signals with the frozen simulation core.

Research proxy, not actual fills. No live orders; no regeneration of missing signals.
"""
import argparse
from datetime import datetime,timezone,timedelta
import json
from pathlib import Path
import pandas as pd
from research_core import ROOT,load_panel,file_hash,simulate,nav_metrics
from research_control import verify_freeze
from research_pipeline import json_write

def recorded_features(panel,records,selection,freeze_hash):
    features=panel.copy()
    for factor in selection: features[factor]=float('nan')
    seen=set(); tz=timezone(timedelta(hours=8)); calendar=features.index.get_level_values('datetime').unique().sort_values()
    for record in records:
        if record['freeze_sha256']!=freeze_hash: raise ValueError('Signal belongs to a different freeze')
        date=pd.Timestamp(record['signal_date'])
        if date in seen: raise ValueError('Duplicate signal date')
        seen.add(date)
        after=calendar[calendar>date]
        if date not in calendar or len(after)<1: continue
        recorded=datetime.fromisoformat(record['recorded_at_utc'])
        close=datetime.combine(date.date(),datetime.min.time(),tz).replace(hour=15)
        deadline=datetime.combine(after[0].date(),datetime.min.time(),tz).replace(hour=9,minute=30)
        if not close<=recorded<deadline: raise ValueError('Signal was not recorded before next open')
        for factor in selection:
            values=record['signals'][factor]
            if len({r['symbol'] for r in values})!=len(values): raise ValueError('Duplicate symbol in signal')
            expected=set(features.xs(date,level='datetime').index)
            if {r['symbol'] for r in values}!=expected: raise ValueError('Incomplete signal universe')
            for row in values: features.loc[(date,row['symbol']),factor]=row['score']
    return features

def evaluate_modes(features, frozen, start, end):
    details=[]; metrics=[]
    for factor in frozen['selection']:
        for mode in ('long_short','long_only'):
            daily=simulate(features,factor,start,end,frozen['config']['cost'],fraction=frozen['config']['quantile_fraction'],minimum=frozen['config']['minimum_cross_section'],mode=mode)
            details.append(daily); metrics.append({'factor':factor,'mode':mode,**nav_metrics(daily)})
    benchmark=simulate(features,frozen['selection'][0],start,end,frozen['config']['cost'],minimum=frozen['config']['minimum_cross_section'],mode='equal_weight').assign(factor='baseline_equal_weight')
    details.append(benchmark); metrics.append({'factor':'baseline_equal_weight','mode':'equal_weight',**nav_metrics(benchmark)})
    return pd.concat(details), pd.DataFrame(metrics)


def main():
    p=argparse.ArgumentParser(); p.add_argument('--freeze',type=Path,default=ROOT/'config/freeze_manifest.json')
    p.add_argument('--signals',type=Path,required=True); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); frozen=verify_freeze(a.freeze); paths=sorted(a.signals.glob('*.json'))
    if not paths: raise ValueError('No prospective signals; cannot manufacture forward results')
    records=[json.loads(path.read_text(encoding='utf-8')) for path in paths]
    for record in records:
        if datetime.fromisoformat(record['recorded_at_utc'])<=datetime.fromisoformat(frozen['frozen_at_utc']): raise ValueError('Signal predates freeze')
    panel,quality=load_panel(a.input)
    tz=timezone(timedelta(hours=8)); now=datetime.now(tz)
    last=panel.index.get_level_values('datetime').max()
    if datetime.combine(last.date(),datetime.min.time(),tz).replace(hour=9,minute=30)>now: raise ValueError('Future prices are not observations')
    features=recorded_features(panel,records,frozen['selection'],file_hash(a.freeze))
    start=min(r['signal_date'] for r in records); end=str(last.date())
    if len(features.loc[start:end].index.get_level_values('datetime').unique())<3: raise ValueError('Need signal date and two subsequent open observations')
    a.output.mkdir(parents=True,exist_ok=False)
    daily, metrics=evaluate_modes(features,frozen,start,end)
    daily.to_csv(a.output/'daily.csv.gz',index=False,compression='gzip')
    metrics.to_csv(a.output/'metrics.csv',index=False)
    json_write(a.output/'manifest.json',{'generated_at_utc':datetime.now(timezone.utc).isoformat(),'freeze_sha256':file_hash(a.freeze),
              'source_sha256':file_hash(__file__),'input_sha256':file_hash(a.input),'signal_hashes':{p.name:file_hash(p) for p in paths},
              'status':'prospectively_recorded_signal_price_proxy','signal_count':len(records),'date_start':start,'date_end':end,
              'missing_signal_policy':'cash target at next open, subject to held-quote blocking',
              'limits':'Not actual fills; frozen open-price proxy, theoretical shorts, forced terminal liquidation, original universe and data limitations apply.'})
    print(a.output)

if __name__=='__main__': main()
