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
pending and manual. Hosted results for earlier commits do not validate these
uncommitted changes. Use the manual GUI build instructions and run every enabled
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
