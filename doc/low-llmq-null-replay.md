# Legacy LOW_LLMQ null-commitment replay

This change fixes fresh synchronization failing with `bad-qc-invalid-null` when
historical null commitments use a different bitset size from the current live
quorum parameters. In the operator testnet, a fresh node with SPORK_21 already
active rejected block 17: the block contained a three-member null commitment,
while the live LOW_LLMQ parameters expected 200 members.

A null commitment records that no quorum formed. It has no signers, valid
members, public key, verification-vector hash, or signatures. Its bitset size
therefore cannot authorize a quorum or set a signature threshold.

The legacy validator now accepts only the existing null-commitment sizes for
the registered quorum type, independently of the current adaptive size. The
extra five-member type-2/type-3 profiles remain testnet-only. Version bounds,
equal bitset lengths, and all empty-field checks remain mandatory. Quorum
ancestry, interval, mining-window, duplicate, and required-commitment checks
remain in the block validation path. Signed commitment validation is unchanged.
The opt-in chain-record test profiles retain their exact contextual size checks;
this change does not activate or extend that recovery mechanism.

This changes consensus acceptance of null commitments. Operators still need a
coordinated software upgrade before production activation. It adds no spork,
activation transaction, expiration rule, or change to quorum generation.

## Validation

- `chainparams_tests/legacy_null_commitments_survive_live_size_changes` accepts
  known empty formats and rejects unsupported sizes, mismatched vectors,
  unknown versions/types, and non-empty records.
- `llmq-null-replay.py` mines normal then LOW null commitments, then performs
  fresh sync and full reindex with the latest spork both ON and OFF. Its
  regtest-only fixture initializes the adaptive quorum types at startup,
  matching the type availability on public networks.
- `llmq-lowparams-pose.py` exercises real signed DKG, PoSe punishment/ban, and
  exclusion of the banned operator from the next quorum.
- The remote lab observer downloaded from genesis with the signed LOW spork
  preloaded and `assumevalid=0`, importing no chain databases. At height 428,
  its block hash and all 118 deterministic smartnode states matched the
  controller. Full reindex preserved that result.

## Remaining scope

The ON/OFF regression above covers null commitments. It does not establish
replay of historical signed quorums under a different current spork or node
count. Signed membership/threshold selection and the current-spork dependency
of PoSe decay above height 37650 remain separate mainnet replay concerns. The
short testnet result must not be described as full mainnet readiness.
