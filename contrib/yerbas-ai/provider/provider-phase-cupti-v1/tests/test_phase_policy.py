import copy
import unittest
from direct_policy import PINS
from prepare_direct_policy import prepare
from provider_executor import verify_policy,worker_config,validate_request

class Tests(unittest.TestCase):
 def setUp(self):
  self.old=dict(schema=1,provider_uid=1001,gpu='1',python='/opt/runtime/python',worker='/opt/old/text_gpu.py',dataset='/opt/corpus',credentials='/etc/provider.json',state='/var/lib/old',locks=['/run/a','/run/b'],files={'/opt/old/text_gpu.py':'a'*64,**{'/opt/corpus/'+n:'b'*64 for n in ('manifest.json','train.jsonl','validation.jsonl')},'/etc/ca.pem':'c'*64},expected_identity=dict(runner='d'*64,dataset='e'*64,config='f'*64))
  self.request=dict(run_id='a'*32,contribution='test-1')
 def candidate(self):return prepare(self.old,'/opt/yerbas-ai/provider-phase-cupti-v1','/var/lib/measured')
 def test_old_policy_and_config_unchanged(self):
  before=copy.deepcopy(self.old);verify_policy(self.old)
  self.assertNotIn('training_attribution',worker_config(self.old,{},self.request))
  self.candidate();self.assertEqual(before,self.old)
 def test_explicit_candidate_enables_attribution(self):
  policy=self.candidate();self.assertEqual(worker_config(policy,{},self.request)['collector_backend'],'direct-cupti-v1');self.assertEqual(policy['expected_identity'],self.old['expected_identity'])
 def test_all_dependencies_are_pinned(self):
  for name in PINS:
   with self.subTest(name=name):
    policy=self.candidate();del policy['files']['/opt/yerbas-ai/provider-phase-cupti-v1/'+name]
    with self.assertRaises(ValueError):verify_policy(policy)
 def test_changed_dependency_refused(self):
  policy=self.candidate();policy['files']['/opt/yerbas-ai/provider-phase-cupti-v1/profile_attempt.py']='0'*64
  with self.assertRaises(ValueError):verify_policy(policy)
 def test_owner_cannot_choose_profiling(self):
  with self.assertRaises(ValueError):validate_request(dict(self.request,measurement='training-attribution-v1'))
 def test_no_in_place_migration(self):
  for code,state in (('/opt/old','/var/lib/new'),('/opt/new','/var/lib/old'),('/opt/new','/opt/new/state'),('/opt/old/child','/var/lib/new'),('/opt/new','/var/lib/old/child')):
   with self.assertRaises(ValueError):prepare(self.old,code,state)
 def test_unknown_mode_refused(self):
  policy=self.candidate();policy['measurement']='automatic-rewards'
  with self.assertRaises(ValueError):verify_policy(policy)
 def test_replay_worker_in_allowlist(self):
  self.assertIn('/opt/yerbas-ai/provider-phase-cupti-v1/text_replay.py',self.candidate()['files'])
if __name__=='__main__':unittest.main()
