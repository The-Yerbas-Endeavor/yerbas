#!/usr/bin/env python3
"""Check that native drain validation cannot silently use the workaround."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dkg_network_test import disable_and_drain


class PeerNode:
    def __init__(self, clears_itself=False):
        self.data = SimpleNamespace(name='test-node')
        self.active = True
        self.peers = [{'id': 7}]
        self.clears_itself = clears_itself
        self.disconnects = 0

    def rpc(self, method, *args):
        if method == 'setnetworkactive':
            self.active = args[0]
        elif method == 'getnetworkinfo':
            return {'networkactive': self.active}
        elif method == 'getpeerinfo':
            peers = self.peers[:]
            if self.clears_itself:
                self.peers = []
            return peers
        elif method == 'getconnectioncount':
            return len(self.peers)
        elif method == 'disconnectnode':
            self.disconnects += 1
            self.peers = []
        else:
            raise AssertionError(method)


def bounded_poll(predicate, timeout):
    for _ in range(3):
        if predicate():
            return
    raise TimeoutError('peer remained connected')


class DrainTests(unittest.TestCase):
    def test_native_stuck_peer_fails_without_fallback(self):
        node = PeerNode()
        with tempfile.TemporaryDirectory() as root:
            diagnostic = Path(root) / 'peers.json'
            with patch('dkg_network_test.wait_for', bounded_poll):
                with self.assertRaises(TimeoutError):
                    disable_and_drain([node], diagnostic, native=True)
            self.assertEqual(json.loads(diagnostic.read_text()), {'test-node': [7]})
        self.assertEqual(node.disconnects, 0)
        self.assertFalse(node.active)

    def test_native_accepts_socket_handler_cleanup(self):
        node = PeerNode(clears_itself=True)
        with tempfile.TemporaryDirectory() as root:
            with patch('dkg_network_test.wait_for', bounded_poll):
                disable_and_drain([node], Path(root) / 'peers.json', native=True)
        self.assertEqual(node.disconnects, 0)
        self.assertEqual(node.peers, [])

    def test_workaround_remains_explicitly_available(self):
        node = PeerNode()
        with tempfile.TemporaryDirectory() as root:
            with patch('dkg_network_test.wait_for', bounded_poll):
                disable_and_drain([node], Path(root) / 'peers.json')
        self.assertEqual(node.disconnects, 1)


if __name__ == '__main__':
    unittest.main()
