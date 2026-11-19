"""Read-only journal/filesystem comparison. Never resumes, removes or repairs."""
import argparse,hashlib,json,os,stat
from pathlib import Path
from install_journal import read,inspect
from guarded_writer import DIR_FLAGS,parts

def open_entry(root_fd,name,directory):
 components=parts(name);fd=os.dup(root_fd)
 try:
  for component in components[:-1]:
   child=os.open(component,DIR_FLAGS,dir_fd=fd);os.close(fd);fd=child
  return os.open(components[-1],DIR_FLAGS if directory else os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
 finally:os.close(fd)

def reconcile(root,journal,expected_plan_sha256):
 events,_=read(journal);summary=inspect(journal)
 if summary['plan_sha256']!=expected_plan_sha256:raise ValueError('Different installation plan')
 completed={};final_meta=None;finalized=False
 for event in events[1:]:
  op=event['operation']
  if event['kind']=='intent' and op=='finalize':final_meta=event['metadata']
  if event['kind']!='complete':continue
  if op=='finalize':finalized=True;continue
  row=event.get('created',{})
  if row.get('kind') not in ('directory','file') or not row.get('complete'):raise ValueError('Completed inode binding missing')
  name=row['path'];parts(name)
  if op!=('mkdir:' if row['kind']=='directory' else 'write:')+name or name in completed:raise ValueError('Ambiguous completed operation')
  completed[name]=row
 if finalized and (not isinstance(final_meta,dict) or set(final_meta)!=set(completed)):raise ValueError('Final ownership plan differs')
 root=Path(root)
 # Refuse symlinks throughout the supplied root path as well as below it.
 for p in (root,*root.parents):
  if p.is_symlink():raise ValueError('Symlink root ancestry')
 root_fd=os.open(root,DIR_FLAGS);checks=[]
 try:
  for name,row in completed.items():
   differences=[];fd=None
   try:
    fd=open_entry(root_fd,name,row['kind']=='directory');info=os.fstat(fd)
    if (info.st_dev,info.st_ino)!=(row['device'],row['inode']):differences.append('inode_replaced')
    if row['kind']=='file':
     if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('Unexpected file type/link count')
     if info.st_size>16*1024*1024:raise ValueError('File exceeds staged-code bound')
     with os.fdopen(os.dup(fd),'rb') as stream:h=hashlib.file_digest(stream,'sha256').hexdigest()
     if h!=row['sha256']:differences.append('content_changed')
     after=os.fstat(fd)
     if (info.st_size,info.st_mtime_ns,info.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):differences.append('changed_during_read')
    if finalized:
     meta=final_meta[name]
     if (info.st_uid,info.st_gid)!=(meta['uid'],meta['gid']):differences.append('ownership_changed')
     if stat.S_IMODE(info.st_mode)!=meta['mode']:differences.append('mode_changed')
   except (OSError,ValueError) as exc:differences.append(type(exc).__name__)
   finally:
    if fd is not None:os.close(fd)
   checks.append(dict(path=name,matches=not differences,differences=differences))
 finally:os.close(root_fd)
 passed=finalized and not summary['pending_operations'] and all(r['matches'] for r in checks)
 return dict(passed=passed,plan_sha256=expected_plan_sha256,checks=checks,finalization_recorded=finalized,pending_operations=summary['pending_operations'],inspection_required=not passed,automatic_retry=False,recovery_authorized=False,mutations=False,scope='recorded entries only; does not assert absence of extra files or installation readiness')
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--journal',type=Path,required=True);p.add_argument('--plan-sha256',required=True);a=p.parse_args();r=reconcile(a.root,a.journal,a.plan_sha256);print(json.dumps(r,indent=2));return 0 if r['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
