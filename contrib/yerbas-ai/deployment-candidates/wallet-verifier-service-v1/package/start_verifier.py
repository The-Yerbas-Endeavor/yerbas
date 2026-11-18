"""Run the fixed public-text GPU demo under the dedicated provider account."""
import argparse,fcntl,json,os,platform,pwd,re,signal,subprocess,sys,time
from pathlib import Path
from run_gpu_gate import ROOT,provider_processes

def signal_worker(process,signum,uid):
    # This supervisor is single-threaded. Signal only its retained child as the
    # dedicated worker account, then restore its effective UID. CAP_KILL is not needed.
    if os.geteuid()!=0 or uid==0:raise ValueError('Dedicated worker signal required')
    try:
        os.seteuid(uid)
        process.send_signal(signum)
    finally:
        os.seteuid(0)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--ready',type=Path,required=True);p.add_argument('--gate',type=Path,required=True);args=p.parse_args()
    if os.geteuid()!=0 or platform.node()!='anno2-u26':raise SystemExit('Requires sudo on anno2-u26')
    if not re.fullmatch('[a-f0-9]{32}',args.run_id):raise SystemExit('Invalid run identity')
    from text_baseline import load_dataset
    manifest,_=load_dataset(args.dataset)
    if sum(r['bytes'] for r in manifest['splits'])>16*1024*1024:raise SystemExit('Corpus exceeds pilot bound')
    runtime=Path('/opt/yerbas-ai/runtime-v1/venv/bin/python')
    if not runtime.exists():raise ValueError('Protected runtime missing; no download attempted')
    for target in (runtime,runtime.resolve()):
        for path in (target,*target.parents):
            info=path.stat()
            if info.st_uid!=0 or info.st_mode & 0o022:raise ValueError('Runtime is not root controlled: '+str(path))
    account=pwd.getpwnam('yerbas-provider');base=ROOT/('text-demo-'+args.run_id)
    stopped=False;process=None
    def stop(*_):
        nonlocal stopped
        stopped=True
        if process is not None and process.poll() is None:signal_worker(process,signal.SIGTERM,account.pw_uid)
    for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stop)
    with (ROOT/'continuous-worker.lock').open('a') as lock,(ROOT/'gpu-probe.lock').open('a') as gpu_lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(gpu_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if provider_processes(account.pw_uid):raise SystemExit('Provider already busy')
        if subprocess.check_output(['nvidia-smi','--id=0','--query-compute-apps=pid','--format=csv,noheader'],text=True,timeout=10).strip():raise SystemExit('GPU 0 busy; no workload stopped')
        if args.ready.exists() or args.gate.exists() or args.ready.parent!=args.gate.parent:raise ValueError('Fresh activation gate required')
        with args.ready.open('x') as f:f.write(args.run_id)
        args.ready.chmod(0o644);deadline=time.monotonic()+60
        while not args.gate.exists():
            if stopped or time.monotonic()>deadline:raise RuntimeError('Activation cancelled or timed out')
            time.sleep(.1)
        if args.gate.read_text()!=args.run_id:raise ValueError('Activation identity differs')
        base.mkdir(mode=0o755);base.chmod(0o755);dataset=base/'dataset';dataset.mkdir(mode=0o755);dataset.chmod(0o755)
        for name in ('manifest.json','train.jsonl','validation.jsonl'):
            data=(args.dataset/name).read_bytes()
            if len(data)>16*1024*1024:raise ValueError('Dataset file too large')
            path=dataset/name;path.write_bytes(data);path.chmod(0o644)
        load_dataset(dataset)
        for name in ('text_neural.py','text_baseline.py'):
            path=base/name;path.write_bytes(Path(__file__).with_name(name).read_bytes());path.chmod(0o644)
        state=base/'private';state.mkdir(mode=0o700);os.chown(state,account.pw_uid,account.pw_gid)
        env={'PATH':'/usr/bin:/bin','HOME':account.pw_dir,'CUDA_VISIBLE_DEVICES':'0','CUBLAS_WORKSPACE_CONFIG':':4096:8','PYTHONNOUSERSITE':'1'}
        command=[str(runtime),str(base/'text_neural.py'),'--dataset',str(dataset),'--state',str(state),'--device','cuda','--steps','6000','--max-seconds','120']
        failure=None;began=time.monotonic()
        with (base/'runner.log').open('w') as log:
            process=subprocess.Popen(command,user=account.pw_uid,group=account.pw_gid,extra_groups=[],env=env,cwd=base,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            try:
                while process.poll() is None:
                    if stopped:raise RuntimeError('Owner stopped text demo')
                    if time.monotonic()-began>165:raise RuntimeError('Text demo exceeded overall bound')
                    temperature=int(subprocess.check_output(['nvidia-smi','--id=0','--query-gpu=temperature.gpu','--format=csv,noheader,nounits'],text=True,timeout=3).strip())
                    if temperature>=80:raise RuntimeError('GPU reached 80 C')
                    time.sleep(.5)
            except Exception as exc:failure=str(exc)
            finally:
                if process.poll() is None:
                    signal_worker(process,signal.SIGTERM,account.pw_uid)
                    try:process.wait(timeout=20)
                    except subprocess.TimeoutExpired:signal_worker(process,signal.SIGKILL,account.pw_uid);process.wait()
        idle=not provider_processes(account.pw_uid)
        report=json.loads((state/'report.json').read_text()) if (state/'report.json').exists() else None
        result={'run_id':args.run_id,'host':platform.node(),'physical_gpu':'0','exit_code':process.returncode,'provider_idle':idle,'error':failure,'report':report,
                'execution_passed':process.returncode==0 and failure is None and idle and report is not None,
                'quality_target_met':bool(process.returncode==0 and failure is None and idle and report and report['completed'] and report['beats_bigram']),
                'two_host_text_training_tested':False}
        (base/'status.json').write_text(json.dumps(result,indent=2)+'\n');(base/'status.json').chmod(0o644)
        if (state/'sample.txt').exists():(base/'sample.txt').write_bytes((state/'sample.txt').read_bytes());(base/'sample.txt').chmod(0o644)
        if result['execution_passed'] and report['step']==6000:
            from text_neural import read_checkpoint,identity
            read_checkpoint(state/'checkpoint.json',identity(dataset))
            public=base/'verified-public-checkpoint.json';public.write_bytes((state/'checkpoint.json').read_bytes());public.chmod(0o644)
        print(json.dumps(result,indent=2))
        if not result['execution_passed']:raise SystemExit('Text demo incomplete; inspect retained report/log')
if __name__=='__main__':main()
