import json,sqlite3,tempfile,unittest
from pathlib import Path
from payment_store import PaymentStore
from payment_review import review_row,saved_approvals
from identity import PROFILE
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'drafts'
  self.row=dict(id='a'*32,provider='anno2-u26',address='r'+'A'*33,proof='b'*64)
  self.record=dict(state='completed',provider='anno2-u26',artifact_sha256='c'*64,max_runtime_seconds=120,independently_confirmed=True,confirmation_sha256='e'*64,signed_verification_accepted=True,attestation_sha256='f'*64)
  self.a=dict(receipt=self.row['id'],provider=self.row['provider'],address=self.row['address'],approved_gpu_ms=36000,approval_id='d'*32,identity_proof=self.row['proof'])
  self.identity=lambda _:dict(provider=self.row['provider'],address=self.row['address'],profile=PROFILE)
 def tearDown(self):self.tmp.cleanup()
 def review(self,**kw):return review_row(self.row,self.record,kw.pop('identity',self.identity),rate='1',**kw)
 def test_missing_journal_is_read_only(self):
  with saved_approvals(self.path) as pair:self.assertEqual(pair,({},{}))
  self.assertFalse(self.path.exists());r=self.review();self.assertEqual(r['blockers'],['operator_gpu_time_approval_required']);self.assertIsNone(r['preview_amount_base_units'])
 def test_saved_approval_enables_preview_without_draft(self):
  store=PaymentStore(self.path);store.approve(self.a,lambda _:self.record,self.identity);before=self.path.read_bytes()
  with saved_approvals(self.path) as (a,d):r=self.review(approval=a[self.row['id']])
  self.assertTrue(r['reward_draft_ready']);self.assertEqual(r['preview_amount_base_units'],1000000);self.assertEqual(before,self.path.read_bytes());self.assertEqual(d,{})
 def test_drafted_receipt_not_ready_again(self):
  store=PaymentStore(self.path);store.approve(self.a,lambda _:self.record,self.identity);plan=store.draft([self.a['approval_id']],'1',lambda _:self.record,self.identity)
  with saved_approvals(self.path) as (a,d):r=self.review(approval=a[self.row['id']],draft=d[self.row['id']])
  self.assertFalse(r['reward_draft_ready']);self.assertEqual(r['existing_unsigned_draft'],plan['plan_sha256'])
 def test_draft_review_never_asserts_unsent(self):
  # A previously drafted receipt may already have been paid outside this reader.
  for kw in ({},dict(approval=self.a),dict(approval=self.a,draft='e'*64)):
   with self.subTest(kw=kw):
    r=self.review(**kw)
    self.assertIsNone(r['payment_sent'])
    self.assertEqual(r['payment_status'],'not_checked')
 def test_revocation_invalidates_approval(self):
  r=self.review(approval=self.a,identity=lambda _:None);self.assertFalse(r['reward_draft_ready']);self.assertIsNone(r['approved_gpu_ms'])
 def test_unsigned_verification_blocks(self):
  self.record['signed_verification_accepted']=False;r=self.review(approval=self.a);self.assertIn('accepted_signed_verification_required',r['blockers']);self.assertIsNone(r['preview_amount_base_units'])
 def test_unapproved_elapsed_not_used(self):
  self.record['elapsed_training_seconds']=6;r=self.review();self.assertIsNone(r['approved_gpu_ms']);self.assertFalse(r['reward_draft_ready'])
 def test_no_default_rate_authority(self):
  r=review_row(self.row,self.record,self.identity,approval=self.a);self.assertIn('explicit_reward_rate_required',r['blockers']);self.assertIsNone(r['preview_amount_base_units'])
 def test_changed_identity_proof(self):
  r=self.review(approval=dict(self.a,identity_proof='9'*64));self.assertFalse(r['reward_draft_ready'])
 def test_corrupted_approval_binding(self):
  store=PaymentStore(self.path);store.approve(self.a,lambda _:self.record,self.identity)
  with store.db() as db:db.execute('UPDATE approvals SET receipt=?',('0'*32,))
  with self.assertRaises(ValueError):
   with saved_approvals(self.path):pass
 def test_symlink_refused(self):
  PaymentStore(self.path);link=self.path.parent/'link';link.symlink_to(self.path)
  with self.assertRaises(ValueError):
   with saved_approvals(link):pass
if __name__=='__main__':unittest.main()
