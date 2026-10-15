"""Verify immutable forward snapshots and signal provenance, without fetching or scoring."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import pandas as pd
from research_core import ROOT, file_hash
from research_control import verify_freeze, validate_forward_date


def verify(root=ROOT):
    freeze_path = root/'config/freeze_manifest.json'
    frozen = verify_freeze(freeze_path, root)
    freeze_hash = file_hash(freeze_path)
    expected = set(pd.read_csv(root/frozen['config']['input'], usecols=['symbol']).symbol)
    snapshots = {}
    latest = None
    failed = []
    manifests = sorted((root/'data/forward_v2').glob('*/manifest.json'))
    for summary_path in sorted((root/'data/forward_v2').glob('*/summary.json')):
        if json.loads(summary_path.read_text(encoding='utf-8'))['status']=='failed':
            failed.append(summary_path.parent.name)
    for path in manifests:
        m = json.loads(path.read_text(encoding='utf-8')); folder = path.parent
        if m['status']!='complete' or m['freeze_sha256']!=freeze_hash or set(m['symbols'])!=expected:
            raise ValueError('Snapshot freeze/universe mismatch')
        for name, digest in m['artifacts'].items():
            target = (folder/name).resolve()
            if not target.is_relative_to(folder.resolve()) or file_hash(target)!=digest:
                raise ValueError('Snapshot artifact changed: '+name)
        if file_hash(folder/'panel.csv.gz')!=m['input_sha256']:
            raise ValueError('Snapshot input hash mismatch')
        if datetime.fromisoformat(m['completed_at_utc'])>datetime.now(timezone.utc):
            raise ValueError('Snapshot timestamp in future')
        data = pd.read_csv(folder/'panel.csv.gz', dtype={'symbol':str})
        if data.duplicated(['datetime','symbol']).any() or len(data)!=m['rows']:
            raise ValueError('Snapshot row identity mismatch')
        if set(data.symbol)!=expected or data.datetime.max()!=m['end']:
            raise ValueError('Snapshot end/universe mismatch')
        missing = data.observation_kind.eq('provider_confirmed_delisted_no_quote')
        if data.loc[missing,['open','high','low','close']].notna().any().any():
            raise ValueError('Delisted rows have fabricated prices')
        snapshots.setdefault(m['input_sha256'], []).append((folder,m))
        if latest is None or m['end']>latest[1]['end']:
            latest = (folder,m)
    records = []
    for path in sorted((root/'runs/forward_v2').glob('*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record['freeze_sha256']!=freeze_hash or set(record['signals'])!=set(frozen['selection']):
            raise ValueError('Signal freeze/selection mismatch')
        validate_forward_date(record['signal_date'], frozen['frozen_at_utc'], datetime.fromisoformat(record['recorded_at_utc']))
        candidates = [(folder,m) for folder,m in snapshots.get(record['input_sha256'],[]) if not m['observe_only'] and m['end']==record['signal_date'] and m['completed_at_utc']<=record['recorded_at_utc']]
        if not candidates:
            raise ValueError('Signal has no preceding same-day immutable snapshot')
        summaries = [json.loads((folder/'summary.json').read_text(encoding='utf-8')) for folder,_ in candidates]
        relative = str(path.relative_to(root)).replace('\\','/')
        if not any(s.get('signal')==relative and s.get('signal_sha256')==file_hash(path) and s.get('signal_created') for s in summaries):
            raise ValueError('Signal differs from the collection completion record')
        for rows in record['signals'].values():
            if len(rows)!=len(expected) or {r['symbol'] for r in rows}!=expected:
                raise ValueError('Signal universe mismatch')
        if path.stem!=record['signal_date']:
            raise ValueError('Signal filename mismatch')
        records.append(record)
    mature = []
    if latest:
        dates = sorted(pd.read_csv(latest[0]/'panel.csv.gz', usecols=['datetime']).datetime.unique())
        mature = [r['signal_date'] for r in records if len([d for d in dates if d>r['signal_date']])>=2]
    return {'passed':True, 'snapshot_count':len(manifests), 'signal_count':len(records),
            'signal_dates':[r['signal_date'] for r in records], 'mature_signal_dates':mature,
            'pending_signal_dates':[r['signal_date'] for r in records if r['signal_date'] not in mature],
            'latest_snapshot':str(latest[0].relative_to(root)).replace('\\','/') if latest else None,
            'latest_data_date':latest[1]['end'] if latest else None, 'failed_attempts':failed,
            'scope':'Provenance and maturity only. Historical snapshot dates without timely signals are not forward performance.'}


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path); a=p.parse_args()
    result=verify()
    if a.output:
        a.output.parent.mkdir(parents=True,exist_ok=True)
        a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
