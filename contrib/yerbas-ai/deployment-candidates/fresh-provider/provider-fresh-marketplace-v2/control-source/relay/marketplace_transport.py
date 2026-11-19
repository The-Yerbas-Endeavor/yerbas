"""Role-scoped marketplace relay; buyer secret never crosses the owner socket."""
import http.client,json,re
from reward_socket import trusted,unique,CA,CA_SHA,ORIGIN
PROVIDER_ACTIONS={'advertise','renew','pause','capacity','pendingwork','workassignment','acceptwork','releasework'}
ACTIONS=PROVIDER_ACTIONS|{'schedulework','browse','request','status','quote','acceptquote','order','withdraw','pool','summary','refundstatus','orderrecovery','refundpreview','refundconfirm','paidquote','deposit','fundingstatus','capabilities'}
class MarketplaceTransport:
 def __init__(self,client):
  self.client=client
  value=json.loads(trusted('/etc/yerbas-ai/marketplace-buyer-v1.json',True),object_pairs_hook=unique)
  if (set(value)!={'schema','buyer','token','origin','ca_sha256'} or type(value['schema']) is not int or value['schema']!=1
      or value['buyer']!=client.config['provider'] or value['origin']!=ORIGIN or value['ca_sha256']!=CA_SHA
      or not isinstance(value['token'],str) or not re.fullmatch('[A-Za-z0-9_-]{32,128}',value['token'])):
   raise ValueError('Invalid scoped buyer enrollment')
  if value['token']==client.credentials['token']:raise ValueError('Distinct buyer credential required')
  self.buyer=value
 def marketplace(self,action,body):
  if action not in ACTIONS or type(body) is not dict:raise ValueError('Unknown marketplace action')
  raw=json.dumps(body,allow_nan=False).encode()
  if len(raw)>7000:raise ValueError('Oversized marketplace request')
  token=self.client.credentials['token'] if action in PROVIDER_ACTIONS else self.buyer['token']
  connection=http.client.HTTPSConnection('127.0.0.1',19444,context=self.client.context,timeout=3)
  try:
   connection.request('POST','/v1/marketplace/'+action,raw,{'Content-Type':'application/json','Authorization':'Bearer '+token})
   response=connection.getresponse();data=response.read(7501)
   if response.status!=200 or response.getheader('Content-Type')!='application/json' or len(data)>7500:raise ValueError('Marketplace unavailable')
   value=json.loads(data,object_pairs_hook=unique)
   if type(value) is not dict:raise ValueError('Invalid marketplace reply')
   return value
  finally:connection.close()
