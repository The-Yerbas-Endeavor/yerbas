"""Fixed byte-context neural recipe. Local execution only; no pickle or downloads."""
import argparse,hashlib,json,math,signal,threading,time
from pathlib import Path
from text_baseline import load_dataset
CONFIG={'recipe':'byte-context-mlp-v1','seed':731,'context':8,'embedding':16,'hidden':128,'batch':256,'lr':.1,'momentum':.9,'target_steps':6000}
SHAPES={'embedding.weight':[256,16],'hidden.weight':[128,128],'hidden.bias':[128],'output.weight':[256,128],'output.bias':[256]}
MAX_CHECKPOINT=16*1024*1024

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def identity(dataset):
    manifest,_=load_dataset(dataset)
    return {'dataset':digest(manifest),'config':digest(CONFIG),'runner':hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('text_baseline.py').read_bytes()).hexdigest()}

def examples(documents):
    contexts=[];targets=[]
    for doc in documents:
        raw=doc['text'].encode('utf-8')
        for i in range(1,len(raw)):
            prefix=list(raw[max(0,i-CONFIG['context']):i]);contexts.append([0]*(CONFIG['context']-len(prefix))+prefix);targets.append(raw[i])
    if not targets:raise ValueError('No byte transitions in split')
    return contexts,targets

def validate_checkpoint(c,expected):
    if type(c) is not dict or set(c)!={'schema','identity','config','step','torch','parameters','momentum'}:raise ValueError('Invalid checkpoint fields')
    if c['schema']!=1 or c['identity']!=expected or c['config']!=CONFIG:raise ValueError('Checkpoint recipe/data changed')
    if type(c['step']) is not int or not 0<=c['step']<=CONFIG['target_steps']:raise ValueError('Invalid checkpoint step')
    if c['torch']!='2.14.1+cu126':raise ValueError('Unapproved Torch runtime')
    for group in ('parameters','momentum'):
        if type(c[group]) is not dict or set(c[group])!=set(SHAPES):raise ValueError('Invalid tensor names')
        for name,shape in SHAPES.items():
            v=c[group][name]
            if type(v) is not list or len(v)!=math.prod(shape) or any(type(x) not in (int,float) or not math.isfinite(x) for x in v):raise ValueError('Invalid tensor values/shape')
    return c

def save(path,c):
    raw=canonical(c)
    if len(raw)>MAX_CHECKPOINT:raise ValueError('Checkpoint too large')
    tmp=path.with_suffix('.tmp')
    import os
    with tmp.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    tmp.replace(path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)

def read_checkpoint(path,expected):
    with path.open('rb') as f:raw=f.read(MAX_CHECKPOINT+1)
    if len(raw)>MAX_CHECKPOINT:raise ValueError('Checkpoint too large')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('Duplicate checkpoint key')
            d[k]=v
        return d
    return validate_checkpoint(json.loads(raw,object_pairs_hook=unique),expected)

