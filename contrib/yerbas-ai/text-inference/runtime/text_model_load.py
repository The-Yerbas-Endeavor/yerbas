"""Read the fixed JSON model for offline use; no coordinator dependencies."""
import hashlib,json
from pathlib import Path
from text_neural import MAX_CHECKPOINT,validate_checkpoint

def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON field')
        result[key]=value
    return result

def load(directory):
    directory=Path(directory)
    with (directory/'model.json').open('rb') as f:metadata=f.read(65537)
    if len(metadata)>65536:raise ValueError('Model metadata exceeds bound')
    meta=json.loads(metadata,object_pairs_hook=unique)
    if meta.get('kind')!='yerbas-text-model' or meta.get('schema')!=1:raise ValueError('Unsupported model bundle')
    with (directory/'checkpoint.json').open('rb') as f:raw=f.read(MAX_CHECKPOINT+1)
    if len(raw)>MAX_CHECKPOINT or hashlib.sha256(raw).hexdigest()!=meta['checkpoint_sha256']:raise ValueError('Model file hash mismatch')
    c=validate_checkpoint(json.loads(raw,object_pairs_hook=unique),meta['identity'])
    if c['step']!=6000 or meta['step']!=6000:raise ValueError('Incomplete model')
    return meta,c
