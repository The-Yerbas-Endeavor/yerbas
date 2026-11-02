"""Experimental training metadata validation. No execution, networking or accounting."""
import hashlib,json,os,re,stat
from pathlib import Path
HEX=re.compile(r'[0-9a-f]{64}\Z')
ID=re.compile(r'[a-z0-9][a-z0-9_-]{0,63}\Z')
MAX_CHECKPOINT_BYTES=64*1024*1024

def require(test,message):
    if not test:raise ValueError(message)

def fields(value,expected):
    require(type(value) is dict and set(value)==set(expected),'Unexpected fields')

def integer(value,low,high,label):
    require(type(value) is int and low<=value<=high,'Invalid '+label)

def digest(value):
    require(type(value) is str and HEX.fullmatch(value) is not None,'Invalid SHA256')

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def spec_hash(job):
    validate_job(job)
    return hashlib.sha256(canonical(job)).hexdigest()

def validate_job(job):
    fields(job,['schema','job_id','runner','dataset_sha256','initial_model_sha256',
                'training','limits','accounting'])
    require(type(job['schema']) is int and job['schema']==1,'Unsupported schema')
    require(type(job['job_id']) is str and ID.fullmatch(job['job_id']) is not None,'Invalid job ID')
    require(job['runner']=='tiny-mlp-v1','Runner is not approved')
    require(job['accounting']=='simulated','Only simulated accounting is supported')
    digest(job['dataset_sha256']);digest(job['initial_model_sha256'])
    t=job['training'];fields(t,['seed','batch_size','total_steps','checkpoint_every','optimizer','learning_rate'])
    integer(t['seed'],0,2**31-1,'seed');integer(t['batch_size'],1,256,'batch size')
    integer(t['total_steps'],1,10000,'steps');integer(t['checkpoint_every'],1,t['total_steps'],'checkpoint interval')
    require(t['optimizer']=='sgd_momentum_0.9','Optimizer is not approved')
    require(type(t['learning_rate']) in (int,float) and 0<t['learning_rate']<=1,'Invalid learning rate')
    l=job['limits'];fields(l,['wall_seconds','max_checkpoint_bytes'])
    integer(l['wall_seconds'],1,600,'wall limit')
    integer(l['max_checkpoint_bytes'],1,MAX_CHECKPOINT_BYTES,'checkpoint size limit')
    canonical(job)
    return job

def validate_checkpoint(manifest,job,*,expected_parent,previous_step):
    """Caller supplies accepted lineage from trusted coordinator state, not provider metadata."""
    validate_job(job)
    fields(manifest,['schema','job_id','job_spec_sha256','step','parent_sha256','artifact'])
    require(type(manifest['schema']) is int and manifest['schema']==1,'Unsupported schema')
    require(manifest['job_id']==job['job_id'],'Checkpoint belongs to another job')
    require(manifest['job_spec_sha256']==spec_hash(job),'Training specification changed')
    integer(previous_step,0,job['training']['total_steps'],'previous step')
    if previous_step==0:require(expected_parent==job['initial_model_sha256'],'Invalid initial lineage')
    else:digest(expected_parent)
    require(manifest['parent_sha256']==expected_parent,'Checkpoint lineage mismatch')
    integer(manifest['step'],previous_step+1,job['training']['total_steps'],'checkpoint progress')
    require(manifest['step']==job['training']['total_steps'] or
            manifest['step']%job['training']['checkpoint_every']==0,'Unexpected checkpoint boundary')
    a=manifest['artifact'];fields(a,['filename','bytes','sha256','format'])
    require(a['filename']=='checkpoint.json','Only the fixed checkpoint filename is allowed')
    require(a['format']=='yerbas-tiny-mlp-json-v1','Unsupported checkpoint format')
    integer(a['bytes'],1,job['limits']['max_checkpoint_bytes'],'artifact size');digest(a['sha256'])
    return manifest

def verify_artifact(directory,manifest,job,*,expected_parent,previous_step):
    """Verify a sealed artifact in a trusted private directory; does not deserialize it.

    The coordinator must own the immutable directory before this call. Hash validity
    does not prove useful computation, accuracy, safety of a training runner, or payment.
    """
    validate_checkpoint(manifest,job,expected_parent=expected_parent,previous_step=previous_step)
    a=manifest['artifact'];path=Path(directory)/a['filename']
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode),'Checkpoint is not a regular file')
        require(info.st_size==a['bytes'],'Checkpoint size mismatch')
        h=hashlib.sha256();remaining=a['bytes']
        while remaining:
            chunk=stream.read(min(1024*1024,remaining))
            require(bool(chunk),'Truncated checkpoint');h.update(chunk);remaining-=len(chunk)
        require(not stream.read(1),'Checkpoint grew during verification')
        require(h.hexdigest()==a['sha256'],'Checkpoint checksum mismatch')
    return {'verified':True,'job_id':job['job_id'],'step':manifest['step'],'sha256':a['sha256']}
