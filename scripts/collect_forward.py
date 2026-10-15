"""Append-only BaoStock snapshots and same-day signals; never submits orders.

Transport/data-availability wrapper added after freeze. Frozen numerical code is unchanged.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import time
import uuid
import pandas as pd
from research_core import ROOT, file_hash, load_panel
from research_control import verify_freeze, forward

TZ = timezone(timedelta(hours=8))
FIELDS = 'date,code,open,high,low,close,volume,amount,turn,pctChg,tradestatus,isST,adjustflag'


def save(path, value):
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False, indent=2, allow_nan=False)


def completed_day(calendar, now, observe_only):
    today = now.astimezone(TZ).date().isoformat()
    dates = sorted(calendar.loc[calendar.is_trading_day.eq('1'), 'calendar_date'])
    if observe_only:
        prior = [d for d in dates if d < today]
        if not prior:
            raise ValueError('No completed prior trading day')
        return prior[-1]
    if now.astimezone(TZ).hour < 18:
        raise ValueError('Wait until 18:00 China time for completed provider daily bars')
    if today not in dates:
        raise ValueError('Today is not a provider trading day; never backfill a signal')
    return today


def validate_chunk(frame, symbol, dates, basic):
    """Only a provider-confirmed delisting explains missing rows; other gaps fail closed."""
    if list(frame.columns) != FIELDS.split(','):
        raise ValueError('Unexpected provider schema')
    if not frame.empty and (set(frame.code) != {symbol} or frame.date.duplicated().any()):
        raise ValueError('Unexpected symbol or duplicate date')
    if not set(frame.date).issubset(dates):
        raise ValueError('Provider returned a non-trading or out-of-range date')
    missing = sorted(set(dates)-set(frame.date))
    out_date = basic.get('outDate', '')
    if missing and not (out_date and all(d >= out_date for d in missing)):
        raise ValueError('Unexplained missing trading dates for '+symbol)
    # Explicit empty observations preserve the frozen universe. No fabricated price.
    placeholders = []
    for day in missing:
        row = {key: '' for key in FIELDS.split(',')}
        row.update(date=day, code=symbol, volume='0', tradestatus='0', adjustflag='2')
        placeholders.append(row)
    result = pd.concat([frame, pd.DataFrame(placeholders)], ignore_index=True) if placeholders else frame.copy()
    result['observation_kind'] = result.date.map(lambda d: 'provider_confirmed_delisted_no_quote' if d in missing else 'provider_daily_bar')
    active = result.tradestatus.eq('1')
    numeric = result.loc[active, ['open','high','low','close','volume','turn']].apply(pd.to_numeric, errors='coerce')
    if numeric.isna().any().any() or (numeric[['open','high','low','close']] <= 0).any().any():
        raise ValueError('Missing/invalid active daily bar for '+symbol)
    if not result.loc[~result.date.isin(missing), 'adjustflag'].eq('2').all():
        raise ValueError('Adjustment changed')
    return result.sort_values('date'), len(missing)


def collect(observe_only=False):
    frozen_path = ROOT/'config/freeze_manifest.json'
    frozen = verify_freeze(frozen_path)
    started = datetime.now(TZ)
    # Reject premature signal calls before making network requests.
    if not observe_only and started.hour < 18:
        raise ValueError('Wait until 18:00 China time; use --observe-only for prior-day data')
    signal_path = ROOT/'runs/forward_v2'/f'{started.date()}.json'
    if not observe_only and signal_path.exists():
        raise FileExistsError('Today already has an immutable signal; verify it, do not overwrite')
    folder = ROOT/'data/forward_v2'/(started.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'raw').mkdir()
    journal = (folder/'events.jsonl').open('x', encoding='utf-8')
    def event(kind, **data):
        journal.write(json.dumps({'at_utc':datetime.now(timezone.utc).isoformat(), 'event':kind, **data})+'\n')
        journal.flush()
    result = {'started_at_utc':started.astimezone(timezone.utc).isoformat(), 'observe_only':observe_only,
              'status':'failed', 'signal_created':False, 'folder':str(folder.relative_to(ROOT)).replace('\\','/')}
    import baostock as bs
    socket.setdefaulttimeout(25)
    def login():
        if bs.login().error_code != '0':
            raise RuntimeError('Provider login failed')
    def query(call):
        for attempt in range(3):
            try:
                response = call()
                if response.error_code != '0':
                    raise RuntimeError('Provider query failed: '+response.error_code)
                rows = []
                while response.next():
                    rows.append(response.get_row_data())
                if response.error_code != '0':
                    raise RuntimeError('Incomplete provider query')
                return pd.DataFrame(rows, columns=response.fields)
            except Exception as exc:
                event('transport_retry', attempt=attempt+1, error_type=type(exc).__name__)
                if attempt == 2:
                    raise
                try:
                    bs.logout()
                except Exception:
                    pass
                time.sleep(1)
                login()
    try:
        login()
        start = (started.date()-timedelta(days=180)).isoformat()
        calendar = query(lambda: bs.query_trade_dates(start_date=start, end_date=started.date().isoformat()))
        calendar.to_csv(folder/'calendar.csv', index=False)
        end = completed_day(calendar, started, observe_only)
        dates = sorted(calendar.loc[calendar.is_trading_day.eq('1') & calendar.calendar_date.le(end), 'calendar_date'])
        symbols = sorted(pd.read_csv(ROOT/frozen['config']['input'], usecols=['symbol']).symbol.unique())
        if len(dates) < 80:
            raise ValueError('Insufficient warmup calendar')
        frames, basic_rows, retrieval = [], [], []
        for i, symbol in enumerate(symbols, 1):
            basic_frame = query(lambda: bs.query_stock_basic(code=symbol))
            if len(basic_frame) != 1 or basic_frame.iloc[0]['code'] != symbol:
                raise ValueError('Missing stock metadata for '+symbol)
            basic = basic_frame.iloc[0].to_dict(); basic_rows.append(basic)
            raw = query(lambda: bs.query_history_k_data_plus(symbol, FIELDS, start_date=start, end_date=end, frequency='d', adjustflag='2'))
            raw_path = folder/'raw'/(symbol+'.csv'); raw.to_csv(raw_path, index=False)
            clean, missing = validate_chunk(raw, symbol, dates, basic)
            frames.append(clean)
            info = {'symbol':symbol, 'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
                    'provider_rows':len(raw), 'delisted_missing_rows':missing, 'raw_sha256':file_hash(raw_path)}
            retrieval.append(info); event('symbol_complete', **info)
            print(f'completed {i}/{len(symbols)} {symbol} rows={len(raw)} unavailable={missing}', flush=True)
        pd.DataFrame(basic_rows).to_csv(folder/'stock_basic.csv', index=False)
        panel = pd.concat(frames, ignore_index=True).rename(columns={'date':'datetime','code':'symbol'})
        panel = panel.sort_values(['datetime','symbol'])
        panel_path = folder/'panel.csv.gz'; panel.to_csv(panel_path, index=False, compression='gzip')
        _, quality = load_panel(panel_path)
        if quality['invalid_ohlc_rows']:
            raise ValueError('Invalid OHLC in provider data')
        save(folder/'quality.json', quality)
        event('snapshot_complete', end=end, rows=len(panel)); journal.close()
        manifest = {'schema':1, 'status':'complete', 'provider':'BaoStock', 'source_api':'query_history_k_data_plus',
                    'started_at_utc':result['started_at_utc'], 'completed_at_utc':datetime.now(timezone.utc).isoformat(),
                    'end':end, 'start':start, 'observe_only':observe_only, 'freeze_sha256':file_hash(frozen_path),
                    'collector_sha256':file_hash(__file__), 'input_sha256':file_hash(panel_path),
                    'symbols':symbols, 'rows':len(panel), 'calendar_dates':len(dates), 'fields':FIELDS,
                    'adjustflag':'2', 'retrieval_by_symbol':retrieval,
                    'limits':'Retrieval-vintage adjusted daily bars, not real fills. Missing delisted prices remain blank. Historical dates are not backfilled signals.',
                    'artifacts':{str(p.relative_to(folder)).replace('\\','/'):file_hash(p) for p in sorted(folder.rglob('*')) if p.is_file()}}
        save(folder/'manifest.json', manifest)
        if not observe_only:
            # Frozen function rechecks same-day time, input end, universe and source hashes.
            signal = forward(frozen_path, panel_path, end, ROOT/'runs/forward_v2')
            result.update(signal_created=True, signal=str(signal.relative_to(ROOT)).replace('\\','/'), signal_sha256=file_hash(signal))
        result.update(status='observation_only' if observe_only else 'signal_recorded', end=end, rows=len(panel))
    except Exception as exc:
        result['failure'] = type(exc).__name__+': '+str(exc)
        raise
    finally:
        try:
            bs.logout()
        except Exception:
            pass
        if not journal.closed:
            journal.close()
        result['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        save(folder/'summary.json', result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--observe-only', action='store_true', help='Capture prior completed day only; never create a signal')
    collect(parser.parse_args().observe_only)
