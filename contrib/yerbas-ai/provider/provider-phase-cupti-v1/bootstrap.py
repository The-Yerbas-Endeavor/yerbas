"""Verify root-owned complete runtime before importing its routing modules."""
import hashlib,json,os,runpy,stat,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def checked():
 for p in [ROOT,*ROOT.parents]:
  s=p.lstat()
  if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('Root-owned runtime required')
 def content(p):
  fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  try:
   s=os.fstat(fd)
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or s.st_size>16*1024*1024:raise ValueError('Untrusted runtime file')
   with os.fdopen(fd,'rb',closefd=False) as f:return f.read()
  finally:os.close(fd)
 manifest=json.loads(content(ROOT/'RUNTIME.json'))
 if set(manifest)!={'schema','files'} or manifest['schema']!=1:raise ValueError('Invalid runtime manifest')
 if {p.name for p in ROOT.iterdir()}!=set(manifest['files'])|{'RUNTIME.json'}:raise ValueError('Unexpected runtime files')
 for name,digest in manifest['files'].items():
  if Path(name).name!=name or hashlib.sha256(content(ROOT/name)).hexdigest()!=digest:raise ValueError('Runtime source differs')
 return manifest
if __name__=='__main__':
 checked();sys.path.insert(0,str(ROOT));runpy.run_path(str(ROOT/'phase_router.py'),run_name='__main__')
