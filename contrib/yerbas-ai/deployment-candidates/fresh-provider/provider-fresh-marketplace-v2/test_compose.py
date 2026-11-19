import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from compose import compose
from guarded_writer import Writer, DIR_FLAGS


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.plan = compose(1000,1000,1100,1100,'/home/newowner','new-provider')

    def data(self, target):
        return bytes.fromhex(self.plan['files'][target]['content_hex'])

    def test_disabled_and_no_enrollment_copied(self):
        config=json.loads(self.data('/etc/yerbas-ai/broker.json'))
        self.assertIs(config['submissions_enabled'],False)
        self.assertIs(config['rentals_enabled'],False)
        self.assertFalse(self.plan['activate_services'])
        self.assertFalse(self.plan['installable'])
        self.assertEqual(json.loads(self.data('/etc/yerbas-ai/provider-direct-cupti-mode.json')),{'enabled':False})
        for name in self.plan['files']:
            self.assertFalse(name.endswith(('.sqlite3','.pem','enrollment.json','marketplace-buyer-v1.json')))

    def test_services_never_auto_enable(self):
        for name in self.plan['files']:
            if name.endswith(('.service','.socket')):
                text=self.data(name).decode()
                self.assertNotIn('[Install]',text)
                self.assertNotIn('WantedBy=',text)
        relay=self.data('/etc/systemd/system/yerbas-ai-reward-request.service').decode()
        self.assertIn('ConditionPathExists=/etc/yerbas-ai/marketplace-buyer-v1.json',relay)
        self.assertIn('IPAddressDeny=any',relay)

    def test_direct_execution_and_private_ownership(self):
        daemon=self.data('/opt/yerbas-ai/broker-v1/provider_broker_daemon.py')
        self.assertIn(b"POLICY=Path('/etc/yerbas-ai/provider-direct-cupti-v1.json')",daemon)
        for mode in ('provider','replay'):
            unit=self.data('/etc/systemd/system/yerbas-text-'+mode+'@.service').decode()
            self.assertIn('BindsTo=yerbas-provider-broker.service',unit)
            self.assertIn('provider-direct-cupti-v1/bootstrap.py',unit)
            self.assertEqual('--replay-only' in unit,mode=='replay')
        for name,entry in self.plan['files'].items():
            if name.startswith('/home/newowner/'):
                self.assertEqual((entry['uid'],entry['gid'],entry['mode']),(1000,1000,0o600))

    def test_invalid_identity_refused(self):
        for owner,provider,host in ((0,1100,'host'),(1000,1000,'host'),(1000,1100,'../host')):
            with self.assertRaises(ValueError):
                compose(owner,1000,provider,1100,'/home/newowner',host)

    def test_guarded_isolated_staging_and_imports(self):
        # Same guarded exclusive writer, but all ownership stays with this user.
        # This checks composition, not privileged installation or GPU acceptance.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            fd=os.open(root,DIR_FLAGS);writer=Writer(fd,os.getuid());os.close(fd)
            try:
                dirs=set()
                for name in self.plan['files']:
                    dirs.update(str(p).lstrip('/') for p in Path(name).parents if str(p)!='/')
                for name in sorted(dirs,key=lambda n:(n.count('/'),n)):
                    writer.mkdir(name,0o700)
                for name,entry in self.plan['files'].items():
                    writer.write(name.lstrip('/'),bytes.fromhex(entry['content_hex']),entry['sha256'],entry['mode'])
                name=next(iter(self.plan['files']));entry=self.plan['files'][name]
                with self.assertRaises(FileExistsError):
                    writer.write(name.lstrip('/'),bytes.fromhex(entry['content_hex']),entry['sha256'],entry['mode'])
                for name,entry in self.plan['files'].items():
                    self.assertEqual(hashlib.sha256((root/name.lstrip('/')).read_bytes()).hexdigest(),entry['sha256'])
                for relative,modules in (
                    ('opt/yerbas-ai/broker-v1',['provider_broker_daemon','provider_service_adapter','direct_policy']),
                    ('home/newowner/.local/share/yerbas-ai-control-v1/code',['wallet_agent','bound_control','marketplace_socket','request_status']),
                    ('opt/yerbas-ai/reward-requests-v1',['reward_daemon','marketplace_transport'])):
                    code='import sys;sys.path.insert(0,'+repr(str(root/relative))+');'+ ';'.join('import '+m for m in modules)
                    subprocess.run([sys.executable,'-I','-B','-c',code],check=True,capture_output=True,timeout=10)
            finally:
                writer.close()


if __name__=='__main__':unittest.main()
