# Yerbas Asset Contract Layer

## Status

This document defines the first implementation milestone for constrained, deterministic contracts attached to Yerbas Assets. It is a design specification only. The initial code must remain inactive until a later consensus deployment explicitly enables contract transaction parsing and execution.

## Goals

The contract layer supports five bounded applications:

1. Escrow
2. Royalties
3. Auctions
4. Atomic asset swaps
5. Asset-weighted voting

The design intentionally excludes general-purpose computation, arbitrary bytecode, external calls, networking, filesystem access, wall-clock access, floating point, nondeterministic randomness, recursive contract creation, and unrestricted cross-contract calls.

## Contract model

A contract is an immutable template instance associated with one controlling Yerbas Asset. Contract behavior is selected from a consensus-defined template enum rather than uploaded executable code.

Each contract has:

- a deterministic contract ID;
- a template type and template version;
- a controlling asset name;
- an owner destination;
- immutable creation parameters;
- bounded mutable state;
- an execution-unit limit;
- a lifecycle status.

The contract ID is derived from the deployment transaction outpoint:

```
contract_id = Hash(deployment_txid || output_index)
```

## Template types

### Escrow

Locks YERB or Yerbas Assets until one of the following deterministic conditions occurs:

- all required parties approve release;
- a refund height is reached;
- a designated arbitrator selects release or refund.

### Royalty

Defines a basis-point royalty and one or more recipients. A royalty contract may be referenced by marketplace settlement transactions. Consensus validates the recipient shares and the maximum total royalty.

### Auction

Supports fixed-duration English auctions with:

- one listed asset lot;
- YERB-denominated bids;
- a minimum bid;
- an optional reserve;
- a deterministic end height;
- refund accounting for displaced bids.

### Atomic swap

Locks two asset bundles and completes only when both sides satisfy the declared terms before expiry. Otherwise, each side can reclaim its original bundle after the expiry height.

### Voting

Creates an asset-weighted vote with a fixed snapshot height, option count, start height, and end height. Voting power is derived from consensus-visible asset balances at the declared snapshot and cannot be reused across conflicting votes within one proposal.

## Operations

The first protocol version defines these operations:

- `DEPLOY`
- `CALL`
- `CANCEL`
- `FINALIZE`

Each operation must have a maximum serialized size and a template-specific validation function.

## Determinism rules

Contract evaluation may read only:

- the current block height;
- the transaction being validated;
- referenced UTXOs;
- current Yerbas Asset metadata;
- the contract's own state;
- consensus-defined constants.

Contract evaluation must not read median time, local clock time, mempool ordering, peer state, RPC state, environment variables, or external services.

## Resource limits

Initial limits should be conservative and consensus-defined:

- maximum deployment payload: 4 KiB;
- maximum call payload: 2 KiB;
- maximum state entries per contract: 256;
- maximum state key: 64 bytes;
- maximum state value: 512 bytes;
- maximum operations per call: 1,000;
- maximum contracts touched by one transaction: 8.

These values remain provisional until testnet benchmarking is complete.

## Database and undo

Contract metadata and state must use dedicated databases and caches. Every state mutation must produce undo data sufficient to restore the exact previous state during block disconnection and chain reorganization.

Suggested components:

```
src/assets/assetcontract.h
src/assets/assetcontract.cpp
src/assets/assetcontractdb.h
src/assets/assetcontractdb.cpp
src/assets/assetcontractvalidation.h
src/assets/assetcontractvalidation.cpp
```

## Activation

No contract payload is valid on mainnet until a dedicated consensus deployment activates the feature. Before activation, contract-looking data is treated according to existing script and transaction rules and must not mutate contract state.

Activation requires:

- test vectors;
- unit tests;
- functional tests;
- reorganization tests;
- malformed-payload tests;
- resource-limit tests;
- testnet soak testing;
- independent security review.

## Milestones

### Milestone 1

Define serialized types, template limits, IDs, lifecycle status, and context-free validation. No consensus wiring.

### Milestone 2

Add contract database, cache, and undo records with unit tests.

### Milestone 3

Add inactive transaction parsing and RPC decoding behind a regtest-only feature flag.

### Milestone 4

Implement escrow and atomic-swap state transitions on regtest.

### Milestone 5

Implement royalties, auctions, and voting on regtest and testnet.

### Milestone 6

Add deployment signaling and a future activation height after review.
