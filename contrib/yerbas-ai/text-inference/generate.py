#!/usr/bin/env python3
"""Yerbas AI portable text model — local CPU inference, no installation."""
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def verify():
    release=json.loads((ROOT/'RELEASE.json').read_text())
    for name,expected in release['files'].items():
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():raise ValueError('Invalid package path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Package file changed: '+name)
    return release

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prompt',default='Alice ');p.add_argument('--bytes',type=int,default=200);p.add_argument('--seed',type=int,default=731)
    p.add_argument('--verify',action='store_true');p.add_argument('--json',action='store_true');args=p.parse_args()
    release=verify()
    if args.verify:print(json.dumps({'verified':True,'version':release['version'],'files':len(release['files'])},indent=2));return
    sys.path.insert(0,str(ROOT/'runtime'))
    from text_generate import generate
    result=generate(ROOT/'model',args.prompt,args.bytes,args.seed)
    if 'torch' in sys.modules:raise RuntimeError('Portable generation unexpectedly loaded Torch')
    print(json.dumps(result,indent=2,ensure_ascii=False) if args.json else result['text'])
if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,OSError,TimeoutError) as exc:raise SystemExit('Yerbas AI: '+str(exc))
