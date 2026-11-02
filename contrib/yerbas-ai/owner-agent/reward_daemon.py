"""Socket-activated unprivileged request relay; no signing or GPU execution."""
import hashlib,http.client,json,os,re,signal,socket,ssl
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reward_socket import CA,CA_SHA,ORIGIN,SOCKET,frame,load_config,peer_uid,trusted,unique
class Client:
 def __init__(self):
  self.config=load_config()
  if os.getuid()!=self.config['provider_uid']:raise ValueError('Separate provider owner required')
  self.credentials=json.loads(trusted('/etc/yerbas-ai/provider-future-enrollment.json',True),object_pairs_hook=unique)
  c=self.credentials
  if set(c)!={'url','token','ca','provider'} or c['url']!=ORIGIN or c['ca']!=CA or c['provider']!=self.config['provider'] or not isinstance(c['token'],str) or not 20<=len(c['token'])<=256:raise ValueError('Existing enrollment differs')
  if hashlib.sha256(trusted(CA)).hexdigest()!=CA_SHA:raise ValueError('CA binding differs')
  self.context=ssl.create_default_context(cafile=CA);self.context.minimum_version=ssl.TLSVersion.TLSv1_2
 def cancel_contribution(self,contribution):
  return self.request('/v4/text/cancel/'+contribution,'cancellation')
 def request(self,path,field):
  c=http.client.HTTPSConnection('127.0.0.1',19444,context=self.context,timeout=3)
  try:
   c.request('POST',path,b'{}',{'Content-Type':'application/json','Authorization':'Bearer '+self.credentials['token']})
   r=c.getresponse();raw=r.read(8193)
   if r.status!=200 or len(raw)>8192:raise ValueError('Coordinator request unavailable')
   value=json.loads(raw,object_pairs_hook=unique)
   if set(value)!={field}:raise ValueError('Invalid response')
   return value[field]
  finally:c.close()
 def reward(self,action,receipt):
  c=http.client.HTTPSConnection('127.0.0.1',19444,context=self.context,timeout=3)
  try:
   c.request('POST','/v1/rewards/'+action+'/'+receipt,b'{}',{'Content-Type':'application/json','Authorization':'Bearer '+self.credentials['token']})
   r=c.getresponse();raw=r.read(8193)
   if r.status!=200 or len(raw)>8192:raise ValueError('Coordinator request unavailable')
   body=json.loads(raw,object_pairs_hook=unique)
   if set(body)!={'schema','reward_request'} or body['schema']!=1:raise ValueError('Invalid response')
   return body['reward_request']
  finally:c.close()
def dispatch(client,uid,request):
 response={'v':1,'id':None,'ok':False,'error':{'code':'reward_request_unavailable'}}
 try:
  if uid!=client.config['owner_uid']:raise ValueError('Unauthorized owner')
  if type(request) is not dict or set(request)!={'v','id','method','params'} or type(request['v']) is not int or request['v']!=1 or not isinstance(request['id'],str) or not re.fullmatch('[a-f0-9]{32}',request['id']):raise ValueError('Invalid frame')
  response['id']=request['id'];method=request['method'];params=request['params']
  if method=='contributions.cancel':
   if type(params) is not dict or set(params)!={'contribution'} or not isinstance(params['contribution'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',params['contribution']):raise ValueError('Contribution identifier required')
   result=client.cancel_contribution(params['contribution'])
  elif method=='rewards.capabilities':
   if params!={}:raise ValueError('Empty parameters required')
   result={'requests_enabled':True,'payments_enabled':False}
  else:
   if method not in ('rewards.request','rewards.status') or type(params) is not dict or set(params)!={'receipt'} or not isinstance(params['receipt'],str) or not re.fullmatch('[a-f0-9]{32}',params['receipt']):raise ValueError('Receipt only required')
   result=client.reward(method.split('.')[1],params['receipt'])
  return dict(v=1,id=request['id'],ok=True,result=result)
 except Exception:return response
def main():
 client=Client()
 if sys.argv[1:]==['--check']:
  receipts={'u26-2T':'4d64df69e36b4efa8964286fb752633f','anno2-u26':'e765f876819d44cc9031e7cca2e8f04f'}
  client.reward('status',receipts[client.config['provider']])
  print(json.dumps(dict(passed=True,provider=client.config['provider'],credentials_exported=False,coordinator_route_verified=True)));return
 if os.environ.get('LISTEN_PID')!=str(os.getpid()) or os.environ.get('LISTEN_FDS')!='1' or os.environ.get('LISTEN_FDNAMES')!='reward-request':raise ValueError('Named activation socket required')
 listener=socket.socket(fileno=3)
 if listener.family!=socket.AF_UNIX or listener.getsockname()!=SOCKET or not listener.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN):raise ValueError('Wrong activation socket')
 stop=False
 def stopped(*_):
  nonlocal stop;stop=True
 signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped);listener.settimeout(.5)
 while not stop:
  try:c,_=listener.accept()
  except socket.timeout:continue
  with c:
   try:
    uid=peer_uid(c)
    if uid!=client.config['owner_uid']:continue
    r=dispatch(client,uid,frame(c));c.sendall((json.dumps(r)+'\n').encode())
   except (OSError,ValueError):pass
if __name__=='__main__':main()
