#!/usr/bin/env python3
"""Isolated mainnet-parameter smoke test for the built prune=256 daemon.

Uses a disposable empty datadir and disables P2P discovery and connections.
Does NOT test mainnet chain migration, historical quorum retention, or signing.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


def get_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def rpc(port, username, password, method):
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    payload = json.dumps({"jsonrpc": "1.0", "id": "prune-smoke", "method": method, "params": []}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/", data=payload,
        headers={"Authorization": f"Basic {credentials}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        result = json.load(response)
    if result.get("error"):
        raise RuntimeError(f"{method}: {result['error']}")
    return result["result"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("daemon", type=Path)
    parser.add_argument("--workdir", type=Path)
    opts = parser.parse_args()
    daemon = opts.daemon.resolve()
    if not daemon.is_file():
        raise SystemExit(f"No daemon at {daemon}")

    with tempfile.TemporaryDirectory(prefix="yerbas-mainnet-prune-") as temp:
        datadir = (opts.workdir or Path(temp) / "datadir").resolve()
        datadir.mkdir(parents=True, exist_ok=True)
        if any(datadir.iterdir()):
            raise SystemExit("Refusing nonempty datadir; test must never touch existing wallets or chain files")
        rpc_port = get_free_port()
        user = "prune_smoke"
        password = secrets.token_hex(24)
        cmd = [
            str(daemon), f"-datadir={datadir}", "-printtoconsole=1",
            "-server=1", "-listen=0", "-dnsseed=0", "-discover=0",
            "-connect=0", "-maxconnections=0", "-upnp=0",
            "-txindex=0", "-prune=256", f"-rpcport={rpc_port}",
            f"-rpcuser={user}", f"-rpcpassword={password}",
        ]
        output_path = Path(temp) / "daemon.log"
        with output_path.open("w+") as log:
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 65
                last_error = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"daemon exited with status {process.returncode}")
                    try:
                        info = rpc(rpc_port, user, password, "getblockchaininfo")
                        if info.get("chain") != "main":
                            raise RuntimeError(f"Expected main chain, got {info.get('chain')!r}")
                        if info.get("pruned") is not True:
                            raise RuntimeError(f"Mainnet daemon did not enable pruning: {info.get('pruned')!r}")
                        print("PASS: built mainnet daemon accepts prune=256 and reports pruned=true", flush=True)
                        print("NOTE: empty chain only; no block deletion or Smartnode quorum validation", flush=True)
                        return
                    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                        last_error = exc
                        time.sleep(0.3)
                raise RuntimeError(f"RPC startup timeout: {last_error!r}")
            finally:
                if process.poll() is None:
                    try:
                        rpc(rpc_port, user, password, "stop")
                    except Exception:
                        process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                log.flush()
                if process.returncode not in (0, None):
                    log.seek(0)
                    tail = log.read()[-5000:]
                    print(f"Daemon diagnostic tail (RPC password not logged):\n{tail}", flush=True)


if __name__ == "__main__":
    main()
