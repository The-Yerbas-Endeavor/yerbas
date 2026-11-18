"""Per-order owner context for the persistent rental and protected payment services."""
import json,os,re,subprocess,sys,time
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(OUT/'wallet-consensus-rental-v1'),str(OUT/'paid-rental-v1'),str(OUT/'marketplace-offers-v1'),str(OUT/'wallet-identity-prototype'),str(OUT/'YERB-Coordinator/runtime/yerbas-ai-coordinator-private-0.3.0/code')]
from commands import digest,retain
from wallet_rpc import request as wallet
sys.path.insert(0,str(OUT/'wallet-rental-credit-v2'))
from fund import rpc
GENESIS='e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554'
REMOTE="""import json,pwd,socket,struct,sys
raw=sys.stdin.buffer.read(65537)
if len(raw)>65536:raise ValueError('Bounded request required')
r=json.loads(raw)
with socket.socket(socket.AF_UNIX) as s:
 s.settimeout(30);s.connect('/run/yerbas-wallet-rental/control.sock')
 if struct.unpack('3i',s.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]!=pwd.getpwnam('yerbas-coordinator').pw_uid:raise ValueError('Coordinator peer differs')
 s.sendall(json.dumps(r).encode()+b'\\n');raw=s.makefile('rb').readline(131073)
 if len(raw)>131072:raise ValueError('Bounded reply required')
 response=json.loads(raw)
 if not response.get('ok'):raise ValueError(response.get('error','Refused'))
 print(json.dumps(response['result']))
"""
class Context:
 SSH_ANNO2=['ssh','-o','BatchMode=yes','anno2']
 rpc=staticmethod(rpc)
 def __init__(self,quote,state):
  if type(quote)is not str or not re.fullmatch('[a-f0-9]{32}',quote):raise ValueError('Exact quote required')
  self.quote=quote;self.state=Path(state);self.trial=self;self.STATE=self.state
  if self.state.is_symlink() or not self.state.is_dir() or self.state.stat().st_uid!=os.getuid() or self.state.stat().st_mode&0o077:raise ValueError('Private owner state required')
 def remote(self,action,**fields):
  import shlex
  result=subprocess.run(self.SSH_ANNO2+[shlex.join(['/usr/bin/python3','-I','-B','-c',REMOTE])],input=json.dumps(dict(action=action,quote_id=self.quote,**fields)),capture_output=True,text=True,timeout=40)
  if result.returncode:raise RuntimeError('Rental service refused: '+result.stderr[-700:])
  return json.loads(result.stdout)
 def load(self,name):return json.loads((self.state/name).read_text())
 def save(self,name,value):retain(self.state/name,value)
 def save_once(self,name,value):
  if (self.state/name).exists():
   if self.load(name)!=value:raise ValueError('Retained evidence differs')
  else:self.save(name,value)
 def network(self):
  c=rpc('getblockchaininfo')
  if rpc('getblockhash',0)!=GENESIS or c['chain']!='test' or c['initialblockdownload']:raise ValueError('Synced private testnet required')
  return c
 def funding(self):
  r=wallet('marketplace.fundingstatus',{'quote_id':self.quote})
  if r.get('currently_funded') is not True:raise ValueError('Current unspent deposit required')
  return dict(r['observation'],checked_at=int(time.time()),genesis=GENESIS)
