"""Run offline checks and retain real stdout/stderr/exit codes. Never logs in or trades."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    out=ROOT/'docs/checks'; out.mkdir(parents=True,exist_ok=True)
    research=(ROOT/'scripts/research_core.py').exists()
    syntax="from pathlib import Path; paths=list(Path('scripts').rglob('*.py'))+list(Path('tests').glob('*.py')); [compile(p.read_text(encoding='utf-8-sig'),str(p),'exec') for p in paths]; print('Compiled',len(paths),'Python files without executing them.')"
    commands=[('syntax',['-c',syntax])]
    if research:
        commands+=[('unit_tests',['-m','unittest','discover','-s','tests','-v']),
                   ('freeze_integrity',['scripts/research_control.py','verify']),
                   ('results_integrity',['scripts/verify_results.py']),
                   ('forward_provenance',['scripts/verify_forward.py','--output','docs/checks/forward_status.json'])]
    else:
        commands+=[('unit_tests',['-S','-m','unittest','discover','-s','scripts/simnow','-p','test_*.py','-v']),
                   ('evidence_integrity',['scripts/verify_evidence.py'])]
    commands += [('documentation',['scripts/check_docs.py','--output','docs/checks/documentation.json']),
                 ('security',['scripts/check_secrets.py','--output','docs/checks/security.json'])]
    records=[]
    for name,args in commands:
        start=datetime.now(timezone.utc).isoformat(); before=time.monotonic()
        done=subprocess.run([sys.executable,'-B',*args],cwd=ROOT,capture_output=True)
        (out/(name+'.stdout.log')).write_bytes(done.stdout); (out/(name+'.stderr.log')).write_bytes(done.stderr)
        records.append({'check':name,'arguments':args,'started_at_utc':start,'duration_seconds':round(time.monotonic()-before,3),
                        'exit_code':done.returncode,'stdout':name+'.stdout.log','stderr':name+'.stderr.log'})
        print(name,'PASS' if done.returncode==0 else 'FAIL',flush=True)
    paths=list((ROOT/'scripts').rglob('*.py'))+list((ROOT/'tests').glob('*.py'))
    manifest={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'scope':'local offline checks; no account connection or orders',
              'python':sys.version,'all_passed':all(r['exit_code']==0 for r in records),'checks':records,
              'source_sha256':{str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}}
    (out/'local_checks.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return int(not manifest['all_passed'])

if __name__=='__main__': raise SystemExit(main())
