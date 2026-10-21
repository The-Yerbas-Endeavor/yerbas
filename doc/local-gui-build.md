# Local Linux GUI build: Qt 6

Yerbas 4.0.0.1 now uses shared Qt **6.8 or newer**, including Core5Compat.
Boost is pinned to **1.92.0**. The native Linux build uses the operating system's
Qt packages; it does not download or pin Qt itself. Compatibility checks use
Ubuntu's Qt 6.10.2 development files. Upstream Qt 6.12 is the current LTS
release; a full 6.12 build has not been validated here.

The bundled Qt 5 build path is retired. `depends` automatically selects `USE_SYSTEM_QT=1`
for a native Linux GUI when you run plain `make`. Use `NO_QT=1` for headless builds.
This builds the other dependencies; it does not install Qt itself. Cross-platform GUI
release packaging is not supported by this migration. Headless CI remains enabled.

## Features and compatibility

Ordinary `yerbas:` links, address/amount/label/message handling, wallet operations,
QR codes and asset viewing remain. Legacy BIP70 payment files, remote `r=` and
`req-r=` requests, merchant certificate verification, and payment acknowledgements
are retired. No protobuf library or protoc compiler is needed. Historical request
bytes and merchant labels retain their original serialized positions and are
preserved as opaque data; historical requests cannot be submitted as payments.
Transaction details identify retained legacy metadata without processing it.

Qt compatibility changes cover screen geometry, font measurements, dates, sorting,
item flags, image access, keyboard events, DBus image metatypes and explicit
includes. Core5Compat
supplies the remaining QRegExp APIs. The `yerbas://` normalization also fixes an
existing wrong prefix length which corrupted the address. The traffic-graph
regression test now uses a deterministic Qt random generator.

## Manual build

Provide Qt 6.8+ development libraries and tools (Core, Gui, Widgets, Network,
Core5Compat, Test and Linguist), plus a compiler, Autotools, pkg-config, Perl and
Python. An existing system installation or a user-owned Qt SDK can be used; for
a local SDK, put its pkg-config directory on PKG_CONFIG_PATH. Berkeley DB does
not require system installation: see [berkeley-db-local.md](berkeley-db-local.md)
for the independent, unprivileged BDB-only build.

```bash
cd /home/anno/Code/yerbas
make -C depends -j2 NO_UPNP=1
# Clean old objects if this checkout already has a generated Makefile.
make clean
./autogen.sh
./configure --prefix="$PWD/depends/x86_64-pc-linux-gnu" \
  --with-gui=qt6 --with-qrencode --without-miniupnpc \
  --disable-bench --enable-wallet --enable-tests
make -j2
python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results-gui-deps
QT_QPA_PLATFORM=offscreen src/qt/test/test_yerbas-qt
```

Do not reuse the old dependency prefix under Documents/Codex or objects compiled
against older Boost/Qt versions. If no Makefile exists, omit `make clean`.
Qt tool discovery uses Qt6Core's pkg-config `libexecdir` and `bindir` and rejects
non-Qt-6 moc/uic/rcc/lrelease. Configure no longer probes protobuf.

The dependency and full application rebuild remain manual. Syntax checks and
focused GUI tests do not establish full linking, GUI startup, wallet transaction
behavior, or cross-platform compatibility. Run the asset wallet checks in
[asset-viewer-updates.md](asset-viewer-updates.md) before using this build with
valuable wallets. Existing core test failures must remain visible.

See [dependency-modernization.md](dependency-modernization.md) for pins,
compatibility exceptions, upstream sources and validation details.

The core configure checks require OpenSSL 3.5 or newer. Depends supplies 3.5.9
LTS; system builds must provide matching supported headers and libraries.
