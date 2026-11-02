"""Wallet ownership registry; operator binding, no signing or payment."""
import hashlib,ipaddress,json,os,re,secrets,sqlite3,stat,time
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit
APP_ID=1498698310
GENESIS='e3a4fabed29dfc45e9aebe696453545ee2e198bae150e4c115fcc80ef3298554'
PROFILE='yerbas-private-reduced-collateral-testnet'
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True)
def message(challenge):
 return 'Yerbas AI provider identity v1\nIdentity proof only; does not authorize payments or spending.\n'+canonical(challenge)
class IdentityStore:
 def __init__(self,path,origin,ca_sha256,clock=time.time):
  self.path=Path(path);self.clock=clock
  parsed=urlsplit(origin)
  if parsed.scheme!='https' or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:raise ValueError('Canonical private HTTPS origin required')
  ip=ipaddress.ip_address(parsed.hostname)
  if ip.version!=4 or not any(ip in ipaddress.ip_network(n) for n in ('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):raise ValueError('Private origin required')
  if not parsed.port or not 1024<=parsed.port<=65535 or not re.fullmatch('[a-f0-9]{64}',ca_sha256):raise ValueError('Invalid coordinator identity')
  self.binding={'origin':origin,'ca_sha256':ca_sha256,'genesis':GENESIS,'profile':PROFILE}
  info=self.path.parent.lstat()
  if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private owner directory required')
  fd=os.open(self.path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
  try:
   info=os.fstat(fd)
   if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('Private identity database required')
  finally:os.close(fd)
  with self.db() as db:
   app=db.execute('PRAGMA application_id').fetchone()[0];tables=db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
   if app!=APP_ID and (app!=0 or tables):raise ValueError('Separate identity database required')
   db.execute('CREATE TABLE IF NOT EXISTS config(value TEXT NOT NULL)')
   rows=db.execute('SELECT value FROM config').fetchall()
   if not rows:db.execute('INSERT INTO config VALUES(?)',(canonical(self.binding),))
   elif rows!=[(canonical(self.binding),)]:raise ValueError('Coordinator binding differs')
   db.execute('CREATE TABLE IF NOT EXISTS challenges(nonce TEXT PRIMARY KEY,body TEXT NOT NULL,used INTEGER NOT NULL DEFAULT 0)')
   db.execute('CREATE TABLE IF NOT EXISTS proofs(id TEXT PRIMARY KEY,body TEXT NOT NULL,signature TEXT NOT NULL,verified_at INTEGER NOT NULL)')
   db.execute('CREATE TABLE IF NOT EXISTS bindings(provider TEXT PRIMARY KEY,proof TEXT NOT NULL,active INTEGER NOT NULL,updated_at INTEGER NOT NULL)')
   db.execute(f'PRAGMA application_id={APP_ID}')
 @contextmanager
 def db(self):
  db=sqlite3.connect(self.path,timeout=5)
  try:
   with db:yield db
  finally:db.close()
 def issue(self,provider,address):
  if not re.fullmatch('[A-Za-z0-9_-]{1,64}',provider) or not re.fullmatch('[1-9A-HJ-NP-Za-km-z]{26,50}',address):raise ValueError('Invalid provider or address')
  now=int(self.clock());challenge=dict(schema=1,purpose='provider-identity',provider=provider,address=address,nonce=secrets.token_hex(32),issued_at=now,expires_at=now+300,**self.binding)
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   if db.execute('SELECT count(*) FROM challenges').fetchone()[0]>=10000:raise ValueError('Identity challenge capacity reached')
   db.execute('INSERT INTO challenges(nonce,body) VALUES(?,?)',(challenge['nonce'],canonical(challenge)))
  return challenge
 def redeem(self,nonce,signature,verify):
  if not re.fullmatch('[a-f0-9]{64}',nonce) or not isinstance(signature,str) or not 1<=len(signature)<=256:raise ValueError('Invalid proof')
  with self.db() as db:row=db.execute('SELECT body,used FROM challenges WHERE nonce=?',(nonce,)).fetchone()
  if not row or row[1]:raise ValueError('Unknown or consumed challenge')
  challenge=json.loads(row[0]);now=self.clock()
  if not challenge['issued_at']<=now<challenge['expires_at']:raise ValueError('Expired challenge or clock regression')
  # Integrator must call this network's Yerbas verifymessage RPC, never trust a
  # client-supplied verification result. Signing belongs in the owner's wallet.
  if verify(challenge['address'],signature,message(challenge)) is not True:raise ValueError('Signature rejected')
  proof={'provider':challenge['provider'],'address':challenge['address'],'profile':PROFILE,'proof_sha256':hashlib.sha256(message(challenge).encode()).hexdigest(),'payments_authorized':False}
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');now=self.clock()
   if not challenge['issued_at']<=now<challenge['expires_at']:raise ValueError('Proof expired during verification')
   if db.execute('UPDATE challenges SET used=1 WHERE nonce=? AND used=0',(nonce,)).rowcount!=1:raise ValueError('Challenge already consumed')
   db.execute('INSERT INTO proofs VALUES(?,?,?,?)',(proof['proof_sha256'],canonical(proof),signature,int(now)))
  return proof
 def bind(self,provider,proof_id,registered_provider):
  # Operator-only API. Caller must check authoritative coordinator enrollment;
  # a provider cannot select another provider name through a public endpoint.
  if registered_provider(provider) is not True:raise ValueError('Enabled coordinator provider required')
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   row=db.execute('SELECT body FROM proofs WHERE id=?',(proof_id,)).fetchone()
   if not row or json.loads(row[0])['provider']!=provider:raise ValueError('Verified matching proof required')
   old=db.execute('SELECT proof,active FROM bindings WHERE provider=?',(provider,)).fetchone()
   if old:
    if old!=(proof_id,1):raise ValueError('Existing identity preserved; rotation requires separate review')
   else:db.execute('INSERT INTO bindings VALUES(?,?,1,?)',(provider,proof_id,int(self.clock())))
  return self.lookup(proof_id)
 def lookup(self,proof_id):
  with self.db() as db:
   row=db.execute('SELECT p.body FROM proofs p JOIN bindings b ON b.proof=p.id WHERE p.id=? AND b.active=1',(proof_id,)).fetchone()
  return json.loads(row[0]) if row else None
 def provider_identity(self,provider):
  with self.db() as db:
   row=db.execute('SELECT proof FROM bindings WHERE provider=? AND active=1',(provider,)).fetchone()
  return self.lookup(row[0]) if row else None
 def revoke_binding(self,provider):
  with self.db() as db:
   if db.execute('UPDATE bindings SET active=0,updated_at=? WHERE provider=?',(int(self.clock()),provider)).rowcount!=1:raise ValueError('Unknown binding')
