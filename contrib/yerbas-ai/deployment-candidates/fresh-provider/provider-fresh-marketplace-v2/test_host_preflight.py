import copy
import types
import unittest
from unittest.mock import patch
import host_preflight as hp


class HostPreflightTests(unittest.TestCase):
    def setUp(self):
        self.owner=types.SimpleNamespace(pw_uid=1000,pw_gid=1000,pw_name='owner',pw_dir='/home/owner')
        self.provider=types.SimpleNamespace(pw_uid=1100,pw_gid=1100,pw_name='yerbas-provider',pw_shell='/usr/sbin/nologin')
        self.og=types.SimpleNamespace(gr_gid=1000,gr_mem=[])
        self.pg=types.SimpleNamespace(gr_gid=1100,gr_mem=[])

    def test_offline_refuses_live_manager(self):
        with patch.object(hp.Path,'exists',return_value=True),patch.object(hp.subprocess,'run') as run:
            with self.assertRaises(ValueError):hp.service_inventory(True)
            run.assert_not_called()

    def test_offline_inventory_uses_real_disk_units(self):
        with patch.object(hp.Path,'exists',return_value=False),patch.object(hp.Path,'read_text',return_value='python3'),patch.object(hp.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='',stderr='')) as run:
            hp.service_inventory(True)
            self.assertEqual(run.call_args.args[0][:3],['/usr/bin/systemctl','--root=/','list-unit-files'])

    def test_separate_accounts(self):
        hp.identity(self.owner,self.provider,self.og,self.pg)

    def test_root_same_uid_or_group_refused(self):
        for key,value in (('pw_uid',0),('pw_uid',1000),('pw_gid',1000)):
            provider=copy.copy(self.provider);setattr(provider,key,value)
            with self.assertRaises(ValueError):hp.identity(self.owner,provider,self.og,self.pg)

    def test_interactive_provider_refused(self):
        self.provider.pw_shell='/bin/bash'
        with self.assertRaisesRegex(ValueError,'non-login'):
            hp.identity(self.owner,self.provider,self.og,self.pg)

    def test_cross_group_membership_refused(self):
        self.pg.gr_mem=['owner']
        with self.assertRaisesRegex(ValueError,'supplemental'):
            hp.identity(self.owner,self.provider,self.og,self.pg)

    def test_empty_systemd_inventory_variants(self):
        result=types.SimpleNamespace(returncode=1,stdout='',stderr='')
        hp.inventory_empty('list-unit-files',result)
        with self.assertRaises(ValueError):hp.inventory_empty('list-units',result)
        result.returncode=0
        hp.inventory_empty('list-units',result)

    def test_inventory_errors_and_existing_units_refused(self):
        for code,out,err in ((0,'yerbas-provider-broker.service disabled',''),
                             (0,'','warning'),(1,'','bus unavailable')):
            with self.assertRaises(ValueError):
                hp.inventory_empty('list-unit-files',types.SimpleNamespace(returncode=code,stdout=out,stderr=err))

    def test_existing_host_stops_before_systemd_or_wheel_scan(self):
        with patch.object(hp.pwd,'getpwnam',side_effect=[self.owner,self.provider]), \
             patch.object(hp.grp,'getgrgid',side_effect=[self.og,self.pg]), \
             patch.object(hp.os.path,'lexists',return_value=True), \
             patch.object(hp.subprocess,'run') as run,patch.object(hp,'inspect_wheels') as wheels:
            with self.assertRaisesRegex(ValueError,'Existing installation preserved'):
                hp.check('owner','unused')
            run.assert_not_called();wheels.assert_not_called()


if __name__=='__main__':unittest.main()
