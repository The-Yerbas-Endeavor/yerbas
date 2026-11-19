"""Narrow system-service adapter; not installed or exposed as a privileged API.

Only the broker dispatcher may call it, under its exclusive dispatcher lock.
No arbitrary unit, path, command or environment comes from a client request.
"""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from provider_broker import identifier,CONTRIBUTION

PROPERTIES=('LoadState','ActiveState','SubState','Result','ExecMainCode','ExecMainStatus','ExecMainStartTimestampMonotonic','InvocationID','MainPID','FragmentPath')


def unit_name(run,mode):
    identifier(run)
    if mode not in ('train','replay'):raise ValueError('Unsupported service mode')
    return ('yerbas-text-provider@' if mode=='train' else 'yerbas-text-replay@')+run+'.service'


def parse_properties(raw):
    result={}
    if not isinstance(raw,str) or len(raw)>8192:raise ValueError('Invalid service response')
    for line in raw.splitlines():
        key,separator,value=line.partition('=')
        if not separator or key not in PROPERTIES or key in result:raise ValueError('Unexpected service property')
        result[key]=value
    if set(result)!=set(PROPERTIES):raise ValueError('Incomplete service response')
    for key in ('ExecMainCode','ExecMainStatus','ExecMainStartTimestampMonotonic','MainPID'):
        if not re.fullmatch('[0-9]{1,20}',result[key]):raise ValueError('Invalid service counter')
        result[key]=int(result[key])
    return result


def systemctl(arguments):
    # This function is not a request endpoint. Only fixed call sites below supply arguments.
    result=subprocess.run(['/usr/bin/systemctl','--no-pager']+arguments,
        stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,timeout=8,env={'PATH':'/usr/bin:/bin','LC_ALL':'C','SYSTEMD_COLORS':'0'})
    if result.returncode:raise RuntimeError('Service manager rejected operation')
    if len(result.stdout)>8192:raise ValueError('Oversized service response')
    return result.stdout


class ServiceAdapter:
    def __init__(self,spool,records,control=systemctl):
        self.spool=spool;self.records=records;self.control=control
    def query(self,run,mode):
        name=unit_name(run,mode)
        value=parse_properties(self.control(['show',name,'--property='+','.join(PROPERTIES)]))
        if value['LoadState']=='not-found':return value
        expected='/etc/systemd/system/'+('yerbas-text-provider@.service' if mode=='train' else 'yerbas-text-replay@.service')
        if value['FragmentPath']!=expected or value['LoadState']!='loaded':raise ValueError('Unexpected executor unit definition')
        return value
    def start(self,run,mode,contribution):
        name=unit_name(run,mode)
        if not isinstance(contribution,str) or not CONTRIBUTION.fullmatch(contribution):raise ValueError('Invalid contribution')
        previous=self.query(run,mode)
        if previous['ActiveState']=='active' and previous['SubState']=='exited' and previous['MainPID']==0:
            # Retained completed units must be ours before retiring them for a
            # new receipt-only attempt. Never stop an unrelated active unit.
            record=self.records.load(run,mode)
            if previous['ExecMainStartTimestampMonotonic']<=record['baseline_start'] or not previous['InvocationID'] or previous['InvocationID']==record['baseline_invocation']:
                raise ValueError('Retained unit is not a fresh owned invocation')
            self.control(['stop',name])
            previous=self.query(run,mode)
        if previous['LoadState']!='loaded' or previous['ActiveState'] not in ('inactive','failed') or previous['MainPID']!=0:
            raise ValueError('Executor is not provisioned or is already active')
        self.spool.publish(run,contribution)
        # Write before the irreversible external side effect. A lost response must
        # be inspected, never retried by blindly invoking start again.
        self.records.save(run,mode,{'baseline_start':previous['ExecMainStartTimestampMonotonic'],'baseline_invocation':previous['InvocationID'],'stop_confirmed':False})
        self.control(['start','--no-block',name])
    def stop(self,run,mode):
        name=unit_name(run,mode)
        self.query(run,mode)  # Verify the fixed template before any mutation.
        record=self.records.load(run,mode)  # No ownership intent: do not stop an existing unit.
        self.control(['stop',name])
        value=self.query(run,mode)
        if value['ActiveState'] in ('inactive','failed') and value['MainPID']==0:
            record['stop_confirmed']=True;self.records.save(run,mode,record)
    def inspect(self,run,mode):
        value=self.query(run,mode);record=self.records.load(run,mode)
        if value['LoadState']=='not-found':return 'absent'
        # A stop must complete, not merely be queued by systemctl.
        if record.get('stop_confirmed') and value['ActiveState'] in ('inactive','failed') and value['MainPID']==0:return 'cancelled'
        fresh=value['ExecMainStartTimestampMonotonic']>record['baseline_start']
        if not fresh:return 'unknown'
        if value['ActiveState']=='active' and value['SubState']=='exited' and value['MainPID']==0:
            if value['ExecMainCode']!=1:return 'unknown'
            return 'completed' if value['ExecMainStatus']==0 and value['Result']=='success' else 'failed'
        if value['ActiveState'] in ('active','activating','reloading','deactivating'):return 'running'
        if value['MainPID']!=0:return 'unknown'
        if value['ActiveState']=='failed':return 'failed'
        if value['ActiveState']=='inactive' and value['ExecMainCode']==1:
            return 'completed' if value['ExecMainStatus']==0 and value['Result']=='success' else 'failed'
        return 'unknown'


class PrivateRecords:
    """Root-owned adapter records in a preprovisioned directory. No database reuse."""
    def __init__(self,directory):
        from provider_executor import require_root_ancestry
        self.directory=Path(directory)
        require_root_ancestry(self.directory/'record.json')
        info=self.directory.lstat()
        if os.geteuid()!=0 or not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('Root-private record directory required')
    def path(self,run,mode):return self.directory/(unit_name(run,mode)+'.json')
    def load(self,run,mode):
        from provider_executor import read_json
        return read_json(self.path(run,mode),owner=0)
    def save(self,run,mode,value):
        from provider_executor import atomic
        atomic(self.path(run,mode),value)


class RequestSpool:
    """Publish once into a preprovisioned root-controlled spool; preserve matches."""
    def __init__(self,directory,provider_uid,provider_gid):
        from provider_executor import require_root_ancestry
        self.directory=Path(directory);self.uid=provider_uid;self.gid=provider_gid
        require_root_ancestry(self.directory/'request.json')
        info=self.directory.lstat()
        if os.geteuid()!=0 or not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('Root-controlled request spool required')
        if type(provider_uid) is not int or provider_uid<=0 or type(provider_gid) is not int or provider_gid<=0:raise ValueError('Dedicated provider identity required')
    def publish(self,run,contribution):
        from provider_executor import read_json
        identifier(run)
        if not isinstance(contribution,str) or not CONTRIBUTION.fullmatch(contribution):raise ValueError('Invalid contribution')
        path=self.directory/(run+'.json');value={'run_id':run,'contribution':contribution}
        if os.path.lexists(path):
            if read_json(path,owner=self.uid)!=value:raise ValueError('Retained request differs')
            return
        # An exclusive temporary file plus hard-link publication cannot replace
        # an existing request, even if another publisher races this one.
        import uuid
        temporary=self.directory/('.request-'+uuid.uuid4().hex)
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            with os.fdopen(fd,'w') as stream:
                json.dump(value,stream);stream.flush();os.fchown(stream.fileno(),self.uid,self.gid);os.fsync(stream.fileno())
            os.link(temporary,path,follow_symlinks=False)
            directory=os.open(self.directory,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:temporary.unlink(missing_ok=True)
