"""Owner-home staging primitives; no system-unit installation or activation."""
import hashlib,os,stat
from pathlib import Path
from guarded_writer import Writer,DIR_FLAGS,trusted
from owner_agent_plan import plan as build_plan
from verify import ROOT

def open_home(home,owner_uid):
 home=Path(home)
 if not home.is_absolute() or '..' in home.parts:raise ValueError('Absolute owner home required')
 fd=os.open('/',DIR_FLAGS)
 try:
  trusted(fd,0)
  for index,part in enumerate(home.parts[1:]):
   child=os.open(part,DIR_FLAGS,dir_fd=fd)
   try:trusted(child,owner_uid if index==len(home.parts)-2 else 0)
   except BaseException:os.close(child);raise
   os.close(fd);fd=child
  return fd
 except BaseException:os.close(fd);raise

def prepare(home_fd,plan):
 if os.getuid()==0 or plan['owner_uid']!=os.getuid() or plan['owner_gid']!=os.getgid():raise ValueError('Run phase as exact non-root wallet owner')
 if plan!=build_plan(plan['owner_uid'],plan['owner_gid'],plan['owner_home']):raise ValueError('Owner plan altered')
 opened=trusted(home_fd,plan['owner_uid']);named=os.stat(plan['owner_home'],follow_symlinks=False)
 if not stat.S_ISDIR(named.st_mode) or (named.st_dev,named.st_ino)!=(opened.st_dev,opened.st_ino):raise ValueError('Owner home handle differs from plan')
 missing=[];fd=os.dup(home_fd)
 try:
  for relative,leaf in (('.local','.local'),('.local/share','share')):
   try:child=os.open(leaf,DIR_FLAGS,dir_fd=fd)
   except FileNotFoundError:
    missing.extend([n for n in ('.local','.local/share') if n==relative or n.startswith(relative+'/')]);break
   try:trusted(child,plan['owner_uid'])
   except BaseException:os.close(child);raise
   os.close(fd);fd=child
  if not missing:
   try:os.stat('yerbas-ai-control-v1',dir_fd=fd,follow_symlinks=False)
   except FileNotFoundError:pass
   else:raise ValueError('Existing agent destination preserved')
 finally:os.close(fd)
 raw=(ROOT/plan['code']['source']).read_bytes()
 if hashlib.sha256(raw).hexdigest()!=plan['code']['sha256']:raise ValueError('Agent source differs')
 return missing,raw

def stage(home_fd,plan,journal):
 missing,raw=prepare(home_fd,plan);home=Path(plan['owner_home']);writer=Writer(home_fd,plan['owner_uid'],journal)
 try:
  for name in missing:writer.mkdir(name,0o700)
  for path in sorted(plan['directories'],key=lambda x:(len(Path(x).parts),x)):
   writer.mkdir(str(Path(path).relative_to(home)),0o700)
  name=str(Path(plan['code']['destination']).relative_to(home));writer.write(name,raw,plan['code']['sha256'],0o600)
  metadata={r['path']:dict(uid=plan['owner_uid'],gid=plan['owner_gid'],mode=0o700 if r['kind']=='directory' else 0o600) for r in writer.created}
  writer.finalize(metadata)
  return dict(staged=True,created_entries=len(metadata),system_unit_installed=False,agent_started=False,existing_state_copied=False)
 finally:writer.close()
