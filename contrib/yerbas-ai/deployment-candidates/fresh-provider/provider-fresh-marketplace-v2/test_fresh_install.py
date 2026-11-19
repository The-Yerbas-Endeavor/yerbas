import copy
import unittest
from fresh_install import orchestrate


class OrchestrationTests(unittest.TestCase):
    def run_case(self, failed=None, raised=False):
        calls=[];reports=[]
        def operation(name):
            def run():
                calls.append(name)
                if failed==name and raised:raise OSError('injected failure')
                return {'passed':failed!=name}
            return run
        result=orchestrate({n:operation(n) for n in ('root','runtime','owner','units')},
                           lambda r:reports.append(copy.deepcopy(r)))
        return result,calls,reports

    def test_success_stays_disabled(self):
        result,calls,reports=self.run_case()
        self.assertTrue(result['passed'])
        self.assertEqual(calls,['root','runtime','owner','units'])
        self.assertEqual(result['phase'],'installed_disabled')
        for r in reports:
            for field in ('services_started','submissions_enabled','gpu_started','payments_sent','automatic_retry'):
                self.assertIs(r[field],False)

    def test_failure_stops_all_following_phases(self):
        names=['root','runtime','owner','units']
        for index,name in enumerate(names):
            for raised in (False,True):
                with self.subTest(name=name,raised=raised):
                    result,calls,reports=self.run_case(name,raised)
                    self.assertFalse(result['passed'])
                    self.assertTrue(result['inspection_required'])
                    self.assertEqual(calls,names[:index+1])
                    self.assertEqual(reports[-1],result)

    def test_journal_save_failure_prevents_next_operation(self):
        calls=[]
        def save(report):
            if report['phase']=='runtime_started':raise OSError('status disk failure')
        with self.assertRaises(OSError):
            orchestrate({n:lambda n=n:(calls.append(n) or {'passed':True})
                         for n in ('root','runtime','owner','units')},save)
        self.assertEqual(calls,['root'])


if __name__=='__main__':unittest.main()
