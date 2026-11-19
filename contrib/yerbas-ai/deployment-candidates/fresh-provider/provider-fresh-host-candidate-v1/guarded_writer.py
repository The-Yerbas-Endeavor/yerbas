"""Exclusive dirfd-relative primitives. Live apply remains gated off."""
import hashlib,os,stat
from pathlib import PurePosixPath

LOCKS={'var/lib/yerbas-training-experiment/continuous-worker.lock','var/lib/yerbas-training-experiment/gpu-probe.lock'}
def file_modes(name):return (0o660,) if name in LOCKS else (0o600,0o644)

DIR_FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC

def parts(name):
 p=PurePosixPath(name)
 if not isinstance(name,str) or p.is_absolute() or str(p)!=name or not p.parts or any(x in ('.','..') for x in p.parts):raise ValueError('Canonical relative path required')
 return p.parts

def trusted(fd,owner):
 s=os.fstat(fd)
 if not stat.S_ISDIR(s.st_mode) or s.st_uid!=owner or stat.S_IMODE(s.st_mode)&0o022:raise ValueError('Untrusted directory handle')
 return s

class Writer:
 def __init__(self,root_fd,owner,journal=None):
  self.fd=os.dup(root_fd);self.owner=owner;self.created=[];self.sealed=False;self.journal=journal
  try:trusted(self.fd,owner)
  except BaseException:os.close(self.fd);raise
 def event(self,kind,operation,**evidence):
  if self.journal:self.journal.record(dict(kind=kind,operation=operation,**evidence))
 def close(self):os.close(self.fd)
 def parent(self,name):
  components=parts(name);fd=os.dup(self.fd)
  try:
   for component in components[:-1]:
    child=os.open(component,DIR_FLAGS,dir_fd=fd)
    try:trusted(child,self.owner)
    except BaseException:os.close(child);raise
    os.close(fd);fd=child
   trusted(fd,self.owner);return fd,components[-1]
  except BaseException:os.close(fd);raise
 def mkdir(self,name,mode=0o755):
  if self.sealed:raise ValueError("Writer sealed")
  if mode not in (0o700,0o750,0o755):raise ValueError('Unsupported directory mode')
  parent,leaf=self.parent(name)
  try:
   self.event('intent','mkdir:'+name)
   os.mkdir(leaf,0o700,dir_fd=parent)
   # Preserve partial creations on failure; never delete an unverified path.
   self.created.append(dict(path=name,kind='directory'))
   child=os.open(leaf,DIR_FLAGS,dir_fd=parent)
   try:
    info=trusted(child,self.owner);os.fchmod(child,mode);os.fsync(child)
    self.created[-1].update(device=info.st_dev,inode=info.st_ino,complete=True)
   finally:os.close(child)
   os.fsync(parent);self.event('complete','mkdir:'+name,created=dict(self.created[-1]))
  finally:os.close(parent)
 def write(self,name,data,digest,mode=0o644):
  if self.sealed:raise ValueError("Writer sealed")
  if not isinstance(data,bytes) or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Bytes differ from reviewed plan')
  if mode not in file_modes(name):raise ValueError('Unsupported file mode')
  parent,leaf=self.parent(name)
  try:
   self.event('intent','write:'+name)
   fd=os.open(leaf,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=parent)
   self.created.append(dict(path=name,kind='file'))
   try:
    info=os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=self.owner:raise ValueError('Unexpected created file')
    with os.fdopen(os.dup(fd),'wb') as f:f.write(data);f.flush()
    os.fchmod(fd,mode);os.fsync(fd)
    self.created[-1].update(device=info.st_dev,inode=info.st_ino,sha256=digest,complete=True)
   finally:os.close(fd)
   os.fsync(parent);self.event('complete','write:'+name,created=dict(self.created[-1]))
  finally:os.close(parent)

 def finalize(self,metadata):
  if self.sealed:raise ValueError('Writer already sealed')
  if set(metadata)!={r['path'] for r in self.created} or any(not r.get('complete') for r in self.created):raise ValueError('Complete exact creation set required')
  handles=[]
  try:
   # Validate and retain every inode handle before changing any ownership.
   for row in self.created:
    meta=metadata[row['path']]
    if set(meta)!={'uid','gid','mode'} or any(type(meta[k]) is not int or not 0<=meta[k]<2**31 for k in ('uid','gid')):raise ValueError('Invalid ownership')
    allowed=(0o700,0o750,0o755) if row['kind']=='directory' else file_modes(row['path'])
    if type(meta['mode']) is not int or meta['mode'] not in allowed:raise ValueError('Invalid final mode')
    parent,leaf=self.parent(row['path'])
    try:fd=os.open(leaf,DIR_FLAGS if row['kind']=='directory' else os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=parent)
    finally:os.close(parent)
    handles.append((row,meta,fd));info=os.fstat(fd)
    if (info.st_dev,info.st_ino)!=(row['device'],row['inode']) or info.st_uid!=self.owner:raise ValueError('Created inode replaced')
    if row['kind']=='file':
     if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Unexpected file/link')
     with os.fdopen(os.dup(fd),'rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
     if actual!=row['sha256']:raise ValueError('Created content changed')
   self.event('intent','finalize',metadata=metadata)
   self.sealed=True
   # Transfer directories last, deepest first, after all content is validated.
   for row,meta,fd in sorted(handles,key=lambda x:(x[0]['kind']=='directory',-x[0]['path'].count('/'))):
    os.fchown(fd,meta['uid'],meta['gid']);os.fchmod(fd,meta['mode']);os.fsync(fd)
    info=os.fstat(fd)
    if (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(meta['uid'],meta['gid'],meta['mode']):raise ValueError('Final ownership differs')
   os.fsync(self.fd)
   self.event('complete','finalize',entries=len(handles))
   return dict(finalized=True,entries=len(handles),atomic=False)
  finally:
   for _,_,fd in handles:os.close(fd)

def apply(plan):
 # No incomplete candidate can reach filesystem mutation, even under sudo.
 raise ValueError('Live installation disabled: runtime/data/owner-agent provisioning and acceptance incomplete')
