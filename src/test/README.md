### Compiling/running unit tests

Unit tests will be automatically compiled if dependencies were met in `./configure`
and tests weren't explicitly disabled.

After configuring, they can be run with `make check`.

To run the yerbasd tests manually, launch `src/test/test_yerbas`.

To add more yerbasd tests, add `BOOST_AUTO_TEST_CASE` functions to the existing
.cpp files in the `test/` directory or add new .cpp files that
implement new BOOST_AUTO_TEST_SUITE sections.

To run the yerbas-qt tests manually, launch `src/qt/test/test_yerbas-qt`

To add more yerbas-qt tests, add them to the `src/qt/test/` directory and
the `src/qt/test/test_main.cpp` file.

### Running individual tests

test_yerbas has some built-in command-line arguments; for
example, to run just the getarg_tests verbosely:

    test_yerbas --log_level=all --run_test=getarg_tests

... or to run just the doubleyerbas test:

    test_yerbas --run_test=getarg_tests/doubleyerbas

Run `test_yerbas --help` for the full list.

### Note on adding test cases

The sources in this directory are unit test cases.  Boost includes a
unit testing framework, and since Yerbas Core already uses boost, it makes
sense to simply use this framework rather than require developers to
configure some other framework (we want as few impediments to creating
unit tests as possible).

The build system is setup to compile an executable called `test_yerbas`
that runs all of the unit tests.  The main source file is called
test_yerbas.cpp. To add a new unit test file to our test suite you need
to add the file to `src/Makefile.test.include`. The pattern is to create 
one test file for each class or source file for which you want to create 
unit tests.  The file naming convention is `<source_filename>_tests.cpp` 
and such files should wrap their tests in a test suite 
called `<source_filename>_tests`. For an example of this pattern, 
examine `uint256_tests.cpp`.

For further reading, I found the following website to be helpful in
explaining how the boost unit test framework works:
[http://www.alittlemadness.com/2009/03/31/c-unit-testing-with-boosttest/](http://www.alittlemadness.com/2009/03/31/c-unit-testing-with-boosttest/).

### Yerbas-specific test values

Chain-specific expectations come from this branch's `src/chainparams.cpp` and
`GetBlockSubsidy` in `src/validation.cpp`. Update test fixtures to match those
rules; do not change consensus parameters merely to satisfy inherited tests.

- One YERB is 100,000,000 base units.
- Mainnet address/script/private-key prefixes are 140/19/128; testnet uses
  123/19/239. The Base58 vector generator uses these same prefixes. These
  fixtures contain public test keys, never keys for real funds.
- Mainnet P2P message start is `79 65 72 62`; testnet is `7a 79 65 72`.
- The subsidy API takes the **previous** block height. Previous heights 0–419
  return 4.20 YERB; 420–1,000,000 return 100 YERB; 1,000,001–1,999,999 return
  80 YERB. Subsequent million-height bands return 70, 50, 40, 20, 10, 9, 8,
  7, 6, 5, 4.20, 3, 2, and 1 YERB. From previous height 16,000,000 onward
  the reward is 0.420 YERB. Regtest uses this schedule too, without a
  150-block halving. The functional `create_coinbase` helper instead accepts
  the **new** block height and converts it to the previous height.

Run the directly affected unit suites after building:

    src/test/test_yerbas --run_test=subsidy_tests,base58_tests,key_tests,bloom_tests,rpc_tests

Mining and wallet suites use the current coinbase amounts, active sigop and
BIP68 limits, and `TIMESTAMP_WINDOW` for wallet rescan boundaries. Empty mining
test blocks retain required quorum commitments while excluding ordinary mempool
transactions. Functional tests still need their documented Python/P2P
requirements; updating the shared reward helper is not a claim that every
inherited functional scenario is compatible with Yerbas.

Regtest's small quorum uses `LLMQ_5_60` consistently for its registry key and
serialized commitments. Its three-member parameters are copied from the shared
`llmq3_60` definition; only the regtest copy's type ID is adjusted. Mainnet and
testnet retain the shared `LLMQ_50_60` definition. `chainparams_tests` verifies
that null commitments validate before and after serialization, that all regtest
registry IDs match their parameter types, and that the public-network small
quorums retain their existing sizes and thresholds.

    src/test/test_yerbas --run_test=chainparams_tests

### Additional legacy fixture fixes

Fee-rate strings use the `YERB/kB` ticker. Governance proposal fixtures use
mainnet Base58Check version 140; the invalid-address case retains a foreign
network address, while the other invalid cases use a valid Yerbas address so
address validation does not mask the intended failure.

Arithmetic `SetHex` parses hexadecimal text rather than copying raw string
bytes. The arithmetic suite covers empty/short input, optional prefixes,
non-hex suffixes, truncation, and the high limbs of 512-bit values. Rebuild the
unit-test executable before checking these changes:

    python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results-updated --suite arith_uint256_tests --suite uint256_tests --suite amount_tests --suite governance_validators_tests

Asset GUI regression coverage is registered in `src/qt/test/assetviewtests.cpp`. After a GUI build, run `QT_QPA_PLATFORM=offscreen src/qt/test/test_yerbas-qt`. See `doc/asset-viewer-updates.md` for scope and remaining live-wallet checks.

`assetdb_tests` covers empty/exact/wildcard asset filters, reverse pagination in
mixed-key databases, extreme negative offsets, and clearing stale wallet balance
outputs. It uses in-memory asset databases with the normal testing fixture.

### Wallet asset persistence

`asset_wallet_tests` exercises real wallet.dat backup/restore, wallet isolation,
legacy asset-store migration, corruption rejection, and paused reward imports:

```sh
src/test/test_yerbas --run_test=asset_wallet_tests --log_level=test_suite
```

See `doc/wallet-asset-storage.md` for the record format and migration policy.
