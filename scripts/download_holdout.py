"""Download one fixed BaoStock panel after freeze; do not choose factors from it."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import pandas as pd
import baostock as bs
from research_core import ROOT,file_hash

def main():
    from research_control import verify_freeze
    p=argparse.ArgumentParser(); p.add_argument('--freeze',type=Path,default=ROOT/'config/freeze_manifest.json')
    p.add_argument('--output',type=Path,default=ROOT/'data/holdout_2021_2025.csv'); a=p.parse_args()
    f=verify_freeze(a.freeze)
    if a.output.exists(): raise ValueError('Do not overwrite archived input')
    ledger=a.freeze.with_name(a.freeze.stem+'.holdout_access.json')
    if ledger.exists(): raise ValueError('Holdout already consumed; do not refresh the source after inspection')
    symbols=sorted(pd.read_csv(ROOT/f['config']['input'],usecols=['symbol']).symbol.unique())
    socket.setdefaulttimeout(25)
    rows=[]; started=datetime.now(timezone.utc).isoformat()
    result=bs.login()
    if result.error_code!='0': raise RuntimeError('BaoStock login failed: '+result.error_code)
    fields='date,code,open,high,low,close,volume,amount,turn,pctChg,tradestatus,isST,adjustflag'
    try:
        for i,symbol in enumerate(symbols,1):
            r=bs.query_history_k_data_plus(symbol,fields,start_date='2020-08-01',end_date='2025-12-31',frequency='d',adjustflag='2')
            if r.error_code!='0': raise RuntimeError('BaoStock query failed: '+r.error_code)
            values=[]
            while r.next(): values.append(r.get_row_data())
            if r.error_code!='0' or not values: raise RuntimeError('Incomplete BaoStock response for '+symbol)
            rows.append(pd.DataFrame(values,columns=r.fields))
            print(f'downloaded {i}/{len(symbols)} {symbol} rows={len(values)}',flush=True)
    finally: bs.logout()
    frame=pd.concat(rows,ignore_index=True).rename(columns={'date':'datetime','code':'symbol'})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8',newline='') as out: frame.to_csv(out,index=False)
    info={'provider':'BaoStock','source_api':'query_history_k_data_plus','adjustflag':'2 (forward adjusted)',
          'start':'2020-08-01','end':'2025-12-31','warmup':'2020 only, not evaluated',
          'started_at_utc':started,'completed_at_utc':datetime.now(timezone.utc).isoformat(),
          'rows':len(frame),'symbols':len(symbols),'input_sha256':file_hash(a.output),'freeze_sha256':file_hash(a.freeze),
          'note':'Frozen 2020 universe; retrieval date adjustment vintage; no point-in-time membership reconstruction.'}
    a.output.with_suffix('.manifest.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    print(a.output)

if __name__=='__main__': main()
