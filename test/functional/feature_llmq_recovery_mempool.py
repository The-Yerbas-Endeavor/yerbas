#!/usr/bin/env python3
"""Recovery duplicate admission, expiry eviction and continued mining."""
from feature_llmq_manual_recovery import ManualRecovery
from test_framework.messages import CTransaction, FromHex, msg_tx, msg_version
from test_framework.mininode import P2PInterface, network_thread_start
from test_framework.util import assert_equal, assert_raises_rpc_error, wait_until


class RecoveryMempool(ManualRecovery):
    def funded_record(self, payload):
        c = self.nodes[0]
        coin = next(u for u in c.listunspent(1) if u['spendable'] and u['amount'] > 2)
        inputs = [{'txid': coin['txid'], 'vout': coin['vout']}]
        tx = FromHex(CTransaction(), c.createrawtransaction(inputs, {c.getnewaddress(): 1}))
        tx.nVersion, tx.nType = 3, 10
        tx.vExtraPayload = bytes.fromhex(payload)
        funded = c.fundrawtransaction(tx.serialize().hex())['hex']
        signed = c.signrawtransaction(funded)
        assert signed['complete']
        return signed['hex']

    def run_test(self):
        c = self.nodes[0]
        self.mine(110)
        effective = (c.getblockcount() // 30 + 2) * 30
        payload = c.quorum('recoveryrequest', effective, 0, 2)['payload']
        txid = c.sendrawtransaction(self.funded_record(payload))
        duplicate = self.funded_record(payload)
        assert_raises_rpc_error(-26, 'recovery-pending-duplicate', c.sendrawtransaction, duplicate)
        self.log.info('Distinct fee-paying duplicate authorization rejected by mempool policy')
        # Keep the valid request out of local templates until its signed deadline.
        c.prioritisetransaction(txid, -1000000000)
        self.mine(effective - c.getblockcount())
        assert txid not in c.getrawmempool()
        assert not c.quorum('recoverystate')['active']
        assert_equal(c.quorum('recovery', 'status')['status'], 'off')
        assert_raises_rpc_error(-26, 'recovery-window', c.sendrawtransaction, duplicate)
        expired_relay = self.funded_record(payload)
        peer_ids = {p['id'] for p in c.getpeerinfo()}
        peer = c.add_p2p_connection(P2PInterface(), send_version=False)
        network_thread_start()
        wait_until(lambda: peer.is_connected)
        version = msg_version()
        version.nVersion = 70224
        peer.send_message(version)
        peer.wait_for_verack()
        peer_id = next(p['id'] for p in c.getpeerinfo() if p['id'] not in peer_ids)
        peer.send_message(msg_tx(FromHex(CTransaction(), expired_relay)))
        peer.sync_with_ping()
        assert_equal(next(p['banscore'] for p in c.getpeerinfo() if p['id'] == peer_id), 0)
        self.log.info('Peer relaying a now-expired authorization is not punished for a tip-context mismatch')

        anchor = c.getbestblockhash()
        response = c.quorum('recovery', 'on')
        assert response['submitted']
        self.mine(1)
        records = [tx for tx in c.getblock(c.getbestblockhash(), 2)['tx'] if tx['type'] == 10]
        assert_equal(len(records), 1)
        assert_equal(records[0]['txid'], response['txid'])
        self.mine(1)
        c.invalidateblock(anchor)
        assert response['txid'] not in c.getrawmempool()
        assert not c.quorum('recoverystate')['active']
        c.reconsiderblock(anchor)
        self.mine(1)
        self.log.info('Expiry eviction, replacement mining, and orphan-anchor cleanup across reorg passed')


if __name__ == '__main__':
    RecoveryMempool().main()
