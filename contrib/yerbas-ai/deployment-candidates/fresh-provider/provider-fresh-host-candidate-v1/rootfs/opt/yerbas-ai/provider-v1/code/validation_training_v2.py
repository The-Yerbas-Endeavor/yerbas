"""Version-2 synthetic trainer: checkpoint persistence does not consume patience."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import signal
import time
import recovery_checkpoint_v2 as selected
from sustained_training import CONFIG, encoded, atomic_json


def record_checkpoint(path,previous,model,target_step,validation_loss=None):
    updated=selected.record(previous,model,target_step,validation_loss)
    selected.save(path,updated)
    return updated


def run(state,target_step,segment_steps=None):
    if type(target_step) is not int or not 1<=target_step<=10000:raise ValueError("Invalid target")
    if segment_steps is not None and (type(segment_steps) is not int or not 1<=segment_steps<=10000):raise ValueError("Invalid segment bound")
    path=state/'recovery-v2.json'
    if (state/'selection.json').exists():raise ValueError('Legacy selection exists; use a fresh v2 state directory')
    bundle=selected.load(path) if path.exists() else None
    if bundle is not None and bundle['target_step']!=target_step:raise ValueError('Target cannot change on restart')
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
    step=0
    if bundle is not None:
        checkpoint=bundle['latest'];step=checkpoint['step']
        with torch.no_grad():
            for p,values,momentum in zip(model.parameters(),checkpoint['parameters'],checkpoint['momentum'],strict=True):
                p.copy_(torch.tensor(values,dtype=torch.float32,device='cuda:0'))
                opt.state[p]['momentum_buffer']=torch.tensor(momentum,dtype=torch.float32,device='cuda:0')
    initial_step=step;last_status=0
    def save(status):
        nonlocal bundle
        # A restart/finally at the same step must not consume patience again.
        if bundle is None or step != bundle['latest']['step']:
            body={'schema':1,'config':CONFIG,'torch':torch.__version__,'step':step,
                  'parameters':[p.detach().cpu().tolist() for p in model.parameters()],
                  'momentum':[opt.state[p]['momentum_buffer'].cpu().tolist() for p in model.parameters()]}
            loss=None
            if step%selected.INTERVAL==0 or step==target_step:
                with torch.no_grad():
                    loss=torch.nn.functional.binary_cross_entropy_with_logits(model(x[8192:]),y[8192:]).item()
            bundle=record_checkpoint(path,bundle,body,target_step,loss)
        selection=bundle['selection']
        report={'state':'validation_stopped' if selection['stopped'] else status,
                'step':step,'resumed_from_step':initial_step,'selection':selection,
                'best_checkpoint_step':bundle['selection']['best_step'],
                'latest_sha256':hashlib.sha256(encoded(bundle['latest'])).hexdigest(),
                'best_sha256':hashlib.sha256(encoded(bundle['best'])).hexdigest() if bundle['best'] is not None else None,
                'updated_at':time.time(),'gpu':torch.cuda.get_device_name(),
                'workload':'validation-v2 synthetic model; scheduled validation independent of recovery saves',
                'torch':torch.__version__}
        atomic_json(state/'report.json',report)
        print(json.dumps(report),flush=True)
    if bundle and (bundle['selection']['stopped'] or step==target_step):
        save('validation_stopped' if bundle['selection']['stopped'] else 'segment_complete')
        return step
    try:
        while not stopping and step<target_step and (segment_steps is None or step-initial_step<segment_steps) and not (bundle and bundle['selection']['stopped']):
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
    p.add_argument('--target-step',type=int,required=True)
    p.add_argument('--segment-steps',type=int,help='Bound this invocation without changing the global validation target')
    a=p.parse_args()
    if not 1<=a.target_step<=10000:p.error('target-step must be between 1 and 10000')
    a.state.mkdir(mode=0o700,parents=True,exist_ok=True)
    run(a.state,a.target_step,a.segment_steps)
