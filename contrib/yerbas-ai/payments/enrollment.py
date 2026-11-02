"""Read-only identity gate for supervised coordinator job preparation."""
import json,os,sqlite3,stat
from pathlib import Path
from identity import APP_ID,PROFILE,GENESIS,canonical

def enrolled_identity(path,provider,origin,ca_sha256):
 path=Path(path)
 for item in (path.parent,path):
  info=item.lstat()
  if info.st_uid!=os.getuid() or info.st_mode&0o077 or (not stat.S_ISDIR(info.st_mode) if item==path.parent else not stat.S_ISREG(info.st_mode)):
   raise ValueError('Private registry required')
 db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
 try:
  db.execute('BEGIN')
  if db.execute('PRAGMA application_id').fetchone()[0]!=APP_ID:raise ValueError('Wrong identity registry')
  binding=dict(origin=origin,ca_sha256=ca_sha256,genesis=GENESIS,profile=PROFILE)
  if db.execute('SELECT value FROM config').fetchall()!=[(canonical(binding),)]:raise ValueError('Coordinator identity mismatch')
  row=db.execute('SELECT p.id,p.body FROM bindings b JOIN proofs p ON p.id=b.proof WHERE b.provider=? AND b.active=1',(provider,)).fetchone()
  if not row:raise ValueError('Provider needs active verified wallet identity')
  proof=json.loads(row[1])
  if proof['provider']!=provider or proof['profile']!=PROFILE or proof['proof_sha256']!=row[0]:raise ValueError('Registry identity mismatch')
  return proof
 finally:db.close()