def run(dataset,state,device,steps,max_seconds,stop=None):
    if device not in ('cpu','cuda') or not 1<=steps<=6000 or not 1<=max_seconds<=120:raise ValueError('Invalid bounded run')
    expected=identity(dataset);_,splits=load_dataset(dataset);state=Path(state);state.mkdir(mode=0o700,parents=True,exist_ok=True)
    import fcntl
    lock=(state/'worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    try:return _train(dataset,state,device,steps,max_seconds,stop or threading.Event(),expected,splits)
    finally:lock.close()

def _train(dataset,state,device,steps,max_seconds,stop,expected,splits):
    import torch
    if torch.__version__!='2.14.1+cu126':raise ValueError('Requires approved installed Torch 2.14.1+cu126')
    torch.set_num_threads(2);torch.use_deterministic_algorithms(True);torch.manual_seed(CONFIG['seed'])
    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__();self.embedding=torch.nn.Embedding(256,16);self.hidden=torch.nn.Linear(128,128);self.output=torch.nn.Linear(128,256)
        def forward(self,x):return self.output(torch.tanh(self.hidden(self.embedding(x).flatten(1))))
    model=Model().to(device);optimizer=torch.optim.SGD(model.parameters(),lr=CONFIG['lr'],momentum=CONFIG['momentum'])
    checkpoint=state/'checkpoint.json';step=0
    if checkpoint.exists():
        c=read_checkpoint(checkpoint,expected);step=c['step']
        with torch.no_grad():
            for name,p in model.named_parameters():
                p.copy_(torch.tensor(c['parameters'][name],dtype=torch.float32,device=device).reshape(SHAPES[name]))
                optimizer.state[p]['momentum_buffer']=torch.tensor(c['momentum'][name],dtype=torch.float32,device=device).reshape(SHAPES[name])
    resumed=step;end=min(CONFIG['target_steps'],step+steps)
    tx,ty=examples(splits['train']);vx,vy=examples(splits['validation'])
    tx=torch.tensor(tx,dtype=torch.long,device=device);ty=torch.tensor(ty,dtype=torch.long,device=device)
    vx=torch.tensor(vx,dtype=torch.long,device=device);vy=torch.tensor(vy,dtype=torch.long,device=device)
    def evaluate():
        with torch.no_grad():
            total=sum(torch.nn.functional.cross_entropy(model(vx[i:i+512]),vy[i:i+512],reduction='sum').item() for i in range(0,len(vy),512))
        return total/len(vy)/math.log(2)
    initial=evaluate();started=time.monotonic()
    def persist():
        c={'schema':1,'identity':expected,'config':CONFIG,'step':step,'torch':torch.__version__,'parameters':{},'momentum':{}}
        for name,p in model.named_parameters():
            c['parameters'][name]=p.detach().cpu().flatten().tolist()
            c['momentum'][name]=optimizer.state[p].get('momentum_buffer',torch.zeros_like(p)).detach().cpu().flatten().tolist()
        validate_checkpoint(c,expected);save(checkpoint,c)
    while step<end and not stop.is_set() and time.monotonic()-started<max_seconds:
        generator=torch.Generator(device='cpu').manual_seed(CONFIG['seed']+step)
        indexes=torch.randint(len(ty),(CONFIG['batch'],),generator=generator).to(device)
        loss=torch.nn.functional.cross_entropy(model(tx[indexes]),ty[indexes]);optimizer.zero_grad();loss.backward();optimizer.step();step+=1
        if step%1000==0:persist()
    persist();final=evaluate()
    # Compute the comparator on exactly these validation bytes; never fit it to validation.
    counts=[[0]*256 for _ in range(256)]
    for doc in splits['train']:
        raw=doc['text'].encode('utf-8')
        for a,b in zip(raw,raw[1:]):counts[a][b]+=1
    totals=[sum(row) for row in counts];total=0.;n=0
    for doc in splits['validation']:
        raw=doc['text'].encode('utf-8')
        for a,b in zip(raw,raw[1:]):total-=math.log2((counts[a][b]+.1)/(totals[a]+25.6));n+=1
    generator=torch.Generator(device='cpu').manual_seed(731);sample=bytearray(b'Alice ')
    with torch.no_grad():
        for _ in range(300):
            prefix=list(sample[-8:]);x=torch.tensor([[0]*(8-len(prefix))+prefix],device=device)
            probabilities=torch.softmax(model(x)[0].cpu(),dim=0)
            sample.append(int(torch.multinomial(probabilities,1,generator=generator)))
    (state/'sample.txt').write_text(sample.decode('utf-8',errors='replace')+'\n')
    result={'recipe':CONFIG['recipe'],'identity':expected,'device':device,'resumed_from_step':resumed,'step':step,'target_steps':6000,
            'completed':step==6000,'owner_stopped':stop.is_set(),'initial_bits_per_byte':initial,'heldout_bits_per_byte':final,
            'bigram_bits_per_byte':total/n,'beats_bigram':final<total/n,'heldout_bytes_predicted':n,
            'checkpoint_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),'elapsed_training_seconds':round(time.monotonic()-started,3),
            'network_training':False,'simulated_settlement':False}
    save(state/'report.json',result);return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu');p.add_argument('--steps',type=int,default=6000);p.add_argument('--max-seconds',type=int,default=120)
    args=p.parse_args();stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    print(json.dumps(run(args.dataset,args.state,args.device,args.steps,args.max_seconds,stop),indent=2))
if __name__=='__main__':main()
