import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from control import handle


def request():
    return dict(schema=1, network='yerbas-private-reduced-collateral-testnet',
                quote='a'*32, assignment='b'*32, terms_sha256='c'*64,
                deposit_txid='d'*64, deposit_vout=0, maximum_base_units=101000,
                provider_reward_base_units=100000, slot='gpu-1', automatic_settlement=True)


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.launch=Mock(return_value=SimpleNamespace(pid=123))

    def test_duplicate_wallet_click_does_not_launch_again(self):
        self.assertTrue(handle(request(),self.root,self.launch)['started'])
        self.assertFalse(handle(request(),self.root,self.launch)['started'])
        self.assertEqual(self.launch.call_count,1)

    def test_lost_launch_reply_does_not_launch_again(self):
        self.launch.side_effect=OSError('Lost launch acknowledgment')
        with self.assertRaises(OSError):handle(request(),self.root,self.launch)
        self.assertFalse(handle(request(),self.root,self.launch)['started'])
        self.assertEqual(self.launch.call_count,1)

    def test_changed_deposit_rejected(self):
        handle(request(),self.root,self.launch)
        changed=request();changed['deposit_txid']='e'*64
        with self.assertRaises(ValueError):handle(changed,self.root,self.launch)
        self.assertEqual(self.launch.call_count,1)

    def test_unknown_fields_rejected_before_launch(self):
        r=request();r['command']='arbitrary'
        with self.assertRaises(ValueError):handle(r,self.root,self.launch)
        self.launch.assert_not_called()

    def test_symlink_order_directory_refused(self):
        (self.root/('a'*32)).symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):handle(request(),self.root,self.launch)
        self.launch.assert_not_called()

    def test_wallet_close_does_not_terminate_worker(self):
        handle(request(),self.root,self.launch)
        self.assertTrue(self.launch.call_args.kwargs['start_new_session'])
        self.assertTrue(self.launch.call_args.kwargs['close_fds'])


if __name__=='__main__':unittest.main()
