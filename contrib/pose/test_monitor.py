#!/usr/bin/env python3
import unittest
import subprocess
from unittest.mock import patch
from monitor import complete, responded, usable_peers, maybe_approve, probe, RPC


class MonitorTests(unittest.TestCase):
    def test_cli_unquoted_string_results(self):
        rpc = RPC("yerbas-cli", ["-regtest"])
        for command, text, expected in [("getblockhash", "ab" * 32, "ab" * 32),
                                        ("getblockhash", "12" * 32, "12" * 32),
                                        ("getblockcount", "30\n", 30),
                                        ("pose", '{"active":true}', {"active": True}),
                                        ("ping", "", None)]:
            with patch("monitor.subprocess.run", return_value=subprocess.CompletedProcess([], 0, text, "")):
                self.assertEqual(rpc(command), expected)

    def test_authenticated_fresh_outbound_response(self):
        peer = dict(inbound=False, addr="1.2.3.4:15420", verified_proregtx_hash="target", lastrecv=101)
        self.assertTrue(responded(peer, "target", "1.2.3.4:15420", 100))
        for change in [dict(inbound=True), dict(addr="other"), dict(verified_proregtx_hash="wrong"), dict(lastrecv=99)]:
            self.assertFalse(responded(dict(peer, **change), "target", "1.2.3.4:15420", 100))

    def test_probe_requires_new_bytes_not_same_second_old_traffic(self):
        peers = [dict(id=i, inbound=False, version=70200, addr="endpoint",
                      verified_proregtx_hash="target", lastrecv=100, bytesrecv=100) for i in range(3)]
        for count, expected in [(100, False), (101, True)]:
            reads = 0
            def rpc(*args):
                nonlocal reads
                if args[0] == "getblockchaininfo": return {"initialblockdownload": False}
                if args[0] == "getpeerinfo":
                    reads += 1
                    return peers if reads == 1 else [dict(p, bytesrecv=count) for p in peers]
                return None
            with patch("monitor.time.time", return_value=100), patch("monitor.time.monotonic", side_effect=[0, 0, 30]), patch("monitor.time.sleep"):
                self.assertIs(probe(rpc, "target", "endpoint", 20), expected)

    def test_inbound_duplicate_makes_probe_inconclusive(self):
        peers = [dict(id=i, inbound=False, version=70200) for i in range(3)]
        peers.append(dict(id=4, inbound=True, verified_proregtx_hash="target"))
        calls = []
        def rpc(*args):
            calls.append(args)
            return {"initialblockdownload": False} if args[0] == "getblockchaininfo" else peers
        self.assertIsNone(probe(rpc, "target", "endpoint", 20))
        self.assertNotIn(("addnode", "endpoint", "onetry"), calls)

    def test_disconnected_monitor_cannot_report(self):
        peers = [dict(inbound=False, version=70200)]
        self.assertFalse(usable_peers(peers))
        self.assertTrue(usable_peers(peers * 3))
        self.assertFalse(usable_peers([dict(inbound=True, version=70200)] * 3))

    def test_repeated_failures_only(self):
        state = ("service", "key", 1, -1)
        samples = [dict(height=h, identity=state, reachable=False) for h in [10, 20, 30]]
        self.assertTrue(complete(samples, 30, state))
        self.assertFalse(complete(samples[:2], 30, state))
        for change in [dict(reachable=True), dict(reachable=None), dict(height=19), dict(identity=("changed",))]:
            altered = [dict(s) for s in samples]
            altered[1].update(change)
            self.assertFalse(complete(altered, 30, state))


    def test_validator_requires_own_current_failure_and_matching_chain(self):
        state = ("endpoint", "key", 1, -1)
        calls = []
        def rpc(*args):
            calls.append(args)
            if args[0] == "protx":
                return {"state": dict(service="endpoint", pubKeyOperator="key", registeredHeight=1, PoSeRevivedHeight=-1)}
            if args[0] == "getblockhash": return "anchor"
            return True
        pending = (30, state, [(30, "anchor")], "request")
        for result in [True, None]:
            with patch("monitor.probe", return_value=result):
                calls.clear()
                self.assertEqual(maybe_approve(rpc, "target", pending, 30, 20), "discarded")
                self.assertNotIn(("pose", "approve", "request"), calls)
        with patch("monitor.probe", return_value=False):
            calls.clear()
            self.assertEqual(maybe_approve(rpc, "target", pending, 30, 20), "share_requested")
            self.assertIn(("pose", "approve", "request"), calls)
            for invalid in [(30, state, [(30, "fork")], "request"), (30, ("new",), [(30, "anchor")], "request")]:
                calls.clear()
                self.assertEqual(maybe_approve(rpc, "target", invalid, 30, 20), "discarded")
                self.assertNotIn(("pose", "approve", "request"), calls)
            calls.clear()
            self.assertEqual(maybe_approve(rpc, "target", pending, 151, 20), "discarded")
            self.assertNotIn(("pose", "approve", "request"), calls)
            def no_quorum(*args):
                if args[0] == "pose": raise subprocess.CalledProcessError(1, "yerbas-cli")
                return rpc(*args)
            self.assertEqual(maybe_approve(no_quorum, "target", pending, 30, 20), "pending")


if __name__ == "__main__":
    unittest.main()
