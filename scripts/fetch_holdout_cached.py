"""Transport-only retry/cache wrapper for the frozen BaoStock data request.

Added after first freeze because the provider timed out after 46/50 symbols.
Does not change universe, fields, adjustment, date range, factors or selection.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import time
import pandas as pd
import baostock as bs
from research_control import verify_freeze
from research_core import ROOT,file_hash

def main():
    p=argparse.ArgumentParser(); p.add_argument('--freeze',type=Path,default=ROOT/'config/freeze_manifest.json')
    p.add_argument('--output',type=Path,default=ROOT/'data/holdout_2021_2025.csv'); a=p.parse_args()
    f=verify_freeze(a.freeze)
    if a.output.exists() or a.freeze.with_name(a.freeze.stem+'.holdout_access.json').exists(): raise ValueError('Preserve input and consumed holdout')
    freeze_hash=file_hash(a.freeze); cache=ROOT/'.cache'/('holdout-'+freeze_hash[:16]); cache.mkdir(parents=True,exist_ok=True)
    symbols=sorted(pd.read_csv(ROOT/f['config']['input'],usecols=['symbol']).symbol.unique())
    fields='date,code,open,high,low,close,volume,amount,turn,pctChg,tradestatus,isST,adjustflag'
    socket.setdefaulttimeout(35); started=datetime.now(timezone.utc).isoformat(); all_rows=[]; retrieval=[]
    events=(cache/'transport_events.jsonl').open('a',encoding='utf-8')
    def event(kind,**values):
        events.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'event':kind,**values})+'\n'); events.flush()
    def login():
        r=bs.login()
        if r.error_code!='0': raise RuntimeError('BaoStock login failed '+r.error_code)
    login()
    try:
        for i,symbol in enumerate(symbols,1):
            chunk=cache/(symbol+'.csv'); meta=cache/(symbol+'.json')
            if chunk.exists() and meta.exists():
                m=json.loads(meta.read_text());
                if file_hash(chunk)!=m['sha256']: raise ValueError('Cached data changed')
                frame=pd.read_csv(chunk,dtype=str,keep_default_na=False)
            else:
                for attempt in range(3):
                    try:
                        r=bs.query_history_k_data_plus(symbol,fields,start_date='2020-08-01',end_date='2025-12-31',frequency='d',adjustflag='2')
                        if r.error_code!='0': raise RuntimeError('query_error_'+r.error_code)
                        rows=[]
                        while r.next(): rows.append(r.get_row_data())
                        if r.error_code!='0' or not rows: raise RuntimeError('incomplete_query')
                        frame=pd.DataFrame(rows,columns=r.fields)
                        frame.to_csv(chunk,index=False)
                        m={'symbol':symbol,'retrieved_at':datetime.now(timezone.utc).isoformat(),'sha256':file_hash(chunk),'rows':len(frame)}
                        meta.write_text(json.dumps(m,indent=2),encoding='utf-8'); event('downloaded',**m); break
                    except Exception as exc:
                        event('retry',symbol=symbol,attempt=attempt+1,error=type(exc).__name__)
                        if attempt==2: raise
                        try: bs.logout()
                        except Exception: pass
                        time.sleep(1); login()
            all_rows.append(frame); retrieval.append(m)
            print(f'completed {i}/{len(symbols)} {symbol} rows={len(frame)}',flush=True)
        result=pd.concat(all_rows,ignore_index=True).rename(columns={'date':'datetime','code':'symbol'})
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x',encoding='utf-8',newline='') as out: result.to_csv(out,index=False)
        manifest={'provider':'BaoStock','source_api':'query_history_k_data_plus','fields':fields,'adjustflag':'2 (forward adjusted)',
                  'start':'2020-08-01','end':'2025-12-31','warmup':'2020 only, not evaluated','started_at_utc':started,
                  'completed_at_utc':datetime.now(timezone.utc).isoformat(),'rows':len(result),'symbols':len(symbols),
                  'input_sha256':file_hash(a.output),'freeze_sha256':freeze_hash,'transport_source_sha256':file_hash(__file__),
                  'transport_note':'Per-symbol cache/retry added after freeze; frozen request parameters unchanged; no factor evaluation during retrieval.',
                  'retrieval_by_symbol':retrieval,'note':'Frozen 2020 universe, retrieval-vintage forward adjustment, no point-in-time membership.'}
        a.output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        event('complete',input_sha256=file_hash(a.output)); print(a.output)
    finally:
        bs.logout(); events.close()

if __name__=='__main__': main()
