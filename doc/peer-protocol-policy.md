# Minimum peer protocol for 4.0.1.6

Core requires peer protocol **70224** during the VERSION handshake, both before
and after asset activation. It continues to advertise protocol 70224; a new
wire format or application-version bump is not needed for this cutoff.

The inspected v3.2.0.8–v3.2.0.21 release tags advertise 70223, and v3.2.2.10
advertises 70222. These peers are disconnected as obsolete. The inspected
v4.0.0.6, v4.0.1.2, v4.0.1.3 and v4.0.1.4 tags advertise 70224 and remain
eligible to connect. Other existing handshake checks still apply.

The check applies to inbound and outbound connections, including manual
connections and Smartnode links. It rejects the handshake without permanently
banning the address. A TCP connection must first be established to learn the
remote version; this policy prevents completing a session with an obsolete
peer, not every TCP connection attempt to its address.

This is a protocol compatibility policy, not authentication of the remote
software. A modified peer can misreport its protocol or user-agent. Advertising
a v4 user-agent with protocol 70223 does not bypass the minimum.

No block-validation rules, quorum parameters, Smartnode protocol eligibility
constants, or ChainLock behavior change. Deploy the tested binary through the
normal upgrade process; no reindex is required by this peer-policy change.
Existing connections are replaced on daemon restart. Production rollout is a
separate operator action.

`p2p_min_peer_version.py` exercises inbound and manual outbound handshakes at
regtest heights 0 and 2 (asset activation is at height 1), rejects 70222/70223,
and verifies version/verack plus ping/pong for 70224 and 70225. It also checks
that a v4 user-agent cannot rescue protocol 70223. The functional-test default
protocol is 70224 so ordinary test peers remain compatible.
