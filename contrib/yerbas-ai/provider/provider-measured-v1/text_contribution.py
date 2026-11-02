"""Schema-4 fixed neural-text contract; structurally verified, not proof of computation."""
import hashlib,json
from text_neural import CONFIG,MAX_CHECKPOINT,canonical,digest as value_digest,validate_checkpoint
from training_contract import fields,integer,digest,require
from checkpoint_receipts import identifier

def initial_parent(identity):return value_digest({'initialization':'seeded-byte-context-mlp-v1','identity':identity})

def validate_manifest(m):
    fields(m,('schema','recipe','chain','contribution','provider','identity','parent_sha256','start_step','end_step','target_step','max_runtime_seconds','max_artifact_bytes'))
    require(type(m['schema']) is int and m['schema']==4,'Text schema 4 required')
    require(m['recipe']==CONFIG['recipe'],'Unapproved text recipe')
    for key in ('chain','contribution','provider'):identifier(m[key])
    fields(m['identity'],('runner','dataset','config'))
    for value in m['identity'].values():digest(value)
    require(m['identity']['config']==value_digest(CONFIG),'Text configuration changed')
    digest(m['parent_sha256']);integer(m['target_step'],6000,6000,'fixed text target')
    integer(m['start_step'],0,5999,'start');integer(m['end_step'],m['start_step']+1,6000,'end')
    integer(m['max_runtime_seconds'],1,120,'runtime');integer(m['max_artifact_bytes'],1,MAX_CHECKPOINT,'artifact size')
    if m['start_step']==0:require(m['parent_sha256']==initial_parent(m['identity']),'Wrong seeded initial parent')
    return m

def manifest_digest(m):return hashlib.sha256(canonical(validate_manifest(m))).hexdigest()

def checkpoint(raw,identity):
    require(type(raw) is bytes and 0<len(raw)<=MAX_CHECKPOINT,'Invalid checkpoint size')
    def unique(pairs):
        result={}
        for k,v in pairs:
            if k in result:raise ValueError('Duplicate checkpoint field')
            result[k]=v
        return result
    return validate_checkpoint(json.loads(raw,object_pairs_hook=unique),identity)

def decode(raw,identity):
    c=checkpoint(raw,identity)
    return {'latest':{'step':c['step']},'target_step':CONFIG['target_steps'],'selection':{'stopped':False}}

def verify_result(m,raw,parent_raw=None):
    validate_manifest(m);require(type(raw) is bytes and 0<len(raw)<=m['max_artifact_bytes'],'Invalid contribution size')
    c=checkpoint(raw,m['identity']);require(c['step']==m['end_step'],'Incomplete or out-of-range text contribution')
    if m['start_step']==0:require(parent_raw is None,'Unexpected parent')
    else:
        require(type(parent_raw) is bytes and hashlib.sha256(parent_raw).hexdigest()==m['parent_sha256'],'Parent checksum changed')
        parent=checkpoint(parent_raw,m['identity']);require(parent['step']==m['start_step'],'Parent step changed')
    return {'sha256':hashlib.sha256(raw).hexdigest(),'step':c['step'],'stopped':c['step']==6000}
