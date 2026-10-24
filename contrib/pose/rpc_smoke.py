#!/usr/bin/env python3
"""Local RPC smoke tests; starts isolated nodes with peer networking disabled."""
import argparse, json, pathlib, socket, subprocess, tempfile, time
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bin-dir', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2]/'src')
parser.add_argument('--workdir', type=pathlib.Path)
args=parser.parse_args()
root=args.workdir or pathlib.Path(tempfile.mkdtemp(prefix='yerbas-pose-smoke-'))
root.mkdir(parents=True, exist_ok=True)
bin=args.bin_dir.resolve()
results=[]

def run_case(active):
    directory=pathlib.Path(tempfile.mkdtemp(prefix='pose-regtest-',dir=root))
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
    args=[f'-datadir={directory}','-regtest',f'-rpcport={port}','-listen=0','-connect=0','-dnsseed=0','-discover=0','-printtoconsole=0']
    if active: args.append('-poseactivationheight=30')
    with (directory/'console.log').open('w') as log:
        process=subprocess.Popen([str(bin/'yerbasd')]+args,stdout=log,stderr=log)
        def rpc(*cmd,check=True):
            p=subprocess.run([str(bin/'yerbas-cli')]+args[:3]+list(map(str,cmd)),capture_output=True,text=True,timeout=30)
            if check and p.returncode: raise RuntimeError(p.stderr)
            if not check: return p
            if not p.stdout.strip(): return None
            try: return json.loads(p.stdout)
            except json.JSONDecodeError: return p.stdout.strip()
        try:
            for _ in range(60):
                if process.poll() is not None: raise RuntimeError((directory/'console.log').read_text())
                try: status=rpc('pose','status');break
                except Exception: time.sleep(0.5)
            else: raise RuntimeError('RPC startup timeout')
            assert status['active'] is False and status['minimumMonitors']==3,status
            if active:
                address=rpc('getnewaddress')
                rpc('generatetoaddress',29,address)
                assert rpc('pose','status')['active'] is False
                rpc('generatetoaddress',11,address)
                assert rpc('pose','status')['active'] is True
                assert rpc('getblockcount')==40
                bad=rpc('pose','submitcertificate','00',check=False)
                assert bad.returncode != 0
                unknown=rpc('pose','request','00'*32,30,check=False)
                assert unknown.returncode != 0 and 'Unknown smartnode' in unknown.stderr, unknown.stderr
            results.append({'case':'regtest activation at 30' if active else 'regtest default disabled','passed':True})
        finally:
            if process.poll() is None:
                try:rpc('stop')
                except Exception:process.terminate()
                process.wait(timeout=30)

run_case(False)
run_case(True)
directory=pathlib.Path(tempfile.mkdtemp(prefix='pose-mainnet-gate-',dir=root))
p=subprocess.run([str(bin/'yerbasd'),f'-datadir={directory}','-poseactivationheight=30','-listen=0','-connect=0','-dnsseed=0'],capture_output=True,text=True,timeout=20)
assert p.returncode !=0 and 'regtest-only' in p.stderr,(p.returncode,p.stderr)
results.append({'case':'mainnet activation override rejected','passed':True})
print(json.dumps(results,indent=2))
(root/'pose-rpc-results.json').write_text(json.dumps(results,indent=2)+'\n')
