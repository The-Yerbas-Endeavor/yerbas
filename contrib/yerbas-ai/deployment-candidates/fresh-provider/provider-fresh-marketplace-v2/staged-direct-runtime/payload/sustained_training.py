"""Persistent synthetic GPU training, deliberately separate from the pilot ledger."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

CONFIG = {'recipe':'sustained-mlp-v1','widths':[256,512,256,1], 'batch':1024,
          'train_rows':8192,'heldout_rows':1024,'seed':731,'lr':0.01,'momentum':0.9,
          'rng_policy':'fixed-generated-data-no-stochastic-training'}
SHAPES=((512,256),(512,),(256,512),(256,),(1,256),(1,))
MAX_BYTES=32*1024*1024


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def atomic_json(path, value):
    raw=encoded(value)
    if len(raw)>MAX_BYTES:raise ValueError('Artifact too large')
    temporary=path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def shape(value,dimensions):
    if dimensions:
        if type(value) is not list or len(value)!=dimensions[0]:raise ValueError('Wrong tensor shape')
        for item in value:shape(item,dimensions[1:])
    elif type(value) not in (float,int) or not math.isfinite(value) or abs(value)>1e6:
        raise ValueError('Invalid tensor value')


def validate(body):
    if type(body) is not dict or set(body)!={'schema','config','torch','step','parameters','momentum'}:
        raise ValueError('Wrong checkpoint fields')
    if type(body['schema']) is not int or body['schema']!=1:raise ValueError('Wrong schema')
    if encoded(body['config'])!=encoded(CONFIG) or body['torch']!='2.14.1+cu126':
        raise ValueError('Recipe/runtime changed')
    if type(body['step']) is not int or not 1<=body['step']<2**53:raise ValueError('Invalid step')
    for key in ('parameters','momentum'):
        if type(body[key]) is not list or len(body[key])!=len(SHAPES):raise ValueError('Wrong tensor count')
        for data,dims in zip(body[key],SHAPES,strict=True):shape(data,dims)
    return body


def load(path):
    with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Checkpoint too large')
    def unique(pairs):
        value={}
        for key,item in pairs:
            if key in value:raise ValueError('Duplicate JSON key')
            value[key]=item
        return value
    wrapper=json.loads(raw,object_pairs_hook=unique)
    if type(wrapper) is not dict or set(wrapper)!={'sha256','checkpoint'}:raise ValueError('Invalid envelope')
    body=wrapper['checkpoint']
    if hashlib.sha256(encoded(body)).hexdigest()!=wrapper['sha256']:raise ValueError('Checkpoint hash mismatch')
    return validate(body)


def run(state,max_seconds):
    import torch
    if torch.__version__!='2.14.1+cu126' or not torch.cuda.is_available():raise RuntimeError('Reviewed CUDA runtime required')
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32=False
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    for sig in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):signal.signal(sig,stop)
    # Fresh deterministic generation is identical on restore; no randomness in steps.
    generator=torch.Generator().manual_seed(CONFIG['seed'])
    x=torch.randn(9216,256,generator=generator).to('cuda:0')
    y=(x[:,:16].sum(dim=1,keepdim=True)>0).float()
    torch.manual_seed(CONFIG['seed'])
    model=torch.nn.Sequential(torch.nn.Linear(256,512),torch.nn.Tanh(),
                              torch.nn.Linear(512,256),torch.nn.Tanh(),torch.nn.Linear(256,1)).to('cuda:0')
    opt=torch.optim.SGD(model.parameters(),lr=CONFIG['lr'],momentum=CONFIG['momentum'])
    path=state/'checkpoint.json';step=0
    if path.exists():
        checkpoint=load(path);step=checkpoint['step']
        with torch.no_grad():
            for p,values,momentum in zip(model.parameters(),checkpoint['parameters'],checkpoint['momentum'],strict=True):
                p.copy_(torch.tensor(values,dtype=torch.float32,device='cuda:0'))
                opt.state[p]['momentum_buffer']=torch.tensor(momentum,dtype=torch.float32,device='cuda:0')
    initial_step=step;started=time.monotonic();last_saved=started;last_status=0
    def save(status):
        body={'schema':1,'config':CONFIG,'torch':torch.__version__,'step':step,
              'parameters':[p.detach().cpu().tolist() for p in model.parameters()],
              'momentum':[opt.state[p]['momentum_buffer'].cpu().tolist() for p in model.parameters()]}
        validate(body)
        digest=hashlib.sha256(encoded(body)).hexdigest()
        atomic_json(path,{'sha256':digest,'checkpoint':body})
        with torch.no_grad():
            loss=torch.nn.functional.binary_cross_entropy_with_logits(model(x[8192:]),y[8192:]).item()
        report={'state':status,'step':step,'resumed_from_step':initial_step,'heldout_loss':loss,
                'checkpoint_sha256':digest,'updated_at':time.time(),'gpu':torch.cuda.get_device_name(),
                'workload':'persistent synthetic model, no network jobs','torch':torch.__version__}
        atomic_json(state/'report.json',report)
        print(json.dumps(report),flush=True)
    try:
        while not stopping and (not max_seconds or time.monotonic()-started<max_seconds):
            offset=step*CONFIG['batch']%CONFIG['train_rows']
            opt.zero_grad(set_to_none=True)
            loss=torch.nn.functional.binary_cross_entropy_with_logits(model(x[offset:offset+1024]),y[offset:offset+1024])
            if not math.isfinite(loss.item()):raise RuntimeError('Non-finite loss')
            loss.backward();opt.step();step+=1
            now=time.monotonic()
            if now-last_status>=5:
                atomic_json(state/'progress.json',{'step':step,'resumed_from_step':initial_step,
                            'training_loss':loss.item(),'updated_at':time.time(),'state':'training'})
                last_status=now
            if now-last_saved>=60:
                save('checkpointed');last_saved=time.monotonic()
                # A short, interruptible cooldown after saving, not between steps.
                end=time.monotonic()+5
                while not stopping and time.monotonic()<end:time.sleep(.1)
    finally:
        if step>initial_step:save('stopped')
    return step


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',type=Path,required=True)
    p.add_argument('--max-seconds',type=int,default=0)
    a=p.parse_args()
    if a.max_seconds<0:p.error('max-seconds must be nonnegative')
    run(a.state,a.max_seconds)
