# Dependency modernization — 2026-10-20

This follow-up updates the active dependency graph for Yerbas 4.0.0.1 and removes
the obsolete Qt 5/BIP70 build path. Public consensus parameters, BLS signature
formats and the wallet database format are unchanged.

| Dependency | Previous pin | Updated pin |
| --- | --- | --- |
| Boost | 1.90.0 | 1.92.0 |
| libevent | 2.1.12-stable | 2.1.13-stable |
| CMake | 3.22.2 | 4.4.4, native build tool |
| immer | 0.7.0 | 0.9.1, headers only |
| MiniUPnPc | 2.2.2 | 2.3.3 |
| libbacktrace | 2018 Rust mirror snapshot | upstream 0b9b49cf4a2c9229fc052d6716e1528b2f23e91a |
| Expat (inactive legacy desktop recipe) | 2.4.1 | 2.9.0 |
| GUI | bundled Qt 5.9.6 / system Qt 5.15 | system shared Qt >= 6.8 |
| protobuf/protoc | 3.20.3 | removed with BIP70 |

The earlier OpenSSL 3.5.9 LTS, ZeroMQ 4.3.5, GMP 6.3.0, qrencode 4.1.1 and
zlib 1.3.2 updates remain. Versions describe selected compatible releases,
not a promise that every vendored or inactive recipe is the newest release.
The system Qt version follows OS updates. The old X11/font/DBus source recipes
are no longer selected for the Linux GUI; those libraries come from the OS.
Unused Python DMG packaging dependencies (biplist, ds_store, mac_alias) are
removed from the native macOS graph. Legacy macOS cross-toolchain recipes are
outside this local-GUI migration.

Berkeley DB remains 4.8.30 for wallet compatibility. The patched 20181101 BLS
fork remains pinned because upgrading signature schemes/serialization requires
a separate protocol compatibility project. These are deliberate exceptions,
not dependencies that can safely be bumped by changing a version number.

## Build and source changes

CMake is now `native_cmake`, uses the build compiler/prefix, and is an explicit
BLS dependency. Cross builds must run a host tool rather than a target executable.
Immer installs its upstream headers without building examples or tests.
MiniUPnPc uses its new include layout; the network code supplies the WAN address
arguments required by API >= 18. Its privacy patch was rebased onto the new
source layout. Libbacktrace now tracks an immutable upstream commit instead
of the old Rust mirror. Archive hashes are recorded in the recipes.

Qt changes and retirement behavior are documented in [local-gui-build.md](local-gui-build.md).
Existing GUI test suites remain registered. Payment-server tests now cover URI
queuing, normal recipients, rejected remote/file requests, and historical coin
and asset recipient serialization. URI tests also reject remote requests in the
shared parser. No failing core suite is hidden or excluded.

## Verification scope

Archive checksums were calculated from downloaded upstream sources; Boost and
CMake were additionally compared with upstream checksum manifests. The updated
MiniUPnPc patch applies without fuzz. Autotools regeneration and isolated Qt 6
configuration/tool discovery are checked. GUI sources are checked against Qt
6.10.2, Boost 1.92 and OpenSSL 3.5.9 headers; focused tests use offscreen Qt.

A full dependency rebuild and complete application link/runtime test remain
pending and manual. Hosted results for earlier commits do not validate later changes. Use the manual GUI build instructions and run every enabled
Boost suite plus the integrated Qt test executable after rebuilding.

## Upstream references

- https://www.boost.org/releases/1.92.0/
- https://github.com/libevent/libevent/releases/tag/release-2.1.13-stable
- https://github.com/Kitware/CMake/releases/tag/v4.4.4
- https://github.com/arximboldi/immer/releases/tag/v0.9.1
- https://github.com/miniupnp/miniupnp/releases/tag/miniupnpc_2_3_3
- https://github.com/ianlancetaylor/libbacktrace/commit/0b9b49cf4a2c9229fc052d6716e1528b2f23e91a
- https://github.com/libexpat/libexpat/releases/tag/R_2_9_0
- https://www.qt.io/blog/qt-6.12-released

## Hosted CI findings from the preceding published commit

