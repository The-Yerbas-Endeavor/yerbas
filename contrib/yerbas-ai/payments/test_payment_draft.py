import copy,unittest
from payment_draft import build_draft,rate_units
from identity import PROFILE
class Tests(unittest.TestCase):
 def setUp(self):
  self.receipt='a'*32;self.proof='b'*64;self.address='r'+'A'*33
  self.receipts={self.receipt:dict(state='completed',provider='provider',artifact_sha256='c'*64,max_runtime_seconds=120,independently_confirmed=True,confirmation_sha256='e'*64,signed_verification_accepted=True,attestation_sha256='f'*64)}
  self.approval=dict(receipt=self.receipt,provider='provider',address=self.address,approved_gpu_ms=36000,approval_id='d'*32,identity_proof=self.proof)
  self.lookup=lambda key:dict(provider='provider',address=self.address,profile=PROFILE) if key==self.proof else None
 def build(self,approvals=None,rate='1'):return build_draft(self.receipts,approvals or [self.approval],rate,self.lookup)
 def test_exact_integer_rate_and_no_spending(self):
  p=self.build();self.assertEqual(p['total_base_units'],1000000)
  self.assertFalse(p['spending_authorized']);self.assertFalse(p['transaction_created']);self.assertFalse(p['simulated_credits_converted'])
  self.assertEqual(p,self.build())
 def test_unconfirmed_result_cannot_earn_draft(self):
  for change in ({'independently_confirmed':False},{'confirmation_sha256':None}):
   before=self.receipts[self.receipt].copy();self.receipts[self.receipt].update(change)
   with self.assertRaisesRegex(ValueError,'confirmation required'):self.build()
   self.receipts[self.receipt]=before
 def test_unsigned_result_cannot_earn_draft(self):
  for change in ({'signed_verification_accepted':False},{'attestation_sha256':None}):
   before=self.receipts[self.receipt].copy();self.receipts[self.receipt].update(change)
   with self.assertRaisesRegex(ValueError,'signed contribution verification required'):self.build()
   self.receipts[self.receipt]=before
 def test_duplicate_receipt_rejected(self):
  with self.assertRaises(ValueError):self.build([self.approval,self.approval])
 def test_cancelled_or_wrong_provider_receipt_rejected(self):
  for change in ({'state':'cancelled'},{'provider':'other'}):
   old=self.receipts[self.receipt].copy();self.receipts[self.receipt].update(change)
   with self.assertRaises(ValueError):self.build()
   self.receipts[self.receipt]=old
 def test_unapproved_time_or_excess_bound_rejected(self):
  for ms in (0,-1,120001,True,5.5):
   a=dict(self.approval,approved_gpu_ms=ms)
   with self.assertRaises(ValueError):self.build([a])
 def test_identity_binding_required(self):
  for change in ({'address':'r'+'B'*33},{'identity_proof':'f'*64}):
   with self.assertRaises(ValueError):self.build([dict(self.approval,**change)])
 def test_rate_precision_and_rounding(self):
  for rate in ('0','-1','NaN','1e3','0.000000001'):
   with self.assertRaises(ValueError):rate_units(rate)
  self.assertEqual(self.build(rate='0.00000001')['total_base_units'],0)
 def test_order_independent_plan_and_two_receipts(self):
  other='e'*32;self.receipts[other]=self.receipts[self.receipt].copy();a=dict(self.approval,receipt=other,approval_id='f'*32)
  self.assertEqual(self.build([a,self.approval]),self.build([self.approval,a]))
  self.assertEqual(self.build([a,self.approval])['total_base_units'],2000000)
if __name__=='__main__':unittest.main(verbosity=2)
