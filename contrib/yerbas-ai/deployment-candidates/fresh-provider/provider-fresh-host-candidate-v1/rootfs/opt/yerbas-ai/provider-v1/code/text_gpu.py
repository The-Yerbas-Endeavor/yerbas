"""Fixed text executor for the schema-4 HTTPS worker."""
import argparse,hashlib,json,os,signal,subprocess,sys,threading,time
from pathlib import Path
from text_neural import identity,read_checkpoint
from text_worker import run_once
from text_https import Client
from network_training_worker import OwnerStopped
from sustained_training import atomic_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',type=Path,required=True);p.add_argument('--state',type=Path,required=True);args=p.parse_args()
    cfg=json.loads(args.config.read_text());dataset=Path(cfg['dataset']);approved=identity(dataset)
    if approved!=cfg['expected_identity']:raise ValueError('Local text recipe or corpus differs from approval')
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    client=Client(cfg['url'],cfg['token'],cfg['ca'])
    origin=hashlib.sha256(json.dumps([cfg['url'],hashlib.sha256(cfg['token'].encode()).hexdigest(),hashlib.sha256(Path(cfg['ca']).read_bytes()).hexdigest()]).encode()).hexdigest()
    def execute(m,state,remaining,stop,guard):
        gpu=os.environ.get('YERBAS_PHYSICAL_GPU')
        if gpu not in ('0','1') or os.environ.get('CUDA_VISIBLE_DEVICES')!=gpu:raise ValueError('GPU binding missing')
        if identity(dataset)!=m['identity']:raise ValueError('Dataset or source changed')
        checkpoint=state/'checkpoint.json';step=read_checkpoint(checkpoint,approved)['step'] if checkpoint.exists() else 0
        if not m['start_step']<=step<m['end_step']:raise ValueError('Invalid resumed step')
        if remaining<1 or stop.is_set():raise OwnerStopped('No remaining authorized runtime')
        command=[sys.executable,str(Path(__file__).with_name('text_neural.py')),'--dataset',str(dataset),'--state',str(state),'--device','cuda','--steps',str(m['end_step']-step),'--max-seconds',str(min(120,int(remaining)))]
        started=time.monotonic()
        with (state/'runner.log').open('a') as log:
            child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while child.poll() is None:
                    if stop.is_set():raise OwnerStopped('Owner stopped text contribution')
                    guard.check()
                    if time.monotonic()-started>=remaining:raise RuntimeError('Text contribution deadline reached')
                    temp=int(subprocess.check_output(['nvidia-smi','--id='+gpu,'--query-gpu=temperature.gpu','--format=csv,noheader,nounits'],text=True,timeout=3).strip())
                    if temp>=80:raise RuntimeError('GPU reached 80 C')
                    stop.wait(.25)
            finally:
                if child.poll() is None:
                    os.killpg(child.pid,signal.SIGTERM)
                    try:child.wait(timeout=20)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        if child.returncode:raise RuntimeError('Text runner failed; private checkpoint retained')
        report=json.loads((state/'report.json').read_text())
        if report['identity']!=approved or report['device']!='cuda' or report['step']!=m['end_step'] or report['owner_stopped']:raise ValueError('Text runner did not complete assigned segment')
        atomic_json(state/'identity-verified.json',approved)
    receipt=run_once(args.state,client,cfg['provider'],cfg['contribution'],origin,approved,execute,stop)
    print(json.dumps({'receipt':receipt,'passed':True}))
if __name__=='__main__':main()
