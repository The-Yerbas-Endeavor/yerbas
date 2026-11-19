"""Read-only, no-follow runtime ownership and content inventory."""
import hashlib,json,os,stat
from pathlib import Path
FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW

def audit(root,expected_uid=0):
 root=Path(root)
 fd=os.open(root,FLAGS)
 rows=[]
 def metadata(st):
  if st.st_uid!=expected_uid or stat.S_IMODE(st.st_mode)&0o022 or st.st_mode&(stat.S_ISUID|stat.S_ISGID):raise ValueError('Runtime entry has unsafe ownership or permissions')
 def walk(directory,prefix):
  before=os.fstat(directory);metadata(before)
  if not stat.S_ISDIR(before.st_mode):raise ValueError('Directory required')
  names=sorted(os.listdir(directory))
  for name in names:
   rel=prefix+'/'+name if prefix else name
   original=os.stat(name,dir_fd=directory,follow_symlinks=False)
   if stat.S_ISLNK(original.st_mode):
    if original.st_uid!=expected_uid:raise ValueError('Runtime link owner differs')
   else:metadata(original)
   mode=stat.S_IMODE(original.st_mode)
   if stat.S_ISLNK(original.st_mode):
    # venv's sole supported alias; do not follow arbitrary wheel links.
    target=os.readlink(name,dir_fd=directory)
    if rel!='lib64' or target!='lib':raise ValueError('Unexpected runtime symlink: '+rel)
    dest=os.stat('lib',dir_fd=directory,follow_symlinks=False)
    if not stat.S_ISDIR(dest.st_mode):raise ValueError('lib64 target is not a real directory')
    metadata(dest);rows.append(dict(path=rel,kind='symlink',target=target));continue
   handle=os.open(name,FLAGS if stat.S_ISDIR(original.st_mode) else os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
   try:
    current=os.fstat(handle)
    if (original.st_dev,original.st_ino)!=(current.st_dev,current.st_ino):raise ValueError('Runtime entry replaced')
    metadata(current)
    if stat.S_ISDIR(current.st_mode):
     rows.append(dict(path=rel,kind='directory',mode=mode));walk(handle,rel)
    elif stat.S_ISREG(current.st_mode):
     if current.st_nlink!=1:raise ValueError('Runtime hard link refused')
     h=hashlib.sha256()
     while True:
      b=os.read(handle,1024*1024)
      if not b:break
      h.update(b)
     after=os.fstat(handle)
     if (current.st_size,current.st_mtime_ns,current.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):raise ValueError('Runtime file changed')
     rows.append(dict(path=rel,kind='file',mode=mode,bytes=current.st_size,sha256=h.hexdigest()))
    else:raise ValueError('Unexpected runtime entry type')
   finally:os.close(handle)
  after=os.fstat(directory)
  if (before.st_mtime_ns,before.st_ctime_ns)!=(after.st_mtime_ns,after.st_ctime_ns) or names!=sorted(os.listdir(directory)):raise ValueError('Runtime directory changed')
 try:walk(fd,'')
 finally:os.close(fd)
 digest=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return dict(passed=True,expected_uid=expected_uid,entries=len(rows),files=sum(r['kind']=='file' for r in rows),tree_sha256=digest,scope='runtime tree only; OS Python and shared libraries remain platform prerequisites',mutations=False)
