#!/usr/bin/env python3
"""Exercise RC signing RPCs with generated active smartnode identities.

This serial regtest harness is not distributed DKG or independent operators.

Generate both inputs in the same native test run, with umask 077:
YERBAS_RC_FIXTURE=/absolute/path/fixture.txt and
YERBAS_RC_RPC_KEYS=/absolute/path/keys.json before running
src/test/test_yerbas --run_test=recovery_consensus_lifecycle.
Keep the generated keys file local and never publish it.
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
p.add_argument('--keys',type=Path,required=True,help='Local-only generated test secrets')
a=p.parse_args()
secrets=json.loads(a.keys.read_text())
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

def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1",0));return s.getsockname()[1]

def start(identity=None):
    global process
    config='listen=0\nconnect=0\npersistmempool=0\nwalletbroadcast=0\ndnsseed=0\ndiscover=0\nprinttoconsole=0\nposeactivationheight=600\nrecoveryactivationheight=600\n'
    if identity:
        config=config.replace('listen=0', 'listen=1')
        # The registered test service is advertised only; all listening is local.
        config+=f"bind=127.0.0.1:{free_port()}\nexternalip={identity['service']}\nsmartnodeblsprivkey={identity['key']}\n"
    conf=data/'yerbas.conf'
    conf.touch(mode=0o600,exist_ok=True)
    conf.write_text(config)
    with (data/'console.log').open('a') as out:
        process=subprocess.Popen([str(binary/'yerbasd')]+base,stdout=out,stderr=out)
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

def rejects(fragment, method, *args):
    try: rpc(method,*args)
    except RuntimeError as error:
        expected_errors=(fragment,) if isinstance(fragment,str) else fragment
        assert any(item in str(error) for item in expected_errors),(fragment,str(error))
    else: raise AssertionError(f'{method} unexpectedly accepted invalid input')

def activate(identity):
    stop();start(identity)
    for _ in range(120):
        s=rpc('smartnode','status')
        if s.get('proTxHash')==identity['proTxHash']:return
        time.sleep(.25)
    raise AssertionError('Generated smartnode identity did not activate: '+str(s))

try:
    start()
    for height,block in enumerate(blocks[:1539],1):
        assert rpc('submitblock',block) is None,height
    assert status()['canAuthorize'] and status()['consumed']==0
    request=rpc('recovery','request',expected['target'],'1519','1539')
    rejects('active registered smartnode','recovery','sign',request)
    rejects('bad-recovery-signatures','recovery','maketx',request)
    record('unsigned request cannot authorize a transaction or be signed by a wallet node')
    activate(secrets['nonmember'])
    rejects('not in the selected RC','recovery','sign',request)
    record('active registered nonmember cannot sign')
    signed=[]
    for identity in secrets['signers'][:11]:
        activate(identity)
        part=rpc('recovery','sign',request)
        rejects('Already signed','recovery','sign',part)
        signed.append(part)
    record('eleven selected active identities sign through the daemon RPC')
    # A wallet coordinator has no operator secret. Merge signatures in reverse
    # order and merge the same contribution twice to exercise de-duplication.
    stop();start()
    combined=request
    for part in reversed(signed[:10]):combined=rpc('recovery','merge',combined,part)
    combined=rpc('recovery','merge',combined,signed[0])
    rejects('bad-recovery-signatures','recovery','maketx',combined)
    record('ten distinct approvals plus a duplicate remain below threshold')
    combined=rpc('recovery','merge',combined,signed[10])
    raw=rpc('recovery','maketx',combined)
    other=rpc('recovery','request',expected['target'],'1520','1539')
    rejects('Different recovery requests','recovery','merge',combined,other)
    corrupt=bytearray.fromhex(combined);corrupt[-1]^=1
    rejects(('Invalid recovery certificate','bad-recovery-signatures'),'recovery','maketx',corrupt.hex())
    # Keep a valid BLS encoding but put signer zero's signature at signer ten.
    wrong_signature=combined[:-192]+signed[0][-192:]
    rejects('bad-recovery-signatures','recovery','maketx',wrong_signature)
    record('eleven approvals authorize; altered signatures and mismatched requests fail')
    rpc('importprivkey',secrets['fundingKey'],'regtest-fixture',True)
    funded=rpc('fundrawtransaction',raw)
    tx=rpc('signrawtransaction',funded['hex'])
    assert tx['complete']
    txid=rpc('sendrawtransaction',tx['hex'])
    address=rpc('getnewaddress')
    mined=rpc('generatetoaddress',1,address)[0]
    assert txid in rpc('getblock',mined)['tx']
    assert status()['consumed']==1
    assert rpc('protx','info',expected['target'])['state']['PoSePenalty']==expected['penalty']
    rejects('bad-recovery','recovery','maketx',combined)
    record('wallet funds and signs RC transaction; mempool and mined block apply penalty once')
    # Roll back the penalty so expiry rejection cannot be masked by consumption.
    rpc('invalidateblock',mined)
    assert status()['consumed']==0
    stop();start()
    assert rpc('getrawmempool')==[]
    rpc('generatetoaddress',31,address)
    assert status()['consumed']==0
    activate(secrets['signers'][0])
    rejects('bad-recovery-window','recovery','sign',request)
    record('selected signer refuses an expired observation request')
finally:
    stop()
    # Remove operator secrets from the last config; generated key file remains
    # private for reproducibility and must never be committed or published.
    (data/'yerbas.conf').write_text('regtest=1\nlisten=0\nconnect=0\n')
    (root/'rc-rpc-results.json').write_text(json.dumps(results,indent=2)+'\n')
print(json.dumps(results,indent=2))
