import itertools
import unittest
from phase_router import choose,command,PREVIOUS
class RoutingTests(unittest.TestCase):
    def test_all_retained_routes_survive_selector_changes(self):
        for index,enabled,replay in itertools.product(range(5),(False,True),(False,True)):
            retained=[i==index for i in range(5)]
            self.assertEqual(choose(retained,enabled,replay),'direct' if index==4 else 'previous')
    def test_fresh_jobs_follow_explicit_selector(self):
        for enabled in (False,True):
            self.assertEqual(choose([False]*5,enabled,False),'direct' if enabled else 'previous')
            with self.assertRaises(ValueError):choose([False]*5,enabled,True)
    def test_ambiguous_and_nonboolean_fail_closed(self):
        for retained in itertools.product((False,True),repeat=5):
            if sum(retained)>1:
                with self.assertRaises(ValueError):choose(retained,True,False)
        with self.assertRaises(ValueError):choose([0,False,False,False],True,False)
    def test_old_replay_uses_unchanged_migration_chain(self):
        args=command('previous','/python','/request',True)
        self.assertIn(PREVIOUS,args);self.assertIn('--replay-only',args)
        args=command('direct','/python','/request',True)
        self.assertTrue(args[2].endswith('provider_executor.py'));self.assertIn('--replay-only',args)
