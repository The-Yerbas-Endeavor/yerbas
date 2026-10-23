#!/usr/bin/env python3
"""Collect evidence, or independently validate it as a quorum member.

One target per process. A complete 30-block window contains three probes spaced
10 blocks apart. Missed probes, RPC errors, reorgs, or a service change discard the
window. Run independent instances on separate official monitoring hosts.
"""
import argparse
import json
import subprocess
import time


class RPC:
    def __init__(self, cli, args):
        self.command = [cli] + args

    def __call__(self, *args):
        result = subprocess.run(self.command + [str(a) for a in args],
                                capture_output=True, text=True, timeout=30, check=True)
        text = result.stdout.strip()
        if not text:
            return None
        # yerbas-cli prints JSON strings without their quotes.
        if args[0] == "getblockhash":
            return text
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


def identity(info):
    state = info["state"]
    return (state["service"], state["pubKeyOperator"],
            state["registeredHeight"], state["PoSeRevivedHeight"])


def usable_peers(peers):
    # A generally disconnected monitor must not report target outages.
    return sum(not p.get("inbound", True) and p.get("version", 0) > 0
               for p in peers) >= 3


def responded(peer, target, service, since):
    return (not peer.get("inbound", True)
            and peer.get("addr") == service
            and peer.get("verified_proregtx_hash") == target
            and peer.get("lastrecv", 0) >= since)


def inbound_duplicate(peers, target):
    # Core rejects a second MNAUTH connection for an already authenticated node.
    # An existing inbound connection can therefore invalidate an outbound probe.
    return any(p.get("inbound", False) and p.get("verified_proregtx_hash") == target for p in peers)


def probe(rpc, target, service, timeout):
    """None is an inconclusive observer failure; False is a target timeout."""
    if rpc("getblockchaininfo").get("initialblockdownload", True):
        return None
    before = rpc("getpeerinfo")
    if not usable_peers(before) or inbound_duplicate(before, target):
        return None
    received = {p["id"]: p.get("bytesrecv", 0) for p in before}
    started = int(time.time())
    rpc("addnode", service, "onetry")
    rpc("ping")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        peers = rpc("getpeerinfo")
        if inbound_duplicate(peers, target):
            return None
        if any(responded(peer, target, service, started)
               and peer.get("bytesrecv", 0) > received.get(peer["id"], 0) for peer in peers):
            return True
        time.sleep(1)
    after = rpc("getpeerinfo")
    return False if usable_peers(after) and not inbound_duplicate(after, target) else None


def complete(samples, end_height, state):
    return (len(samples) == 3
            and [s["height"] for s in samples] == [end_height - 20, end_height - 10, end_height]
            and all(s["reachable"] is False and s["identity"] == state for s in samples))


def maybe_approve(rpc, target, pending, height, timeout):
    end, state, anchors, request_id = pending
    if (height < end or height - end > 120 or identity(rpc("protx", "info", target)) != state
            or any(rpc("getblockhash", h) != block for h, block in anchors)):
        return "discarded"
    # Re-probe before signing: recovery after the observation window cancels it.
    if probe(rpc, target, state[0], timeout) is not False:
        return "discarded"
    if (identity(rpc("protx", "info", target)) != state
            or any(rpc("getblockhash", h) != block for h, block in anchors)):
        return "discarded"
    try:
        rpc("pose", "approve", request_id)
        return "share_requested"
    except subprocess.CalledProcessError:
        # Missing reports/quorum must never be bypassed.
        return "pending"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Registered smartnode proTxHash")
    parser.add_argument("--cli", default="yerbas-cli")
    parser.add_argument("--cli-arg", action="append", default=[], help="Repeat; use --cli-arg=-regtest syntax")
    parser.add_argument("--role", choices=["observer", "validator"], default="observer",
                        help="validator opts a quorum member into approval after independent probes")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    if len(args.target) != 64 or any(c not in "0123456789abcdefABCDEF" for c in args.target):
        parser.error("target must be a 64-character proTxHash")
    if not 5 <= args.timeout <= 60:
        parser.error("timeout must be between 5 and 60 seconds")
    target = args.target.lower()
    rpc = RPC(args.cli, args.cli_arg)
    samples, last_height = [], -1
    pending_approval, last_approval_attempt = None, -1
    while True:
        try:
            height = rpc("getblockcount")
            if pending_approval is not None and height != last_approval_attempt:
                last_approval_attempt = height
                outcome = maybe_approve(rpc, target, pending_approval, height, args.timeout)
                print(json.dumps(dict(target=target, request=pending_approval[3], approval=outcome)), flush=True)
                if outcome != "pending":
                    pending_approval = None
            if height < last_height:
                samples = []
            if height == last_height or height % 10:
                time.sleep(1)
                continue
            last_height = height
            info = rpc("protx", "info", target)
            state = identity(info)
            if info["state"]["PoSeBanHeight"] != -1:
                samples = []
                time.sleep(1)
                continue
            anchor = rpc("getblockhash", height)
            reachable = probe(rpc, target, state[0], args.timeout)
            # Never attach a measurement to a replaced chain reference.
            if rpc("getblockhash", height) != anchor:
                samples = []
                continue
            if height % 30 == 10:
                samples = []
            samples.append(dict(height=height, blockHash=anchor, identity=state, reachable=reachable))
            print(json.dumps(dict(target=target, observation=samples[-1])), flush=True)
            if height % 30 == 0:
                if complete(samples, height, state) and all(
                        rpc("getblockhash", s["height"]) == s["blockHash"] for s in samples):
                    if args.role == "observer":
                        # Signing an observer report is not a quorum vote.
                        report = rpc("pose", "createreport", target, height)
                        rpc("pose", "submitreport", report["hex"])
                        print(json.dumps(dict(target=target, evidence=report, approved=False)), flush=True)
                    else:
                        request = rpc("pose", "request", target, height)
                        pending_approval = (height, state,
                                            [(s["height"], s["blockHash"]) for s in samples], request["id"])
                        last_approval_attempt = -1
                samples = []
        except (subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
            samples = []
            pending_approval = None
            print(json.dumps(dict(error=str(exc), evidence_discarded=True)), flush=True)
        time.sleep(1)


if __name__ == "__main__":
    main()
