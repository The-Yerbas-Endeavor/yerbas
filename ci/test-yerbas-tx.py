#!/usr/bin/env python3
"""Offline smoke and argument-validation checks for a built yerbas-tx."""
import hashlib,json,subprocess,sys
from pathlib import Path
if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 ci/test-yerbas-tx.py /path/to/yerbas-tx')
b=Path(sys.argv[1]).resolve()
def run(*args,ok=True):
 p=subprocess.run([str(b),*args],capture_output=True,text=True,timeout=15)
 assert (p.returncode==0)==ok,(args,p.stderr)
 return p.stdout.strip()
def base58(raw):
 raw+=hashlib.sha256(hashlib.sha256(raw).digest()).digest()[:4]
 n=int.from_bytes(raw,'big');out='';chars='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
 while n:n,i=divmod(n,58);out=chars[i]+out
 return '1'*(len(raw)-len(raw.lstrip(b'\0')))+out
address=base58(bytes([140])+bytes(20))
hex_tx=run('-create','outaddr=0.25:'+address,'outdata=abcd','locktime=42')
tx=json.loads(run('-json',hex_tx));assert tx['locktime']==42 and len(tx['vout'])==2 and tx['vout'][0]['value']==0.25
assert tx['vout'][0]['scriptPubKey']['addresses']==[address]
assert run('-txid',hex_tx)==tx['txid']
assert len(json.loads(run('-json',hex_tx,'delout=1'))['vout'])==1
for arg in ['nversion=1foo','locktime=2foo','locktime=4294967296','delout=0foo','delin=0foo','in='+('00'*32)+':0foo','in='+('00'*32)+':0:1foo','in='+('00'*32)+':0:4294967296','in='+('00'*32)+':0:1:2']:
 run(hex_tx,arg,ok=False)
# Public test key 1 (uncompressed), with a matching P2PKH previous output.
wif=base58(bytes([128])+bytes(31)+b'\x01')
txid='11'*32
prev=[dict(txid=txid,vout=0,scriptPubKey='76a91491b24bf9f5288532960ac687abb035127b1d28a588ac',amount=1)]
signed=json.loads(run('-json','-create','in='+txid+':0','outaddr=0.25:'+address,'set=privatekeys:'+json.dumps([wif]),'set=prevtxs:'+json.dumps(prev),'sign=ALL'))
assert signed['vin'][0]['scriptSig']['hex']
assert run(signed['hex'])==signed['hex']
print('PASS: create, decode, address output, data output, txid, mutation, signing, round-trip, and 9 malformed numeric/input cases.')
