#!/usr/bin/env python3
"""Manual signed ON/OFF history: real DKG, PoSe, replay and reindex."""
import sys, importlib.util, os, hashlib, json
from pathlib import Path
functional = Path(__file__).resolve().parent
sys.path.insert(0, str(functional))
spec = importlib.util.spec_from_file_location('pose', functional / 'llmq-lowparams-pose.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from test_framework.key import CECKey
from test_framework.util import connect_nodes, assert_equal, assert_raises_rpc_error, wait_until, force_finish_mnsync, p2p_port

class ManualRecovery(module.LowLLMQPoSeTest):

    def set_test_params(self):
        super().set_test_params()
        self.num_nodes = 6
        self.extra_args = [['-llmqtestfixture', '-llmqrecoverytest', '-assumevalid=0', '-debug=llmq-dkg'] for _ in range(6)]

    def setup_chain(self):
        self.recovery_start = 120
        self.recovery_end = 1000000
        self.collateral = 10
        super(module.LowLLMQPoSeTest, self).setup_chain()
        secret = os.urandom(32)
        key = CECKey()
        key.set_secretbytes(secret)

        def base58(payload):
            data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
            number, text = (int.from_bytes(data, 'big'), '')
            alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
            while number:
                number, remainder = divmod(number, 58)
                text = alphabet[remainder] + text
            return '1' * (len(data) - len(data.lstrip(b'\x00'))) + text
        authority = base58(bytes([140]) + hashlib.new('ripemd160', hashlib.sha256(key.get_pubkey()).digest()).digest())
        private = base58(bytes([239]) + secret)
        for i in range(self.num_nodes):
            config = Path(self.options.tmpdir) / ('node%d' % i) / 'yerbas.conf'
            config.chmod(384)
            with config.open('a') as output:
                output.write('sporkaddr=' + authority + '\n')
                if i == 0:
                    output.write('sporkkey=' + private + '\n')

    def setup_network(self):
        self.options.chain_recovery = True
        self.setup_nodes()
        self.stop_node(4)
        self.stop_node(5)
        for i in range(1, 4):
            connect_nodes(self.nodes[0], i)
        self.sync_blocks(self.nodes[:4], timeout=30)

    def record(self, active):
        controller = self.nodes[0]
        action, opposite = ('on', 'off') if active else ('off', 'on')
        response = controller.quorum('recovery', action)
        assert response['submitted']
        assert response['fee'] > 0
        assert_equal(-controller.gettransaction(response['txid'])['fee'], response['fee'])
        assert_equal(response['last_inclusion_height'], response['effective_height'] - 1)
        assert_equal(response['active'], not active)
        assert response['pending_authorization'] != response['authorization']
        assert_equal(response['status'], 'awaiting_confirmation')
        repeat = controller.quorum('recovery', action)
        assert not repeat['submitted']
        assert_equal(repeat['txid'], response['txid'])
        assert_equal(repeat['pending_authorization'], response['pending_authorization'])
        assert_equal(controller.quorum('recovery', 'status')['txid'], response['txid'])
        assert_raises_rpc_error(-8, 'awaiting confirmation', controller.quorum, 'recovery', opposite)
        self.mine(1)
        scheduled = controller.quorum('recovery', 'status')
        assert_equal(scheduled['status'], 'scheduled')
        assert_equal(scheduled['active'], not active)
        assert_equal(scheduled['authorization'], response['pending_authorization'])
        assert_equal(scheduled['effective_height'], response['effective_height'])
        assert not controller.quorum('recovery', action)['submitted']
        assert_raises_rpc_error(-8, 'awaiting its effective height', controller.quorum, 'recovery', opposite)
        return controller.getbestblockhash(), response['effective_height']

    def observer(self, i):
        self.start_node(i)
        self.nodes[i].setmocktime(self.mocktime)
        connect_nodes(self.nodes[i], 0)
        self.check(i)

    def check(self, i):
        self.sync_blocks([self.nodes[0], self.nodes[i]], timeout=60)
        assert_equal(self.nodes[i].quorum('recoverystate'), self.nodes[0].quorum('recoverystate'))
        for h in self.registrations:
            assert_equal(self.nodes[i].protx('info', h)['state'], self.nodes[0].protx('info', h)['state'])

    def register_operators(self):
        c = self.nodes[0]
        self.registrations = []
        keys = []
        for i in range(1, 4):
            k = c.bls('generate')
            keys.append(k['secret'])
            f = c.getnewaddress()
            c.sendtoaddress(f, 11)
            self.mine(1)
            self.registrations.append(c.protx('register_fund', f, 10, '127.0.0.1:%d' % p2p_port(i), c.getnewaddress(), k['public'], c.getnewaddress(), 0, c.getnewaddress(), f))
            self.mine(2)
        for i in range(1, 4):
            self.restart_node(i, self.extra_args[i] + ['-smartnodeblsprivkey=' + keys[i - 1]])
            self.nodes[i].setmocktime(self.mocktime)
            connect_nodes(self.nodes[i], 0)
            wait_until(lambda: any(('testnode0' in peer['subver'] and peer['version'] != 0 for peer in self.nodes[i].getpeerinfo())), timeout=30)
        for n in self.nodes[:4]:
            force_finish_mnsync(n)
        self.sync_blocks(self.nodes[:4], timeout=30)
        for i in range(1, 4):
            for j in range(1, 4):
                if i != j:
                    connect_nodes(self.nodes[i], j)
        wait_until(lambda: all((sum((bool(p.get('verified_proregtx_hash')) for p in self.nodes[i].getpeerinfo())) >= 2 for i in range(1, 4))), timeout=45)

    def run_test(self):
        c = self.nodes[0]
        assert_equal(c.quorum('recovery', 'status')['status'], 'off')
        assert not c.quorum('recovery', 'off')['submitted']
        assert_raises_rpc_error(-8, 'Expected on, off, or status', c.quorum, 'recovery', 'invalid')
        assert_raises_rpc_error(-8, 'No spork signing key configured', self.nodes[1].quorum, 'recovery', 'on')
        assert_raises_rpc_error(-4, 'Insufficient funds', c.quorum, 'recovery', 'on')
        assert_equal(c.getrawmempool(), [])
        c.spork('SPORK_21_LOW_LLMQ_PARAMS', 0)
        c.spork('SPORK_17_QUORUM_DKG_ENABLED', 0)
        wait_until(lambda: all((n.spork('active')['SPORK_17_QUORUM_DKG_ENABLED'] for n in self.nodes[:4])))
        self.mine(110)
        # A gossip spork alone cannot authorize recorded-history LOW_LLMQ.
        assert not c.quorum('recoverystate')['active']
        _, on_height = self.record(True)
        self.register_operators()
        healthy = self.dkg(3)
        self.stop_node(3)
        self.online = [0, 1, 2]
        for _ in range(4):
            self.dkg(2)
            if c.protx('info', self.registrations[2])['state']['PoSeBanHeight'] >= 0:
                break
        assert c.protx('info', self.registrations[2])['state']['PoSeBanHeight'] >= 0
        self.dkg(2)
        assert c.getblockcount() > on_height + 60 and c.quorum('recoverystate')['active']
        self.log.info('Manual ON remains active beyond the old automatic expiry; real DKG and PoSe pass')
        self.observer(4)
        self.stop_node(4)
        self.log.info('Fresh signed-history replay while ON passed')
        boundary, off = self.record(False)
        self.mine(off - c.getblockcount() - 1)
        assert c.quorum('recoverystate')['active']
        self.mine(1)
        assert not c.quorum('recoverystate')['active']
        assert_equal(c.quorum('recovery', 'status')['status'], 'off')
        assert not c.quorum('recovery', 'off')['submitted']
        for i in (1, 2):
            assert not self.nodes[i].quorum('sign', 1, '22' * 32, '33' * 32)
        self.log.info('Manual OFF retires old low quorums for signing')
        normal = self.dkg(2)
        assert all((m['valid'] for m in normal['members']))
        self.log.info('Normal quorum formation after manual OFF passed')
        self.bump_mocktime(2, nodes=[self.nodes[i] for i in self.online])
        c.spork('SPORK_21_LOW_LLMQ_PARAMS', 4070908800)
        self.observer(5)
        self.log.info('Fresh signed-history replay after manual OFF passed')
        self.restart_node(5, self.extra_args[5] + ['-reindex'])
        self.nodes[5].setmocktime(self.mocktime)
        connect_nodes(self.nodes[5], 0)
        self.check(5)
        self.log.info('Full reindex after manual OFF passed')
        self.nodes[5].setnetworkactive(False)
        self.nodes[5].invalidateblock(boundary)
        assert self.nodes[5].quorum('recoverystate')['active']
        self.nodes[5].reconsiderblock(boundary)
        self.check(5)
        self.log.info('OFF-record rollback and reconsider preserve historical state')
        Path(self.options.tmpdir, 'manual-recovery-result.json').write_text(json.dumps({'height': c.getblockcount(), 'on_replay': True, 'off_replay': True, 'off_reindex': True, 'off_rollback': True, 'no_automatic_expiry': True, 'normal_quorum_after_off': True, 'old_low_signing_retired': True}, indent=2))
if __name__ == '__main__':
    ManualRecovery().main()
