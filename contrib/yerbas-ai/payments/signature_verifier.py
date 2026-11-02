"""Offline native Yerbas signature checks for exact single-input P2PKH candidates.
No signing/key/RPC capability. Native consensus validation is supplemented with
SIGHASH_ALL, minimal pushes, low-S, exact unsigned bytes and final-size fee checks.
"""
import subprocess
import hashlib
from pathlib import Path
ORDER=0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141
FLAGS=1|4|16|512|1024

def double_hash(raw):return hashlib.sha256(hashlib.sha256(raw).digest()).digest()[::-1].hex()

class Consensus:
 def __init__(self,path,sha256):
  self.path=Path(path)
  if self.path.is_symlink() or hashlib.sha256(self.path.read_bytes()).hexdigest()!=sha256:raise ValueError('Pinned native verifier required')
  self.sha256=sha256
 def verify(self,script,raw):
  if hashlib.sha256(self.path.read_bytes()).hexdigest()!=self.sha256:raise ValueError('Native verifier changed')
  result=subprocess.run([str(self.path.resolve()),script.hex(),raw.hex()],capture_output=True,text=True,timeout=10)
  if result.returncode!=0 or result.stdout.strip()!='1 0':raise ValueError('Native input signature verification failed')

def strip_signature(raw):
 if not 85<=len(raw)<=1000 or raw[4]!=1:raise ValueError('One ordinary input required')
 length=raw[41]
 if not 1<=length<=140 or len(raw)<=42+length:raise ValueError('Bounded canonical scriptSig required')
 script=raw[42:42+length]
 n=script[0]
 if not 9<=n<=73 or len(script)<n+2:raise ValueError('Direct DER signature push required')
 signature=script[1:1+n]
 if signature[-1]!=1:raise ValueError('SIGHASH_ALL without ANYONECANPAY required')
 keylen=script[1+n];key=script[n+2:]
 if keylen!=len(key) or not ((keylen==33 and key[0] in (2,3)) or (keylen==65 and key[0]==4)):raise ValueError('Canonical public key push required')
 der=signature[:-1]
 if len(der)<8 or der[0]!=48 or der[1]!=len(der)-2 or der[2]!=2:raise ValueError('Invalid DER')
 rlen=der[3];offset=4+rlen
 if offset+2>len(der) or der[offset]!=2:raise ValueError('Invalid DER S')
 slen=der[offset+1];sbytes=der[offset+2:]
 if slen!=len(sbytes) or not sbytes or not 0<int.from_bytes(sbytes,'big')<=ORDER//2:raise ValueError('Low-S signature required')
 return raw[:41]+b'\x00'+raw[42+length:]

def verify_signed(signed_hex,candidate,previous_script_hex,consensus,minrelay_units_per_kb=1000):
 if not isinstance(signed_hex,str) or len(signed_hex)>2000:raise ValueError('Bounded signed transaction required')
 raw=bytes.fromhex(signed_hex);unsigned=strip_signature(raw)
 expected=bytes.fromhex(candidate['raw_unsigned_hex'])
 if unsigned!=expected or hashlib.sha256(expected).hexdigest()!=candidate['raw_bytes_sha256']:raise ValueError('Signed transaction changes candidate')
 script=bytes.fromhex(previous_script_hex)
 if len(script)!=25 or script[:3]!=bytes.fromhex('76a914') or script[-2:]!=bytes.fromhex('88ac'):raise ValueError('P2PKH prevout required')
 if type(minrelay_units_per_kb) is not int or minrelay_units_per_kb<=0:raise ValueError('Explicit positive relay rate required')
 fee=candidate['fee_base_units']
 if type(fee) is not int or not (len(raw)*minrelay_units_per_kb+999)//1000<=fee<=10000:raise ValueError('Final-size fee outside allowed bounds')
 consensus.verify(script,raw)
 return dict(signed_txid=double_hash(raw),signed_bytes=len(raw),fee_base_units=fee,
             signatures_verified=True,exact_candidate_verified=True,spending_authorized=False)

def binding_verifier(consensus,previous_script_hex,minrelay_units_per_kb=1000):
 """Adapter for TrackingStore.bind_verified; caller must freshly verify prevout."""
 def check(signed_hex,candidate):
  return verify_signed(signed_hex,candidate,previous_script_hex,consensus,minrelay_units_per_kb)['signed_txid']
 return check
