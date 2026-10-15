"""Check local Markdown links, Wiki frontmatter and orphan pages (no web access)."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import re
from urllib.parse import unquote

def check(root):
    paths=[root/'README.md']
    for name in ('docs','wiki'): paths+=list((root/name).rglob('*.md'))
    paths=[p for p in paths if p.is_file()]
    titles={}; stems={}
    for path in paths:
        content=path.read_text(encoding='utf-8-sig')
        title=re.search(r'^title:\s*(.+)$',content,re.M)
        if title: titles.setdefault(title.group(1).strip('"\''),[]).append(path)
        stems.setdefault(path.stem,[]).append(path)
    issues=[]; referenced=set(); count=0
    for path in paths:
        text=path.read_text(encoding='utf-8-sig')
        # Code examples are not documentation links.
        prose=re.sub(r'```.*?```','',text,flags=re.S)
        for target in re.findall(r'\]\(([^)]+)\)',prose):
            target=target.strip().strip('<>')
            if re.match(r'^[a-zA-Z]+:',target) or target.startswith('#'): continue
            count+=1; relative=unquote(target.split('#')[0]); dest=(path.parent/relative).resolve()
            if not dest.exists(): issues.append({'file':str(path.relative_to(root)),'kind':'broken_link','target':relative})
            else: referenced.add(dest)
        if (root/'wiki') in path.parents:
            if not text.startswith('---\n'): issues.append({'file':str(path.relative_to(root)),'kind':'frontmatter_missing'})
            front=text.split('---',2)[1] if text.startswith('---') else ''
            for field in ('title','type','status','updated','sources','tags'):
                if not re.search('^'+field+':',front,re.M): issues.append({'file':str(path.relative_to(root)),'kind':'frontmatter_field_missing','field':field})
            for target in re.findall(r'\[\[([^]|]+)(?:\|[^]]+)?\]\]',prose):
                if '/' in target or '\\' in target:
                    relative=(path.parent/(target if target.endswith('.md') else target+'.md')).resolve()
                    found={relative} if relative.is_file() else set()
                else:
                    # Wiki filenames/aliases take precedence over display titles.
                    found=set(stems.get(target,[]) or titles.get(target,[]))
                count+=1
                if not found: issues.append({'file':str(path.relative_to(root)),'kind':'unresolved_wikilink','target':target})
                elif len(found)>1: issues.append({'file':str(path.relative_to(root)),'kind':'ambiguous_wikilink','target':target})
                else: referenced.update(p.resolve() for p in found)
    for path in paths:
        if (root/'wiki') in path.parents and path.name!='index.md' and path.resolve() not in referenced:
            issues.append({'file':str(path.relative_to(root)),'kind':'orphan_wiki_page'})
    return {'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'pass' if not issues else 'failed',
            'markdown_files':len(paths),'local_links':count,'scope':'README/docs/wiki local targets, Wiki frontmatter, title resolution and incoming links; external URLs and factual claims require human review','issues':issues}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',type=Path,default=Path('docs/checks/documentation.json')); a=p.parse_args()
    result=check(Path(__file__).resolve().parents[1]); a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2))
    return int(bool(result['issues']))

if __name__=='__main__': raise SystemExit(main())
