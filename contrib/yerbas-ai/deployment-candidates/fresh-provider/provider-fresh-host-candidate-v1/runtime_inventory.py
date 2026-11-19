"""Hash local wheels against the historical runtime lock. Never installs/downloads."""
import argparse,hashlib,json,os,re,stat
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def inspect(manifest,directory):
 directory=Path(directory)
 if directory.is_symlink() or not directory.is_dir():raise ValueError('Real existing wheel directory required')
 rows=[];seen=set()
 for item in manifest['packages']:
  name=item['filename'];digest=item['sha256']
  if not isinstance(name,str) or Path(name).name!=name or '/' in name or '\\' in name or not name.endswith('.whl') or name in seen:raise ValueError('Invalid/duplicate wheel name')
  if not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Invalid wheel hash')
  seen.add(name);path=directory/name
  try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
  except FileNotFoundError:rows.append(dict(filename=name,status='missing'));continue
  try:
   before=os.fstat(fd)
   if not stat.S_ISREG(before.st_mode) or before.st_size>4*1024**3:raise ValueError('Bounded regular wheel required')
   h=hashlib.sha256()
   while True:
    chunk=os.read(fd,1024*1024)
    if not chunk:break
    h.update(chunk)
   after=os.fstat(fd)
   if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('Wheel changed during inspection')
   rows.append(dict(filename=name,status='verified' if h.hexdigest()==digest else 'hash_mismatch',bytes=before.st_size))
  finally:os.close(fd)
 return dict(passed=bool(rows) and all(x['status']=='verified' for x in rows),wheels=rows,network_used=False,installed=False,gpu_compatibility_verified=False)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('wheel_directory',type=Path);a=p.parse_args()
 from verify import verify
 verify(ROOT)
 result=inspect(json.loads((ROOT/'runtime/WHEELS.json').read_text()),a.wheel_directory);print(json.dumps(result,indent=2));return 0 if result['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
