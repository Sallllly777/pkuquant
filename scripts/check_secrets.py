"""Conservative local text/history/archive credential scan. Reports locations, never values.

Not proof that all secrets are absent; rotate/revoke any previously exposed credential.
Ignored local credential/CTP flow directories are intentionally outside this scan.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile
from datetime import datetime,timezone

EXTENSIONS={'.py','.ps1','.md','.json','.yml','.yaml','.toml','.ini','.txt','.log','.jsonl','.env'}
TOKENS=re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}|sk-[A-Za-z0-9_-]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
LITERALS=re.compile(r'''(?ix)["']?(?:password|passwd|userid|investorid|accountid|api_key|token|authcode)["']?\s*[:=]\s*["']([^"'\r\n]+)["']''')
PLACEHOLDERS={'secret','test','dummy','password','your_password','your_userid','your_token','your_api_key','...','0000000000000000'}

def inspect_text(label,data):
    findings=[]
    for line,text in enumerate(data.decode('utf-8',errors='replace').splitlines(),1):
        if TOKENS.search(text): findings.append({'path':label,'line':line,'rule':'token_or_private_key'})
        for match in LITERALS.finditer(text):
            value=match.group(1)
            if re.fullmatch(r'\$\{[A-Z0-9_]+\}',value): continue
            if value.lower() in PLACEHOLDERS or any(w in value for w in ('你的','示例','REPLACE','PLACEHOLDER','<','>')): continue
            # Literal assignments only; short enumeration codes are not credentials.
            if len(value)>=6: findings.append({'path':label,'line':line,'rule':'credential_literal_review'})
    return findings

def scan(root,history=True):
    paths=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).split(b'\0')
    findings=[]; files=archives=blobs=0
    def inspect_blob(label,data):
        nonlocal archives,files
        suffix=Path(label).suffix.lower()
        if suffix in EXTENSIONS or Path(label).name=='.env':
            files+=1; findings.extend(inspect_text(label,data))
        elif suffix=='.zip':
            archives+=1
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for item in archive.infolist():
                    if item.file_size<20_000_000 and Path(item.filename).suffix.lower() in EXTENSIONS:
                        findings.extend(inspect_text(label+'!'+item.filename,archive.read(item)))
    for raw in paths:
        if not raw: continue
        relative=raw.decode('utf-8'); p=root/relative
        if p.is_file() and p.stat().st_size<20_000_000: inspect_blob(relative,p.read_bytes())
    if history:
        objects=subprocess.check_output(['git','rev-list','--objects','--all'],cwd=root,text=True,encoding='utf-8').splitlines()
        for item in objects:
            parts=item.split(' ',1)
            if len(parts)<2 or Path(parts[1]).suffix.lower() not in EXTENSIONS|{'.zip'}: continue
            kind=subprocess.check_output(['git','cat-file','-t',parts[0]],cwd=root,text=True).strip()
            if kind!='blob': continue
            data=subprocess.check_output(['git','cat-file','blob',parts[0]],cwd=root); blobs+=1
            inspect_blob('history/'+parts[0][:12]+'/'+parts[1],data)
    return {'at_utc':datetime.now(timezone.utc).isoformat(),'status':'pass' if not findings else 'review_required',
            'scope':'git-visible working files and all locally reachable history; textual ZIP members included',
            'limitations':'Heuristic scan, not exhaustive. Does not inspect remote-only commits, ignored DPAPI credentials or native binary flow files.',
            'text_blobs_scanned':files,'archives_scanned':archives,'history_blobs_scanned':blobs,'findings':findings}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]); p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); result=scan(a.root.resolve()); a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(bool(result['findings']))

if __name__=='__main__': raise SystemExit(main())
