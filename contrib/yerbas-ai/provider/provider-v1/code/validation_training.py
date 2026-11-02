"""Versioned validation-aware synthetic trainer; preserves best and latest states."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import signal
import time
import selected_checkpoint as selected
from sustained_training import CONFIG, encoded, atomic_json


def record_evaluation(path, previous, model, loss):
    if previous is not None and model['step']==previous['latest']['step']:
        if encoded(model)!=encoded(previous['latest']):
            raise ValueError('Model changed without advancing step')
        return previous
    updated=selected.advance(previous,model,loss)
    selected.save(path,updated)
    return updated


def run(state,max_steps):
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
    path=state/'selection.json';step=0;bundle=None
    if path.exists():
        bundle=selected.load(path);checkpoint=bundle['latest'];step=checkpoint['step']
        with torch.no_grad():
            for p,values,momentum in zip(model.parameters(),checkpoint['parameters'],checkpoint['momentum'],strict=True):
                p.copy_(torch.tensor(values,dtype=torch.float32,device='cuda:0'))
                opt.state[p]['momentum_buffer']=torch.tensor(momentum,dtype=torch.float32,device='cuda:0')
    initial_step=step;last_status=0
    def save(status):
        nonlocal bundle
        # A restart/finally at the same step must not consume patience again.
        if bundle is None or step != bundle['selection']['last_step']:
            body={'schema':1,'config':CONFIG,'torch':torch.__version__,'step':step,
                  'parameters':[p.detach().cpu().tolist() for p in model.parameters()],
                  'momentum':[opt.state[p]['momentum_buffer'].cpu().tolist() for p in model.parameters()]}
            with torch.no_grad():
                loss=torch.nn.functional.binary_cross_entropy_with_logits(model(x[8192:]),y[8192:]).item()
            bundle=record_evaluation(path,bundle,body,loss)
        selection=bundle['selection']
        report={'state':'validation_stopped' if selection['stopped'] else status,
                'step':step,'resumed_from_step':initial_step,'selection':selection,
                'best_checkpoint_step':bundle['best']['step'],
                'latest_sha256':hashlib.sha256(encoded(bundle['latest'])).hexdigest(),
                'best_sha256':hashlib.sha256(encoded(bundle['best'])).hexdigest(),
                'updated_at':time.time(),'gpu':torch.cuda.get_device_name(),
                'workload':'validation-selected synthetic model, no network jobs',
                'torch':torch.__version__}
        atomic_json(state/'report.json',report)
        print(json.dumps(report),flush=True)
    if bundle and bundle['selection']['stopped']:
        save('validation_stopped')
        return step
    try:
        while not stopping and (not max_steps or step-initial_step<max_steps) and not (bundle and bundle['selection']['stopped']):
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
            if step%1000==0:
                save('checkpointed')
    finally:
        if step>initial_step:save('owner_stopped' if stopping else 'segment_complete')
    return step


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state',type=Path,required=True)
    p.add_argument('--max-steps',type=int,default=0)
    a=p.parse_args()
    if a.max_steps<0:p.error('max-steps must be nonnegative')
    run(a.state,a.max_steps)
