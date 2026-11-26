#!/usr/bin/env python3
"""Reject v3.2 wire protocols in both directions, before/after asset activation."""
import socket
import struct
from contextlib import contextmanager

from test_framework.messages import hash256, msg_version
from test_framework.mininode import MAGIC_BYTES
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal, p2p_port, wait_until


class MinPeerVersionTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.setup_clean_chain = True

    def setup_network(self):
        # No legacy mempool-sync RPC is needed for one isolated node.
        self.setup_nodes()

    @contextmanager
    def connection(self, outbound):
        if outbound:
            # Exercise the daemon's outbound VERSION handling, including manual
            # connections: addnode must not bypass the protocol minimum.
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                listener.listen(1)
                listener.settimeout(10)
                self.nodes[0].addnode("127.0.0.1:%d" % listener.getsockname()[1], "onetry")
                peer, _ = listener.accept()
        else:
            peer = socket.create_connection(("127.0.0.1", p2p_port(0)), timeout=10)
        with peer:
            peer.settimeout(10)
            yield peer
        wait_until(lambda: not self.nodes[0].getpeerinfo(), timeout=10)

    def send(self, peer, command, payload=b""):
        peer.sendall(MAGIC_BYTES[self.chain] + command.ljust(12, b"\0") +
                     struct.pack("<I", len(payload)) + hash256(payload)[:4] + payload)

    def receive(self, peer):
        def exact(size):
            data = b""
            while len(data) < size:
                try:
                    chunk = peer.recv(size - len(data))
                except ConnectionResetError:
                    return None
                if not chunk:
                    return None
                data += chunk
            return data
        header = exact(24)
        if header is None:
            return None, None
        assert_equal(header[:4], MAGIC_BYTES[self.chain])
        size = struct.unpack("<I", header[16:20])[0]
        assert size <= 4 * 1024 * 1024
        payload = exact(size)
        assert payload is not None
        assert_equal(hash256(payload)[:4], header[20:24])
        return header[4:16].rstrip(b"\0"), payload

    def check_version(self, version, subversion, outbound, accepted):
        self.log.info("protocol=%d direction=%s accepted=%s", version,
                      "outbound" if outbound else "inbound", accepted)
        with self.connection(outbound) as peer:
            message = msg_version()
            message.nVersion = version
            message.nTime = self.mocktime
            message.strSubVer = subversion
            self.send(peer, b"version", message.serialize())
            verack = False
            while True:
                command, payload = self.receive(peer)
                if command is None:
                    assert not accepted, "Supported peer disconnected during handshake"
                    assert not verack, "Obsolete peer received verack"
                    break
                if command == b"version":
                    # Outbound nodes send VERSION before learning our version.
                    if accepted:
                        self.send(peer, b"verack")
                elif command == b"verack":
                    verack = True
                    assert accepted, "Obsolete peer completed handshake"
                    self.send(peer, b"ping", struct.pack("<Q", 12345))
                elif command == b"pong":
                    assert accepted and verack
                    assert_equal(payload, struct.pack("<Q", 12345))
                    break

    def run_test(self):
        for height in (0, 2):
            if height:
                self.nodes[0].generate(height)
            assert_equal(self.nodes[0].getblockcount(), height)
            self.log.info("Testing peer minimum at height %d (assets activate at 1)", height)
            for outbound in (False, True):
                for version, subversion in (
                        (70222, b"/Yerbas Core:3.2.2.10/"),
                        (70223, b"/Yerbas Core:3.2.0.21/"),
                        # A newer user-agent string cannot bypass the wire gate.
                        (70223, b"/Yerbas Core:4.0.1.6/")):
                    with self.nodes[0].assert_debug_log(["using obsolete version %d" % version]):
                        self.check_version(version, subversion, outbound, False)
                for version in (70224, 70225):
                    self.check_version(version, b"/Yerbas Core:4.0.1.6/", outbound, True)


if __name__ == "__main__":
    MinPeerVersionTest().main()
