"""Generate disabled broker setup only; no installation or account creation."""
import argparse,hashlib,json,os,stat
from pathlib import Path
from verify import ROOT,verify

def identity(owner_uid,owner_gid,provider_uid,provider_gid):
 values=(owner_uid,owner_gid,provider_uid,provider_gid)
 if any(type(x) is not int or not 0<x<2**31 for x in values):raise ValueError('Explicit non-root numeric IDs required')
 if owner_uid==provider_uid or owner_gid==provider_gid:raise ValueError('Separate owner/provider users and groups required')

def build(owner_uid,owner_gid,provider_uid,provider_gid):
 identity(owner_uid,owner_gid,provider_uid,provider_gid);verify(ROOT)
 dirs={
 '/opt/yerbas-ai':(0o755,0,0),'/etc/yerbas-ai':(0o755,0,0),
 '/var/lib/yerbas-ai-broker':(0o700,0,0),'/var/lib/yerbas-ai-broker/records':(0o700,0,0),
 '/var/lib/yerbas-ai-provider':(0o755,0,0),'/var/lib/yerbas-ai-provider/requests':(0o750,0,provider_gid),
 '/var/lib/yerbas-ai-provider/jobs':(0o700,provider_uid,provider_gid),
 '/var/lib/yerbas-ai-provider/measured-jobs-v1':(0o700,provider_uid,provider_gid),
 '/run/yerbas-ai-provider':(0o750,0,owner_gid),
 '/var/lib/yerbas-training-experiment':(0o755,0,0)}
 config=dict(schema=1,owner_uid=owner_uid,socket_gid=owner_gid,submissions_enabled=False)
 socket='[Unit]\nDescription=Private Yerbas provider control socket\nAfter=systemd-tmpfiles-setup.service\n\n[Socket]\nListenStream=/run/yerbas-ai-provider/broker.sock\nFileDescriptorName=provider-broker\nSocketUser=root\nSocketGroup='+str(owner_gid)+'\nSocketMode=0660\nDirectoryMode=0750\nAccept=no\nRemoveOnStop=yes\nService=yerbas-provider-broker.service\n'
 files={}
 def add(path,content,mode=0o644):files[path]=dict(content=content,mode=mode,uid=0,gid=0,sha256=hashlib.sha256(content.encode()).hexdigest())
 for lock in ('continuous-worker.lock','gpu-probe.lock'):
  name='/var/lib/yerbas-training-experiment/'+lock;add(name,'',0o660);files[name]['gid']=provider_gid
 add('/etc/yerbas-ai/broker.json',json.dumps(config,sort_keys=True)+'\n',0o600)
 add('/etc/systemd/system/yerbas-provider-broker.socket',socket)
 add('/etc/tmpfiles.d/yerbas-provider-broker.conf','d /run/yerbas-ai-provider 0750 root '+str(owner_gid)+' -\n')
 return dict(schema=1,scope='disabled broker setup plan; incomplete provisioning',owner_uid=owner_uid,provider_uid=provider_uid,directories={p:dict(mode=m,uid=u,gid=g) for p,(m,u,g) in dirs.items()},files=files,submissions_enabled=False,activate_services=False,installable=False,missing=['root-controlled runtime provisioning','OS account identity verification','owner-agent integration','separate provider enrollment and acceptance'])

def check_empty_targets(plan,filesystem_root):
 """Check all setup targets first. Reject any occupied target, including directories.
 This deliberately supports fresh isolated layouts only; it never adopts state.
 """
 base=Path(filesystem_root)
 if base.is_symlink() or not base.is_dir():raise ValueError('Real filesystem root required')
 for name in (*plan['directories'],*plan['files']):
  relative=Path(name)
  if not relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe target')
  target=base.joinpath(*relative.parts[1:])
  if os.path.lexists(target):raise ValueError('Existing target preserved: '+name)
  for parent in target.parents:
   if parent==base:break
   if os.path.lexists(parent):
    info=parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode)&0o022:raise ValueError('Unsafe parent: '+str(parent))
 return dict(passed=True,mutations=False,installation_authorized=False)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('owner-uid','owner-gid','provider-uid','provider-gid'):p.add_argument('--'+name,type=int,required=True)
 a=p.parse_args();print(json.dumps(build(a.owner_uid,a.owner_gid,a.provider_uid,a.provider_gid),indent=2))
if __name__=='__main__':main()
