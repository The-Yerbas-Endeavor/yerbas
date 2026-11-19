"""Credential-free adapter using the existing root-authenticated local relay."""
ACTIONS={'browse','request','status','advertise','renew','schedulework','pendingwork','workassignment','acceptwork','releasework','pause','quote','acceptquote','order','withdraw','pool','capacity','summary','refundstatus','orderrecovery','refundpreview','refundconfirm','paidquote','deposit','fundingstatus','capabilities'}
class MarketplaceSocket:
 def __init__(self,client):self.client=client
 def marketplace(self,action,body):
  if action not in ACTIONS or type(body) is not dict:raise ValueError('Unknown marketplace action')
  return self.client.exchange('marketplace.'+action,body)
 def ready(self):
  try:
   result=self.marketplace('summary',{})
   return type(result) is dict and result.get('payments_enabled') is False and type(result.get('observed_at')) is int
  except Exception:return False
