"""Append-only staging journal. Recovery is inspection-only, never automatic retry."""
import hashlib,json,os,stat
from pathlib import Path
MAX=1024*1024

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def read(path):
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
 try:
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1 or info.st_size>MAX:raise ValueError('Private bounded journal required')
  raw=b''
  while True:
   chunk=os.read(fd,65536)
   if not chunk:break
   raw+=chunk
   if len(raw)>MAX:raise ValueError('Journal too large')
 finally:os.close(fd)
 rows=[];previous='0'*64
 for line in raw.splitlines(keepends=True):
  if not line.endswith(b'\n'):raise ValueError('Incomplete journal tail; operator inspection required')
  row=json.loads(line);digest=row.pop('digest')
  if set(row)!={'sequence','previous','event'} or row['sequence']!=len(rows) or row['previous']!=previous or hashlib.sha256(canonical(row)).hexdigest()!=digest:raise ValueError('Journal chain differs')
  previous=digest;rows.append(row['event'])
 if not rows or rows[0].get('kind')!='plan':raise ValueError('Plan binding missing')
 return rows,previous

class Journal:
 def __init__(self,path,plan_sha256):
  if not isinstance(plan_sha256,str) or len(plan_sha256)!=64 or any(c not in '0123456789abcdef' for c in plan_sha256):raise ValueError('Plan digest required')
  path=Path(path)
  for parent in (path.parent,*path.parent.parents):
   if parent.is_symlink():raise ValueError('Journal symlink parent')
  parent=path.parent.stat()
  if parent.st_uid!=os.getuid() or parent.st_mode&0o077:raise ValueError('Private journal directory required')
  self.fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600);self.sequence=0;self.previous='0'*64;self.closed=False
  try:
   self.record(dict(kind='plan',sha256=plan_sha256))
   directory=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
   try:os.fsync(directory)
   finally:os.close(directory)
  except BaseException:os.close(self.fd);self.closed=True;raise
 def record(self,event):
  if self.closed:raise ValueError('Journal closed')
  row=dict(sequence=self.sequence,previous=self.previous,event=event);digest=hashlib.sha256(canonical(row)).hexdigest();raw=canonical(dict(row,digest=digest))+b'\n'
  if os.fstat(self.fd).st_size+len(raw)>MAX:raise ValueError('Journal bound reached')
  view=memoryview(raw)
  while view:
   count=os.write(self.fd,view)
   if count<=0:raise OSError('Journal write incomplete')
   view=view[count:]
  os.fsync(self.fd);self.sequence+=1;self.previous=digest
 def close(self):
  if not self.closed:os.close(self.fd);self.closed=True

def inspect(path):
 events,_=read(path);pending=[];completed=[]
 for event in events[1:]:
  if event.get('kind')=='intent':pending.append(event['operation'])
  elif event.get('kind')=='complete':
   if not pending or pending[-1]!=event['operation']:raise ValueError('Completion does not match pending operation')
   pending.pop();completed.append(event)
  else:raise ValueError('Unexpected journal event')
 return dict(plan_sha256=events[0]['sha256'],completed_operations=len(completed),pending_operations=pending,inspection_required=bool(pending),automatic_retry=False,rollback_performed=False,filesystem_reconciled=False,scope='journal-only inspection; verify retained files before any recovery decision')
