"""Read-only native chain observations for both enrolled testnet hosts."""
import json,subprocess,shlex
def node(host):
 if host not in ('u26-2T','anno2-u26'):raise ValueError('Enrolled testnet host required')
 owner='anno' if host=='u26-2T' else 'anno2'
 root='/home/'+owner+'/.local/share/yerbas-ai-testnet-v1'
 def rpc(method,*args):
  if method not in {'getblockhash','getblockchaininfo','getrawtransaction','getblockheader'}:raise ValueError('Read-only methods required')
  argv=[root+'/bin/yerbas-cli','-testnet=1','-testnetfastcollateral=1','-datadir='+root+'/state','-rpcport=21522',method]+[a if type(a) is str else json.dumps(a) for a in args]
  cmd=argv if host=='u26-2T' else ['ssh','-o','BatchMode=yes','anno2']+[shlex.join(argv)]
  r=subprocess.run(cmd,text=True,capture_output=True,timeout=25)
  if r.returncode:raise RuntimeError('Read-only chain check failed on '+host)
  try:return json.loads(r.stdout)
  except json.JSONDecodeError:return r.stdout.strip()
 return rpc
