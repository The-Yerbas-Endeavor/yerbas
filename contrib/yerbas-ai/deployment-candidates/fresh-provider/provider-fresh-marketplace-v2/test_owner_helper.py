import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from install_phases import phases,digest

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'provider-fresh-host-candidate-v1'


class OwnerHelperTests(unittest.TestCase):
    def test_copied_helper_runs_without_source_checkout_imports(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);home=base/'home';home.mkdir(mode=0o700)
            (home/'.local').mkdir(mode=0o700)
            (home/'.local/share').mkdir(mode=0o700)
            tools=base/'tools';tools.mkdir()
            for name in ('guarded_writer.py','install_journal.py','reconcile_install.py'):
                shutil.copyfile(OLD/name,tools/name)
            for name in ('install_phases.py','owner_install_phase.py'):
                shutil.copyfile(ROOT/name,tools/name)
            uid,gid=os.getuid(),os.getgid()
            phase=phases(uid,gid,uid+10000,gid+10000,str(home),'fresh-provider')['phases']['owner']
            # Only ancestry checking is substituted: temporary homes do not have
            # root-owned /home ancestry. Main, stdin binding, writer, journal and
            # reconciliation execute in an isolated interpreter from copied files.
            code='''import os,runpy,sys
sys.path.insert(0,sys.argv[1])
m=runpy.run_path(sys.argv[1]+"/owner_install_phase.py")
m['main'].__globals__['open_home']=lambda home:os.open(home,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
sys.argv=['owner_install_phase.py','--home',sys.argv[2],'--sha256',sys.argv[3]]
m['main']()
'''
            args=[sys.executable,'-I','-B','-c',code,str(tools),str(home),digest(phase)]
            run=subprocess.run(args,input=json.dumps(phase),text=True,capture_output=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
            report=json.loads(run.stdout)
            self.assertTrue(report['passed']);self.assertFalse(report['services_started'])
            self.assertEqual(report['entries'],14)
            journal=home/'.local/share/yerbas-ai-install-v2/owner.jsonl'
            before=journal.read_bytes()
            replay=subprocess.run(args,input=json.dumps(phase),text=True,capture_output=True,timeout=20)
            self.assertNotEqual(replay.returncode,0)
            self.assertIn('Existing target preserved',replay.stderr)
            self.assertEqual(journal.read_bytes(),before)


if __name__=='__main__':unittest.main()
