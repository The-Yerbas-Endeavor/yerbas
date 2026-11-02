import tempfile,unittest,sqlite3,concurrent.futures
from pathlib import Path
from payment_store import PaymentStore
from identity import PROFILE
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'payments';self.store=PaymentStore(self.path)
  self.a=dict(receipt='a'*32,provider='provider',address='r'+'A'*33,approved_gpu_ms=36000,approval_id='d'*32,identity_proof='b'*64)
  self.receipt=lambda key:dict(state='completed',provider='provider',artifact_sha256='c'*64,max_runtime_seconds=120,independently_confirmed=True,confirmation_sha256='e'*64,signed_verification_accepted=True,attestation_sha256='f'*64)
  self.identity=lambda key:dict(provider='provider',address=self.a['address'],profile=PROFILE)
 def tearDown(self):self.tmp.cleanup()
 def approve(self,a=None):return self.store.approve(a or self.a,self.receipt,self.identity)
 def draft(self,rate='1',identity=None):return self.store.draft([self.a['approval_id']],rate,self.receipt,identity or self.identity)
 def test_restart_retry_preserves_one_draft(self):
  self.approve();self.approve();first=self.draft();self.store=PaymentStore(self.path)
  self.assertEqual(first,self.draft());self.assertEqual(first['total_base_units'],1000000)
  with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0],1)
 def test_approval_conflicts_and_cross_draft_dedup(self):
  self.approve()
  for a in (dict(self.a,approved_gpu_ms=37000),dict(self.a,approval_id='e'*32)):
   with self.assertRaises(ValueError):self.approve(a)
  self.draft()
  with self.assertRaises(ValueError):self.draft('2')
  with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0],1)
 def test_no_implicit_approval(self):
  with self.assertRaises(ValueError):self.draft()
 def test_recheck_revoked_identity(self):
  self.approve()
  with self.assertRaises(ValueError):self.draft(identity=lambda _:None)
  with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM drafts').fetchone()[0],0)
 def test_concurrent_different_rate_only_one_wins(self):
  self.approve()
  def draft(rate):
   try:return self.draft(rate)['plan_sha256']
   except ValueError:return None
  with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(draft,['1','2']))
  self.assertEqual(sum(v is not None for v in results),1)
 def test_other_database_and_symlink_refused(self):
  other=Path(self.tmp.name)/'other'
  with sqlite3.connect(other) as db:db.execute('CREATE TABLE unrelated(x)')
  other.chmod(0o600)
  with self.assertRaises(ValueError):PaymentStore(other)
  link=Path(self.tmp.name)/'link';link.symlink_to(self.path)
  with self.assertRaises(OSError):PaymentStore(link)
if __name__=='__main__':unittest.main()
