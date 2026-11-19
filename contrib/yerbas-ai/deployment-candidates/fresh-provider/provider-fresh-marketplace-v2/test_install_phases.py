import copy
import os
from pathlib import Path
import tempfile
import unittest
from install_phases import digest, phases, preflight, stage
from install_journal import Journal, inspect
from reconcile_install import reconcile
from guarded_writer import DIR_FLAGS


class PhaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base/'filesystem'; self.root.mkdir(mode=0o700)
        self.fd = os.open(self.root, DIR_FLAGS)
        self.addCleanup(os.close,self.fd)
        self.addCleanup(self.temp.cleanup)
        self.bundle=phases(1000,1000,1100,1100,'/home/newowner','new-provider')

    def mapped(self, name):
        # Unprivileged rehearsal mapping, separately hashed; does not assert
        # that real root/provider/owner ownership has been installed.
        phase=copy.deepcopy(self.bundle['phases'][name])
        for kind in ('files','directories'):
            for entry in phase[kind].values():
                entry.update(uid=os.getuid(),gid=os.getgid())
        for target in (*phase['files'],*phase['directories']):
            for parent in reversed(Path(target).parents):
                if str(parent)=='.' or str(parent) in phase['directories']:continue
                if any(str(p) in phase['directories'] for p in parent.parents):continue
                (self.root/parent).mkdir(mode=0o700,parents=True,exist_ok=True)
        return phase

    def apply(self,phase,journal=None):
        path=self.base/'install.jsonl'
        j=journal or Journal(path,digest(phase))
        try:return stage(self.fd,phase,digest(phase),j,os.getuid())
        finally:j.close()

    def test_separate_root_owner_boundaries(self):
        root,owner=self.bundle['phases']['root'],self.bundle['phases']['owner']
        self.assertTrue(all(not n.startswith('home/') for n in root['files']))
        self.assertTrue(all(n.startswith('.local/share/yerbas-ai-control-v1/') for n in owner['files']))
        for name,phase in self.bundle['phases'].items():
            self.assertEqual(digest(phase),self.bundle['phase_sha256'][name])

    def test_root_phase_reconciles_and_detects_modified_content(self):
        phase=self.mapped('root');self.apply(phase)
        result=reconcile(self.root,self.base/'install.jsonl',digest(phase))
        self.assertTrue(result['passed'])
        first=next(iter(phase['files']))
        (self.root/first).write_bytes(b'changed')
        self.assertFalse(reconcile(self.root,self.base/'install.jsonl',digest(phase))['passed'])

    def test_owner_phase_reconciles(self):
        phase=self.mapped('owner');self.apply(phase)
        self.assertTrue(reconcile(self.root,self.base/'install.jsonl',digest(phase))['passed'])

    def test_collision_rejected_before_any_new_files(self):
        phase=self.mapped('root')
        target=self.root/'etc/yerbas-ai';target.mkdir(mode=0o700)
        before=set(self.root.rglob('*'))
        with self.assertRaisesRegex(ValueError,'Existing target preserved'):
            preflight(self.fd,phase,digest(phase),os.getuid())
        self.assertEqual(before,set(self.root.rglob('*')))

    def test_plan_change_rejected(self):
        phase=self.mapped('owner');expected=digest(phase)
        next(iter(phase['files'].values()))['mode']=0o644
        with self.assertRaisesRegex(ValueError,'reviewed plan'):
            preflight(self.fd,phase,expected,os.getuid())

    def test_interruption_retains_state_and_requires_inspection(self):
        phase=self.mapped('owner')
        class InterruptedJournal(Journal):
            def record(self,event):
                if event.get('kind')=='complete' and event['operation'].startswith('write:'):
                    raise OSError('simulated interrupted completion record')
                super().record(event)
        j=InterruptedJournal(self.base/'install.jsonl',digest(phase))
        with self.assertRaisesRegex(OSError,'simulated'):
            self.apply(phase,j)
        summary=inspect(self.base/'install.jsonl')
        self.assertTrue(summary['inspection_required'])
        self.assertFalse(summary['automatic_retry'])
        self.assertTrue(list(self.root.rglob('*.py')))
        self.assertFalse(reconcile(self.root,self.base/'install.jsonl',digest(phase))['passed'])
        with self.assertRaises(ValueError):
            preflight(self.fd,phase,digest(phase),os.getuid())


if __name__=='__main__':unittest.main()
