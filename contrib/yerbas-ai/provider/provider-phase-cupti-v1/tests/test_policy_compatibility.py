import copy
import unittest
from direct_policy import PINS,LEGACY_PINS,verify_direct_files
from prepare_direct_policy import prepare
from provider_executor import verify_policy


class CompatibilityTests(unittest.TestCase):
    def old(self):
        root='/opt/yerbas-ai/provider-direct-cupti-v1'
        return dict(schema=3,measurement='direct-cupti-v1',provider_uid=1001,gpu='1',
            python='/opt/runtime/python',worker=root+'/text_gpu.py',dataset='/opt/corpus',
            credentials='/etc/provider.json',state='/var/lib/direct',locks=['/run/a','/run/b'],
            files={**{root+'/'+n:h for n,h in LEGACY_PINS.items()},**{'/opt/corpus/'+n:'a'*64 for n in ('manifest.json','train.jsonl','validation.jsonl')}},
            expected_identity=dict(runner='b'*64,dataset='c'*64,config='d'*64))

    def test_existing_policy_unchanged(self):
        old=self.old();saved=copy.deepcopy(old)
        new=prepare(old,'/opt/yerbas-ai/provider-phase-cupti-v1','/var/lib/phase')
        self.assertEqual(old,saved)
        self.assertEqual(verify_policy(old),saved)
        self.assertNotEqual(new['state'],old['state'])
        self.assertEqual(new['credentials'],old['credentials'])

    def test_old_policy_cannot_accept_new_worker_hash(self):
        old=self.old();old['files'][old['worker']]=PINS['text_gpu.py']
        with self.assertRaises(ValueError):verify_policy(old)

    def test_unreviewed_worker_path_rejected(self):
        with self.assertRaises(ValueError):verify_direct_files(dict(worker='/tmp/text_gpu.py',files={}))
