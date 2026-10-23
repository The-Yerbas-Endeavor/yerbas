#!/usr/bin/env python3
"""Start two isolated localhost testnet full nodes; no mainnet or external peers.

This is a bootstrap/smoke tool, not a distributed smartnode/DKG simulation.
Use separate hosts and 80+ valid smartnodes for the campaign in doc/pose-testnet.md.
"""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import time


def free_ports(count):
    sockets = []
    try:
        for _ in range(count):
            sock = socket.socket()
            sock.bind(('127.0.0.1', 0))
            sockets.append(sock)
        return [sock.getsockname()[1] for sock in sockets]
    finally:
        for sock in sockets:
            sock.close()


def rpc(binary, node, *command):
    result = subprocess.run([str(binary / 'yerbas-cli'), '-testnet',
                             '-datadir=' + node['datadir']] + list(map(str, command)),
                            capture_output=True, text=True,
                            timeout=300 if command and command[0] == 'generatetoaddress' else 60)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def stop(binary, nodes):
    errors = []
    for node in reversed(nodes):
        try:
            rpc(binary, node, 'stop')
        except Exception as error:
            errors.append(str(error))
    return errors


def status(binary, nodes):
    results = []
    for node in nodes:
        chain = rpc(binary, node, 'getblockchaininfo')
        pose = rpc(binary, node, 'pose', 'status')
        recovery = rpc(binary, node, 'recovery', 'status')
        assert chain['chain'] == 'test', chain
        assert pose['activationHeight'] == 4320, pose
        assert recovery['activationHeight'] == 8640, recovery
        assert recovery['committeeSize'] == 15 and recovery['threshold'] == 11, recovery
        results.append({'datadir': node['datadir'], 'height': chain['blocks'],
                        'peers': rpc(binary, node, 'getconnectioncount'),
                        'pose': pose, 'recovery': recovery})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'stop', 'smoke'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--bin-dir', type=Path, default=Path(__file__).resolve().parents[2] / 'src')
    args = parser.parse_args()
    binary = args.bin_dir.resolve()
    root = args.root.resolve()
    manifest = root / 'cluster.json'
    if args.action in ['status', 'stop']:
        nodes = json.loads(manifest.read_text())['nodes']
        result = status(binary, nodes) if args.action == 'status' else stop(binary, nodes)
        print(json.dumps(result, indent=2))
        return
    if root.exists() and any(root.iterdir()):
        parser.error('--root must be empty for start/smoke; existing data is never overwritten')
    root.mkdir(parents=True, exist_ok=True)
    ports = free_ports(4)
    nodes = []
    processes = []
    try:
        for index in range(2):
            directory = root / ('node' + str(index))
            directory.mkdir()
            node = {'datadir': str(directory), 'p2pPort': ports[index * 2],
                    'rpcPort': ports[index * 2 + 1]}
            config = ['testnet=1', 'server=1', 'listen=1', 'bind=127.0.0.1',
                      'rpcbind=127.0.0.1', 'rpcallowip=127.0.0.1', 'dnsseed=0',
                      'discover=0', 'upnp=0', 'printtoconsole=0',
                      'port=' + str(node['p2pPort']), 'rpcport=' + str(node['rpcPort']),
                      'connect=' + ('0' if index == 0 else '127.0.0.1:' + str(ports[0]))]
            (directory / 'yerbas.conf').write_text('\n'.join(config) + '\n')
            with (directory / 'console.log').open('w') as log:
                process = subprocess.Popen([str(binary / 'yerbasd'), '-datadir=' + str(directory)],
                                           stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                           start_new_session=True)
            processes.append(process)
            nodes.append(node)
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError((directory / 'console.log').read_text()[-4000:])
                try:
                    rpc(binary, node, 'getblockchaininfo')
                    break
                except RuntimeError:
                    time.sleep(.25)
            else:
                raise RuntimeError('RPC startup timeout')
            if index == 0:
                # Mine before the follower connects: an ancient genesis makes
                # the seed ignore initial getheaders while it is still in IBD.
                address = rpc(binary, node, 'getnewaddress')
                rpc(binary, node, 'generatetoaddress', 1, address)
                assert not rpc(binary, node, 'getblockchaininfo')['initialblockdownload']
        manifest.write_text(json.dumps({'nodes': nodes}, indent=2) + '\n')
        for _ in range(120):
            if all(rpc(binary, node, 'getconnectioncount') >= 1 for node in nodes):
                break
            time.sleep(.25)
        else:
            raise RuntimeError('Local testnet nodes failed to connect')
        for _ in range(120):
            if rpc(binary, nodes[1], 'getbestblockhash') == rpc(binary, nodes[0], 'getbestblockhash'):
                break
            time.sleep(.25)
        else:
            raise RuntimeError('Follower did not synchronize the bootstrap block')
        result = status(binary, nodes)
        if args.action == 'smoke':
            assert all(item['height'] == 1 for item in result), result
            assert all(not item['pose']['active'] and not item['recovery']['enabled'] for item in result)
            # Both nodes are now synchronized; check a new block announcement.
            address = rpc(binary, nodes[0], 'getnewaddress')
            hashes = rpc(binary, nodes[0], 'generatetoaddress', 1, address)
            for _ in range(120):
                if rpc(binary, nodes[1], 'getbestblockhash') == hashes[-1]:
                    break
                time.sleep(.25)
            else:
                raise RuntimeError('Mined block did not propagate')
            result = status(binary, nodes)
            (root / 'smoke-results.json').write_text(json.dumps(result, indent=2) + '\n')
            errors = stop(binary, nodes)
            if errors:
                raise RuntimeError(errors)
            for process in processes:
                process.wait(timeout=60)
        print(json.dumps(result, indent=2))
    except BaseException:
        stop(binary, nodes)
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=60)
        raise


if __name__ == '__main__':
    main()
