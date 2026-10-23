#!/usr/bin/env python3
"""Replay the native rotating-RC fixture through an isolated real daemon.

Generate it using YERBAS_RC_FIXTURE=/absolute/path/fixture.txt before running
src/test/test_yerbas --run_test=recovery_consensus_lifecycle.
Commitments are cryptographically valid but constructed by the native fixture;
this does not simulate distributed DKG, reachability or independent operators.
"""
import argparse
import base64
import http.client
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bin-dir',type=Path,default=Path(__file__).resolve().parents[2]/'src')
p.add_argument('--fixture',type=Path,required=True)
p.add_argument('--workdir',type=Path)
a=p.parse_args()
lines=a.fixture.read_text().splitlines();expected=json.loads(lines[0]);blocks=lines[1:]
assert len(blocks)==1540
root=a.workdir or Path(tempfile.mkdtemp(prefix='rotating-rc-daemon-'))
root.mkdir(parents=True,exist_ok=True)
data=Path(tempfile.mkdtemp(prefix='node-',dir=root));binary=a.bin_dir.resolve()
sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
base=[f'-datadir={data}','-regtest',f'-rpcport={port}']
process=None;results=[]

def rpc(method,*args):
    cookie=(data/'regtest'/'.cookie').read_text().strip()
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=180)
    try:
        conn.request('POST','/',json.dumps({'jsonrpc':'1.0','id':1,'method':method,'params':list(args)}),
            {'Authorization':'Basic '+base64.b64encode(cookie.encode()).decode(),'Content-Type':'application/json'})
        response=json.loads(conn.getresponse().read())
    finally:conn.close()
    if response.get('error'):raise RuntimeError(response['error'])
    return response['result']

def start(extra=()):
    global process
    (data/'yerbas.conf').write_text('listen=0\nconnect=0\ndnsseed=0\ndiscover=0\nprinttoconsole=0\nposeactivationheight=600\nrecoveryactivationheight=600\n')
    with (data/'console.log').open('a') as out:
        process=subprocess.Popen([str(binary/'yerbasd')]+base+list(extra),stdout=out,stderr=out)
    for _ in range(600):
        if process.poll() is not None:raise RuntimeError((data/'console.log').read_text()[-5000:])
        try:rpc('getblockcount');return
        except (OSError,RuntimeError):time.sleep(.25)
    raise RuntimeError('startup timeout')

def stop():
    global process
    if process and process.poll() is None:
        try:rpc('stop')
        except Exception:process.terminate()
        process.wait(timeout=60)
    process=None

def record(name):
    results.append({'case':name,'passed':True});print(name,flush=True)

def status():return rpc('recovery','status')

try:
    start()
    assert status()['enabled'] is False
    record('inactive before activation, no appointed keys configured')
    for height,block in enumerate(blocks,1):
        result=rpc('submitblock',block)
        assert result is None,(height,result)
        if height==738:
            s=status()
            assert s['mode']=='recovery' and not s['canAuthorize'] and s['members']==[],s
            record('three failures cannot appoint a committee without qualifying history')
        if height==1440:
            s=status()
            assert s['qualified']==80 and len(s['members'])==15 and s['threshold']==11,s
            assert s['committeeHash']==expected['committee'],s
            record('daemon independently selects the same 15 members from 80 qualified registrations')
        if height==1518:
            s=status();assert s['mode']=='recovery' and s['canAuthorize'],s
            assert s['committeeHash']==expected['committee']
            record('three later failures activate the preselected 11-of-15 committee')
    s=status();assert s['consumed']==1,s
    assert rpc('protx','info',expected['target'])['state']['PoSePenalty']==expected['penalty']
    penaltyblock=rpc('getblockhash',1540)
    record('real daemon validates and applies the selected-member penalty transaction')
    stop();start()
    assert status()['committeeHash']==expected['committee'] and status()['consumed']==1
    record('roster, participation state and consumed allowance survive restart')
    rpc('invalidateblock',penaltyblock)
    assert status()['consumed']==0
    rpc('reconsiderblock',penaltyblock)
    assert status()['consumed']==1
    record('penalty rollback and reconnect restore allowance')
    # Undo the roster creation block as well, then reconstruct the entire branch.
    rotationblock=rpc('getblockhash',1440)
    rpc('invalidateblock',rotationblock)
    assert rpc('getblockcount')==1439 and status()['committeeHash']!=expected['committee']
    rpc('reconsiderblock',rotationblock)
    assert rpc('getblockcount')==1540 and status()['committeeHash']==expected['committee']
    record('disconnecting selection and reconnecting reproduces roster and history')
    stop();start(('-reindex',))
    for _ in range(720):
        if rpc('getblockcount')==1540:break
        time.sleep(.25)
    assert rpc('getblockcount')==1540 and status()['committeeHash']==expected['committee']
    assert status()['consumed']==1
    record('full reindex independently reconstructs participation, selection and enforcement')
    address=rpc('getnewaddress')
    rpc('generatetoaddress',260,address)
    assert status()['committeeHash']==expected['committee']
    record('scheduled rotation does not replace the active recovery roster')
    rpc('generatetoaddress',78,address)
    assert status()['mode']=='locked'
    rpc('generatetoaddress',120,address)
    assert status()['mode']=='locked'
    record('expiry locks authority without automatic renewal')
    stop()
    for option in ('-recoveryactivationheight=600','-recoverypubkey=00','-recoveryprivkey=00'):
        gate=Path(tempfile.mkdtemp(prefix='gate-',dir=root))
        rejected=subprocess.run([str(binary/'yerbasd'),f'-datadir={gate}',option,'-listen=0','-connect=0','-dnsseed=0'],capture_output=True,text=True,timeout=30)
        assert rejected.returncode and ('regtest-only' in rejected.stderr or 'unsupported' in rejected.stderr),rejected.stderr
    record('public activation overrides and obsolete appointed-key options rejected')
finally:
    stop()
    (root/'rotating-rc-daemon-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
