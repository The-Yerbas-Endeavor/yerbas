"""Fixed text executor for the schema-4 HTTPS worker."""
import argparse,hashlib,json,os,signal,subprocess,sys,threading,time,uuid
from attempt_evidence import bind
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
    training_only=cfg.get('training_attribution',False)
    if type(training_only) is not bool:raise ValueError('Explicit boolean attribution setting required')
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
        attempt=state/'measurements'/uuid.uuid4().hex
        attempt.mkdir(mode=0o700,parents=True)
        atomic_json(attempt/'start.json',dict(schema=1,attempt_id=attempt.name,manifest=m,physical_gpu=gpu,start_step=step,initial_checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest() if checkpoint.exists() else None))
        command=[sys.executable,str(Path(__file__).with_name('profile_attempt.py')),'--dataset',str(dataset),'--state',str(state),'--attempt',str(attempt),'--steps',str(m['end_step']-step),'--max-seconds',str(min(120,int(remaining)))]
        if training_only:command.append('--training-attribution')
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
        atomic_json(attempt/'process-result.json',dict(exit_code=child.returncode,signal=-child.returncode if child.returncode<0 else None))
        if child.returncode:raise RuntimeError('Text runner failed with exit code '+str(child.returncode)+'; private checkpoint retained')
        report=json.loads((state/'report.json').read_text())
        if report['identity']!=approved or report['device']!='cuda' or report['step']!=m['end_step'] or report['owner_stopped']:raise ValueError('Text runner did not complete assigned segment')
        atomic_json(state/'identity-verified.json',approved)
    receipt=run_once(args.state,client,cfg['provider'],cfg['contribution'],origin,approved,execute,stop)
    attached=[]
    for attempt in sorted((args.state/'training/measurements').glob('*')):
        if not (attempt/'measurement.json').exists():continue
        start=json.loads((attempt/'start.json').read_text());measurement=json.loads((attempt/'measurement.json').read_text());report=json.loads((attempt/'report.json').read_text())
        # Retain earlier partial attempts, but never relabel them as the final result.
        if report['checkpoint_sha256']!=receipt['sha256']:continue
        if training_only and 'training_attribution' not in measurement:raise ValueError('Requested training attribution missing')
        evidence=bind(start,measurement,report,receipt)
        atomic_json(attempt/'receipt-evidence.json',evidence);attached.append(evidence['evidence_sha256'])
    print(json.dumps({'receipt':receipt,'passed':True,'measurement_evidence':attached,'reward_eligible':False}))
if __name__=='__main__':main()
