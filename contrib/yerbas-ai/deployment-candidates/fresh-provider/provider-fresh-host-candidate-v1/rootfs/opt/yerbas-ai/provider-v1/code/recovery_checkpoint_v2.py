"""Version 2: recovery saves preserve scheduled validation and patience state.

No automatic migration from version 1: its off-schedule evaluations cannot be
removed without reconstructing model history. Existing version-1 files stay intact.
"""
import copy
import hashlib
import json
from pathlib import Path
from sustained_training import encoded,validate as validate_model,atomic_json
from validation_policy import initial,observe,validate as validate_policy

MAX_BYTES=32*1024*1024
INTERVAL=1000


def validate_bundle(bundle):
    if type(bundle) is not dict or set(bundle)!={'schema','latest','best','selection','target_step'}:
        raise ValueError('Invalid v2 bundle fields; version-1 migration is not automatic')
    if type(bundle['schema']) is not int or bundle['schema']!=2:raise ValueError('Version 2 required')
    target=bundle['target_step']
    if type(target) is not int or not 1<=target<=10000:raise ValueError('Invalid target step')
    latest=validate_model(bundle['latest']);policy=validate_policy(bundle['selection'])
    step=latest['step']
    if step>target or policy['last_step']>step:raise ValueError('Invalid recovery/validation ordering')
    scheduled=step//INTERVAL*INTERVAL
    if step==target:scheduled=target
    if policy['last_step']!=scheduled:raise ValueError('Missing or off-schedule validation')
    expected=scheduled//INTERVAL+int(scheduled==target and target%INTERVAL!=0)
    if policy['evaluations']!=expected:raise ValueError('Wrong scheduled evaluation count')
    if policy['evaluations']==0:
        if bundle['best'] is not None:raise ValueError('Unevaluated model cannot be selected best')
    else:
        best=validate_model(bundle['best'])
        if best['step']!=policy['best_step']:raise ValueError('Best checkpoint disagrees with policy')
        if best['step']%INTERVAL!=0 and best['step']!=target:raise ValueError('Off-schedule best model')
    if policy['stopped'] and step!=policy['last_step']:raise ValueError('Training continued after validation stop')
    return bundle


def record(previous,model,target_step,validation_loss=None):
    validate_model(model);step=model['step']
    if previous is not None:
        validate_bundle(previous)
        if previous['target_step']!=target_step:raise ValueError('Target cannot change on restart')
        prior_step=previous['latest']['step']
        if step==prior_step:
            if encoded(model)!=encoded(previous['latest']):raise ValueError('Conflicting model at same step')
            return copy.deepcopy(previous)
        if step<prior_step or previous['selection']['stopped']:raise ValueError('Cannot rewind or resume stopped training')
    policy=initial() if previous is None else previous['selection']
    best=None if previous is None else previous['best']
    scheduled=step%INTERVAL==0 or step==target_step
    if scheduled:
        if validation_loss is None:raise ValueError('Scheduled validation loss required')
        policy,improved=observe(policy,step,validation_loss)
        if improved:best=model
    elif validation_loss is not None:
        raise ValueError('Recovery save must not evaluate validation loss')
    return validate_bundle({'schema':2,'target_step':target_step,'latest':copy.deepcopy(model),
                            'best':copy.deepcopy(best),'selection':copy.deepcopy(policy)})


def save(path,bundle):
    validate_bundle(bundle)
    raw={'bundle':bundle,'sha256':hashlib.sha256(encoded(bundle)).hexdigest()}
    if len(encoded(raw))>MAX_BYTES:raise ValueError('Checkpoint too large')
    atomic_json(Path(path),raw)


def load(path):
    with Path(path).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Checkpoint too large')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate checkpoint key')
            result[key]=value
        return result
    envelope=json.loads(raw,object_pairs_hook=unique)
    if type(envelope) is not dict or set(envelope)!={'bundle','sha256'}:raise ValueError('Invalid envelope')
    if hashlib.sha256(encoded(envelope['bundle'])).hexdigest()!=envelope['sha256']:raise ValueError('Checksum mismatch')
    return validate_bundle(envelope['bundle'])