Run [39548746274](https://github.com/The-Yerbas-Endeavor/yerbas/actions/runs/39548746274)
failed Linux/ARM64 application compilation because `httpserver.cpp` relied on a
transitive `<deque>` include removed by modern dependencies. It now includes
`<deque>` directly. Native macOS failed building obsolete `native_biplist` with
missing Python setuptools/ez_setup. Those unused DMG packaging dependencies are
removed from the native macOS graph; headless artifacts do not require them.
A new hosted run is still needed to verify these fixes.

## Local check results

- 76 GUI/test translation units passed C++17 syntax checks with Qt 6.10.2
  and Boost 1.92 headers. Wallet-enabled conditional GUI files were rechecked.
- Focused Qt results: URI 3/3, asset viewer 8/8, traffic graph 9/9, and payment
  server 3/3 (counts include Qt init/cleanup; no skipped cases). The isolated
  payment harness uses mainnet address-prefix and temporary-path fixtures with
  the real parser, payment handler, Base58 code and serialization. It links
  existing local crypto objects; it is not a complete new-dependency build.
- Libevent, libbacktrace and Expat configure successfully.
- HTTP server, deterministic smartnode handling (new immer headers), and
  MiniUPnPc-enabled networking pass focused syntax checks.
- Qt configure accepts Qt 6 and headless mode and rejects the retired Qt 5 choice.

Full rebuild, integrated tests, GUI startup and hosted CI remain pending.

## Qt generated-code and optional-feature follow-up

All 67 Qt meta-object translation units generated by Qt 6 moc pass syntax
checks with the production `QT_NO_KEYWORDS` flag. QR-enabled request dialogs
and DBus-enabled desktop notifications also pass. The DBus check found and
fixed a Qt 6 API change: Freedesktop image registration now retains the returned
`QMetaType` instead of treating it as an integer. A compiled runtime probe
confirms the resulting QVariant type and `(iiibiiay)` DBus image signature;
it does not send a desktop notification.

Dependency selection checks cover native Linux GUI/headless and Windows cross
build configurations. The simulated native-macOS package selection excludes
legacy DMG Python dependencies, but macOS compiler execution cannot be checked
on this Linux machine. Invalid GUI/headless combinations and cross-system-Qt
requests are rejected. These checks do not replace platform builds.

## Dependency and asset audit — 2026-10-21

Current upstream releases were rechecked before this pass. No version-only bump
was needed for the active general-purpose dependencies:

| Package | Selected version | Upstream reference |
| --- | --- | --- |
| Boost | 1.92.0 | https://www.boost.org/releases/latest/ |
| OpenSSL | 3.5.9 LTS | https://openssl-library.org/source/ |
| libevent | 2.1.13-stable | https://libevent.org/ |
| ZeroMQ | 4.3.5 | https://github.com/zeromq/libzmq/releases/latest |
| GMP | 6.3.0 | https://gmplib.org/ |
| CMake | 4.4.4 | https://github.com/Kitware/CMake/releases/latest |
| immer | 0.9.1 | https://github.com/arximboldi/immer/releases |
| MiniUPnPc (client) | 2.3.3 | https://miniupnp.tuxfamily.org/files/ |
| qrencode | 4.1.1 | https://github.com/fukuchi/libqrencode/releases/latest |
| zlib | 1.3.2 | https://zlib.net/ |

OpenSSL 4.0.3 is newer, but the selected 3.5 LTS line has upstream support through
April 2030. Both pkg-config and direct header checks now require OpenSSL >= 3.5;
the old 1.1.1 fallback is no longer accepted. Qt remains supplied by the OS/SDK,
with minimum 6.8; upstream Qt 6.12 is current, but the installed validation SDK is
6.10.2. See https://www.qt.io/blog/qt-6.12-released.
Libbacktrace retains the previously reviewed immutable upstream snapshot.

Removed 34 retired or unselected package recipes and their tracked patches:
the old Qt 5/X11/font/DBus stack, alternative unused BLS/sodium/NAT-PMP and
Boost helpers, Python DMG tools, and the obsolete macOS cross compiler/packaging
stack. This supersedes the earlier note that inactive recipes remained present.
The old cross graph referenced missing `cmake` and did not fully select its
compiler dependencies. macOS now explicitly requires a native Xcode builder;
Linux-to-macOS cross builds fail early with an actionable message. Native macOS
and Linux-to-Windows remain selected CI platforms. `download` no longer tries a
retired macOS cross build on Linux; `download-osx` is native-macOS-only. The native
macOS deployment minimum is 11.0, matching CI. Updated depends usage examples.

Compatibility exceptions remain explicit: Berkeley DB 4.8.30 and the legacy
BLS fork retain wallet/protocol compatibility. Vendored LevelDB, secp256k1,
UniValue, and consensus hashing implementations are unchanged in this pass.
This is not a claim that every embedded third-party source is now at upstream
HEAD. Their upgrades require separate API, persistence and consensus-vector
validation, and the full application build remains manual.

### Asset corrections

- Empty database asset filters no longer call `back()` on an empty string.
- Negative pagination returns to the queried database namespace, rather than
  the first key in the entire database. This fixes missing reverse-page results
  for asset holdings and owner-address queries in mixed-key databases.
- Negative offsets beyond the beginning clamp to the first matching row;
  `LONG_MIN` is covered without signed negation or unsigned wraparound.
- Balance helpers require the caller's wallet and lock that wallet. The asset
  RPC and rewards code pass their selected wallet instead of using `vpwallets[0]`.
- Reused balance/output parameters are reset, avoiding stale amounts and outputs.
- Exact `listmyassets` filters exclude subassets sharing the requested prefix;
  trailing-star filters retain prefix matching.

These changes affect queries and wallet selection, not asset issuance validity,
serialization, activation heights, or public consensus settings.

### Validation

Three new `assetdb_tests` cases are registered in the regular Boost test binary.
A focused binary compiled the changed asset database, balance, rewards and RPC
sources and linked them against existing local libraries: all three cases pass.
The original database source fails the new reverse-pagination regression.
This targeted binary is not a full rebuild with the new dependency stack.
The changed production sources also pass C++17 syntax checks against Boost 1.92
and the prepared OpenSSL 3.5.9 headers. Dependency graph checks pass for native
Linux GUI/headless, ARM64, Windows cross, and simulated native macOS; the retired
macOS cross combination is rejected. Autotools regenerated successfully and
accepted the local OpenSSL 3.5 headers. Hosted builds and live multiwallet asset
issuance/transfer/reorg validation remain pending.

## Bootstrap and asset follow-up — 2026-10-21

Rechecked the required external release pins against upstream: Boost 1.92.0,
OpenSSL 3.5.9 LTS, CMake 4.4.4 stable (4.5 is a release candidate), libevent
2.1.13, ZeroMQ 4.3.5, GMP 6.3.0, immer 0.9.1, qrencode 4.1.1, and zlib 1.3.2.
MiniUPnPc stays at the reviewed 2.3.3 client release; MiniUPnPd releases are a
separate server component. Qt remains system-managed Qt >= 6.8. Berkeley DB 4.8
and the compatible BLS fork remain intentional wallet/protocol exceptions.
There are no invented version bumps or switches to prereleases in this pass.

Additional release references:

- [CMake stable downloads](https://cmake.org/download/)
- [OpenSSL supported downloads](https://openssl-library.org/source/)
- [libevent releases](https://libevent.org/)
- [ZeroMQ 4.3.5](https://github.com/zeromq/libzmq/releases/tag/v4.3.5)
- [GMP](https://gmplib.org/)
- [zlib](https://zlib.net/)
- [qrencode](https://github.com/fukuchi/libqrencode)

The Boost recipe now restricts both stage and install to chrono, filesystem,
program_options, thread, and test. Bootstrap selection alone did not constrain
all b2 installation targets; the previous complete build also explored unrelated
libraries and emitted a histogram target-selection error. Static/release/debug
and platform settings remain explicit.

`configure.ac` now requires Autoconf >= 2.69 and Automake >= 1.16, selects Python 3
instead of obsolete version-specific/Python 2 executables, and verifies Python
>= 3.8 (needed by the test runner). Tests require Python. Pkg-config checks require
libevent >= 2.1.12, ZeroMQ >= 4.3.5, and qrencode >= 4.1.1; the existing OpenSSL
>= 3.5 and Qt >= 6.8 checks remain. Minimum compatible versions are distinct from
reproducible dependency pins.

Configure also compiles the compatible BLS header and links BLS/GMP, producing
an early actionable error when include/library paths are missing. `BLS_LIBS` is
an overridable configure variable propagated into Makefile targets. Use the
built depends `config.site`, or explicitly supply `CPPFLAGS`, `LDFLAGS`, and
`BLS_LIBS` for a nonstandard installation. No sudo installation is required.

`autogen.sh` handles its source directory independently of the caller's CDPATH,
checks prerequisite tools, honors AUTORECONF/AUTOCONF/AUTOMAKE/ACLOCAL and
PKG_CONFIG overrides, supports pkgconf, and forwards autoreconf arguments. The
vendored secp256k1 bootstrap uses AC_PROG_CC; the pthread macro uses AS_ECHO;
Automake knows yerbas-tx as an explicit optional target. These remove the observed
regeneration warnings without hiding warnings or enabling another default binary.

Six focused asset-wallet tests pass, including a new exact reward-allocation
regression. Allocation now uses integer distribution units and a 128-bit
intermediate product, never floating point. Native YERB uses eight decimals;
asset payments respect their declared units. Rounding dust remains unspent.
Zero/negative/overflowing ownership totals, duplicate recipients, invalid units,
and payouts below one distribution unit are rejected. A recorded payment absent
from the selected wallet stops processing before later batches are sent.
These are wallet reward-construction fixes, not consensus changes.

Validation: warning-free autoreconf regeneration; generated configure help;
positive BLS/GMP/Python configure probe and negative missing-library/interpreter
probes; Boost make-database inspection; six focused asset-wallet tests; Boost
1.92 syntax checks of the changed reward code/tests. A complete dependency rebuild
and application build remain manual. The preceding failed Linux jobs in run
39556140920 use code before the Boost placeholder fix in 0b71fcf; new hosted
results are required before claiming all platforms pass.


### Windows Qt repair in progress (2026-10-21)

The development machine is Linux; the priority output is the Windows Qt wallet
and its existing asset viewer. Continue using the existing depends/Autotools build.
The working tree now restores a Qt dependency route for
`HOST=x86_64-w64-mingw32`, using matching Qt 6.12.0 native Linux tools and shared
Windows libraries, with Core5Compat and its two upstream CVE-2026-101201 patches.
Native Linux defaults to system Qt; `NO_QT=1` explicitly selects headless builds.
Configure now requires Qt when GUI dependencies were selected, accepts a separate
native Qt libexec directory, and GUI link flags exclude the old all-static option.
The MinGW global C++ flags no longer force a separate static C++ runtime into the
shared Qt wallet; headless targets retain their existing all-static link setting.

Validation so far: all four dependency-selection checks (native Linux GUI,
native headless, Windows GUI, Windows headless), `git diff --check`, and Autotools
regeneration pass. No Qt compilation, Windows linking, executable startup or asset
viewer runtime validation has been performed. The Windows CI still explicitly
builds headless targets. Runtime DLL/plugin packaging and Windows GUI CI validation
remain unfinished. These changes are committed as build infrastructure work in progress and must not
be represented as a working Windows wallet release.


### Windows GUI CI and packaging (2026-10-21)

The existing Windows job now cross-builds the Qt wallet on Ubuntu 26.04, with a
240-minute allowance for a cold dependency build. Matching host Qt tools use shared
Qt, as recommended upstream, and have an installation RPATH to their native SDK
libraries. Other platform jobs keep their existing headless configuration.

Windows packaging follows PE imports recursively, copies required Qt/compiler
DLLs, checks required platform/image/Schannel plugins, and includes licenses,
toolchain versions and checksums. Missing non-system DLLs fail packaging. The
Windows runner receives the same runtime and runs core suites, Qt/asset tests and
a wallet version-dialog startup check. It does not open a wallet for the startup
check. This supersedes the earlier note that Windows CI remains headless.

Local validation: host Qt configure succeeds; packaging regression tests cover
recursive imports, plugins, case-insensitive DLL names, compiler runtime lookup,
and missing-DLL failure. Workflow YAML and shell syntax are checked. Full Windows
compile and runtime validation belong to the new hosted run; no full local build
was launched. See build-windows.md for artifact and manual-build instructions.

The checksum-verified Qt 6.12.0 Core5Compat archive already contains both
CVE-2026-101201 fixes (overflow-safe bounds arithmetic and size_t comparisons),
including upstream regression tests. Removed redundant downstream patches that
would otherwise fail during depends preprocessing.


### macOS 15 dependency fetch fix (2026-10-21)

The macOS 15 job completed its Boost build, then failed fetching GMP 6.3.0: the
`ftp.gnu.org` connection timed out three times and the shared Bitcoin depends
fallback returned 404. The GMP recipe now fetches the same pinned archive from
GMP's official HTTPS download server. The downloaded archive's SHA-256 matches
the unchanged pin (`ac28211a7cfb609bae2e2c8d6058d66c8fe96434f740cf6fe2e47b000d1c20cb`).
The package version and contents are unchanged. A hosted rerun is required to
confirm macOS completes its dependency and application builds.
