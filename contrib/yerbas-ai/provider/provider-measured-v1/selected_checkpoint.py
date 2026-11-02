"""Atomic latest/best checkpoint selection for the sustained synthetic recipe.

An experimental storage component, not yet connected to the live GPU worker.
The state directory must be private and writer access externally serialized.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
from sustained_training import encoded, validate as validate_model
from validation_policy import initial, observe, validate as validate_policy

MAX_BYTES=64*1024*1024


def validate_bundle(bundle):
    if type(bundle) is not dict or set(bundle)!={'schema','latest','best','selection'}:
        raise ValueError('Wrong bundle fields')
    if type(bundle['schema']) is not int or bundle['schema']!=1:raise ValueError('Wrong bundle schema')
    latest=validate_model(bundle['latest']);best=validate_model(bundle['best'])
    policy=validate_policy(bundle['selection'])
    if latest['step']!=policy['last_step'] or best['step']!=policy['best_step']:
        raise ValueError('Checkpoint and selection steps disagree')
    return bundle


def advance(previous, model, validation_loss):
    validate_model(model)
    if previous is not None:validate_bundle(previous)
    policy,improved=observe(initial() if previous is None else previous['selection'],
                            model['step'],validation_loss)
    return validate_bundle({'schema':1,'latest':copy.deepcopy(model),
                            'best':copy.deepcopy(model if improved else previous['best']),
                            'selection':policy})


def save(path,bundle):
    validate_bundle(bundle)
    body=encoded(bundle)
    raw=encoded({'sha256':hashlib.sha256(body).hexdigest(),'bundle':bundle})
    if len(raw)>MAX_BYTES:raise ValueError('Bundle too large')
    path=Path(path);temporary=path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def load(path):
    with Path(path).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Bundle too large')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate key')
            result[key]=value
        return result
    wrapper=json.loads(raw,object_pairs_hook=unique)
    if type(wrapper) is not dict or set(wrapper)!={'sha256','bundle'}:raise ValueError('Invalid envelope')
    bundle=wrapper['bundle']
    if hashlib.sha256(encoded(bundle)).hexdigest()!=wrapper['sha256']:raise ValueError('Bundle checksum mismatch')
    return validate_bundle(bundle)
