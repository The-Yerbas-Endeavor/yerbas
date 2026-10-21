# GitHub Actions builds and tests

`.github/workflows/build.yaml` is the single **Yerbas Build and Tests** workflow.
It replaces the separate build and test workflows. It runs on pushes to `dev`
and `main`, `v*` tags, pull requests, and manual dispatch. Feature branch pushes
are tested through pull requests, avoiding duplicate push/PR runs. A newer run
for the same workflow/ref cancels its predecessor. Manual dispatch becomes
available in the Actions UI once the workflow exists on the default branch.

## Platforms and artifacts

| Build job | Compiler host | Test job |
| --- | --- | --- |
| Ubuntu 22 | Ubuntu 22.04, x86_64 | Ubuntu 22.04 |
| Ubuntu 24 | Ubuntu 24.04, x86_64 | Ubuntu 24.04 |
| Ubuntu 26 | Ubuntu 26.04, x86_64 | Ubuntu 26.04 |
| Ubuntu 24 ARM64 | Ubuntu 24.04 ARM64, native aarch64 | Ubuntu 24.04 ARM64 |
| macOS 15 Intel | macOS 15, native Apple Clang x86_64 | macOS 15 Intel |
| Windows 64-bit | Ubuntu 22.04, MinGW POSIX | Windows Server 2022 |

Each build compiles `yerbasd`, `yerbas-cli`, and `test_yerbas`, with
the wallet and tests explicitly enabled. It builds the repository's pinned
`depends` libraries, with Qt and UPnP omitted. The duplicate GUI/release workflow has been retired; this consolidated workflow
builds headless binaries for CI and does not create or publish a GitHub release.
Linux ARM64 uses the native `ubuntu-24.04-arm` runner. macOS uses
`macos-15-intel`, Homebrew build tools, and a minimum deployment target of macOS
11. Apple Silicon builds are not included in this matrix.

Artifacts are kept for 14 days:

- `yerbas-<platform>-binaries`: an archive, commit/version information, and SHA-256
  checksums. Windows binaries are packaged as ZIP; Linux and macOS binaries as tar.gz.
- `yerbas-<platform>-test-executable`: the unit-test binary used by the test job.
- `yerbas-<platform>-build-logs`: dependency, configure, and compiler output,
  including dependency Autoconf logs, CMake bootstrap logs, and CMake configure
  diagnostics when present.
- `yerbas-<platform>-test-results`: JUnit XML, per-suite logs, JSON results, and a
  Markdown summary. A suite-by-suite table also appears in the Actions summary.

The Actions token needs only `contents: read`. Pull requests from forks do not
need secrets or permission to write checks. Action versions are pinned by commit.
A failing build on one platform does not cancel other matrix builds. Test jobs
still attempt to use successful build artifacts; a missing artifact fails the
corresponding test job.

## Unit-test execution

`ci/run-unit-tests.py` discovers every enabled top-level Boost suite and runs each
in a separate process. There is no passing-suite allowlist, expected-failure list,
or `continue-on-error`. Each process has a 180-second timeout. The test job fails
if discovery fails or any suite fails, crashes, times out, or produces an invalid
report. A crashing suite does not prevent the other suites from being tested.

To reproduce locally after building:

```bash
python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results
```

For a focused run, repeat `--suite`:

```bash
python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results \
  --suite subsidy_tests --suite base58_tests --suite key_tests \
  --suite bloom_tests --suite rpc_tests
```

A selected run fails if a requested suite does not exist or is disabled. The
summary counts Boost suites; the XML files contain the individual Boost test
cases. If a crash prevents Boost from writing a valid XML report, the runner
writes an error report containing the end of the suite's log.

## Current limitations

The regtest quorum type mismatch that caused `bad-qc-invalid-null` has been
corrected in regtest's local parameter copy, without changing the shared
mainnet/testnet parameters. A regression suite verifies the registry IDs and
null-commitment serialization. The quorum regression, mining, and wallet suites
pass locally after aligning the older fixtures with active Yerbas rules. See
`src/test/README.md`.

CI continues to run every enabled unit suite and reports remaining legacy test
failures rather than excluding them. Ubuntu 26.04 build and native test jobs use
the explicit `ubuntu-26.04` runner label and have their own dependency caches and
artifacts. Each new platform must complete its first hosted build before its toolchain
compatibility is confirmed.

This workflow runs native C++ unit tests. The Python functional/P2P suite is a
separate next step: it still needs its inherited chain assumptions and hash
adapter reconciled with Yerbas before it can provide reliable coverage. Merely
installing Dash's hash adapter would not validate Yerbas GhostRider blocks.

## macOS native CMake bootstrap

Run `39552959987` failed while bootstrapping pinned CMake 4.4.4 with
“Cannot find appropriate C compiler on this system,” before building Yerbas.
The original artifacts omitted the detailed compiler probe log, so the exact
compiler diagnostic could not be recovered from that run.

The Darwin builder now resolves the macOS SDK explicitly with
`xcrun --sdk macosx --show-sdk-path` and supplies `-isysroot` to native C and
C++ compilation and linking. The native CMake recipe now forwards the build
machine's compiler/linker flags to bootstrap. These are build-machine settings:
Linux-to-Windows and Linux-to-Darwin cross builds do not acquire macOS SDK flags.
CMake bootstrap failures print their detailed log and preserve the failing exit
status; CI also uploads the dependency configure logs.

Make-variable and bootstrap failure-path checks can run on Linux, but they do
not establish macOS compatibility. The SDK correction addresses a missing
native-toolchain setting; a successful hosted macOS build is still required to
confirm that it resolves the reported failure.

### Boost 1.92 callback compatibility

Run `39556140920`, Ubuntu 26.04 job `119076493633`, failed compiling unqualified
Boost.Bind placeholders in validation and validationinterface. Callback sites now
use `boost::placeholders::_1` (and corresponding arguments), including matching
connect/disconnect expressions and the RPC/Tor callback sites. This fixes the
reported compile errors without restoring deprecated global placeholder aliases.

## CI compile fix: 2026-10-21

Run 39560293539 passed dependency builds and configure on all five completed
Linux/Windows jobs, then failed compiling `cuckoocache_tests.cpp`: the source used
`std::deque` without including `<deque>`. Added the direct standard-library include
so the test does not depend on Boost's transitive includes. A focused C++17 syntax
check using Boost 1.92 passes. A full CI rerun remains necessary; this check does
not establish that all later compilation or tests pass. macOS was still building
dependencies when inspected. No test suites were excluded.

The local dependency build also exposed a MiniUPnPc 2.3.3 recipe mismatch:
Unix builds now produce `build/libminiupnpc.a`, while `Makefile.mingw` still
produces `libminiupnpc.a`. The recipe now selects the correct platform path for
both building and staging. A fresh patched Linux archive build passed (14 object
files); Windows/macOS compilation remains for platform validation. CI currently
uses `NO_UPNP=1`, so its dependency step did not exercise this recipe.

MiniUPnPc's URL parser now preserves const input pointers through its private
helper and callers. Absolute-URL construction uses a separate const pointer when
searching the input, retaining a writable pointer for its allocated output. This
fixes GCC's discarded-qualifier warnings without casts or warning suppression.
The patched Linux static library rebuilt without warnings using `-Wall -Wextra
-Werror=discarded-qualifiers`. No full application rebuild was run for this fix.
