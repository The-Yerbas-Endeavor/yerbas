# Local Linux GUI build with modern dependencies

The existing checkout remains on `dev`. Use `USE_SYSTEM_QT=1` for the local
Ubuntu desktop build. It uses the installed Qt 5.15 development packages and
system desktop libraries, while building the remaining pinned dependencies.
Qt 5.15.18 and its moc/uic/rcc/lrelease/lupdate tools were found on this machine.
The older Qt 5.9 source recipe is unchanged and is not the recommended local
build path. This is a native Linux configuration, not a portable release bundle.

| Dependency | Previous | Local GUI configuration |
| --- | --- | --- |
| Boost | 1.70.0 | pinned 1.90.0 |
| Qt | source recipe 5.9.6 | installed system Qt 5.15.18 |
| protobuf/protoc | 2.6.1 | pinned 3.20.3, matching compiler and runtime |
| libqrencode | 3.4.4 | pinned 4.1.1 |
| zlib | 1.2.11 | pinned 1.3.2 |

Protobuf 3.20.3 is an incremental compatibility update for the existing payment
request implementation and Autotools build, not the latest protobuf generation.
The earlier OpenSSL 3.5.9, ZeroMQ 4.3.5, and GMP 6.3.0 updates are also included.
BLS serialization and public consensus parameters are unchanged.

## Changes

Boost.System is detected with a link test that permits its header-only form.
The Boost build no longer requests a System library and uses C++17. Obsolete
filesystem calls in configuration, RPC, and wallet handling were replaced.
Qt filename conversion uses public Qt UTF-8/native-wide-string methods instead
of Boost's private codecvt class; a Unicode regression case was added to the
existing GUI compatibility tests.

The native Qt mode skips the old Qt/X11/font recipes and enables system
pkg-config discovery only for this explicit mode. It leaves the compiler,
protobuf, OpenSSL, Boost, and other dependency prefix settings in place. The
mode participates in the final prefix cache identity, so changing modes
regenerates the installed prefix. Combining it with NO_QT or cross compilation
is rejected. Hosted headless CI continues to use NO_QT=1.

The protobuf recipes keep protoc and runtime versions synchronized, install
only the required native compiler and target library/headers, and avoid an
unnecessary zlib dependency. QR encoding uses the official source tag and
regenerates its configure script. zlib no longer applies the obsolete macOS
fdopen patch. All changed source archive hashes were verified locally.

## Build manually

These commands build dependencies and the GUI, daemon, CLI, and enabled tests.
They deliberately clean old object files because objects compiled with Boost
1.70 must not be reused with Boost 1.90. They do not remove wallet data.

```bash
cd /home/anno/Code/yerbas
make -C depends -j2 HOST=x86_64-pc-linux-gnu USE_SYSTEM_QT=1 NO_UPNP=1
make clean
./autogen.sh
./configure --prefix="$PWD/depends/x86_64-pc-linux-gnu" \
  --with-gui=qt5 --with-qrencode --without-miniupnpc \
  --disable-bench --enable-wallet --enable-tests
make -j2
```

Do not reuse the earlier dependency prefix under Documents/Codex. If starting
from an unconfigured checkout, omit `make clean` when there is no Makefile.
On a different Ubuntu installation, install Qt 5 development packages and tools
(`qtbase5-dev`, `qtbase5-dev-tools`, `qttools5-dev-tools`) in addition to the
normal compiler, Autotools, pkg-config, Perl, Python, and CMake prerequisites.
The system Qt mode intentionally relies on the OS package versions.

After the build:

```bash
python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results-gui-deps
QT_QPA_PLATFORM=offscreen src/qt/test/test_yerbas-qt
```

Run `src/qt/yerbas-qt` from the graphical desktop when ready. Runtime GUI and
wallet behavior have not been tested with this dependency combination yet.
Existing unrelated legacy unit-test failures remain visible.

## Checks completed without a full build

- Boost 1.90 archive SHA-256 matches the upstream metadata.
- protobuf 3.20.3, QR encoding 4.1.1, and zlib 1.3.2 configure successfully.
- The updated Boost.System Autoconf macro accepts the installed Boost 1.90
  without a libboost_system. A static filesystem/thread/chrono link and run pass.
- Native Qt and headless package lists select the expected dependencies.
  Generated config.site discovers system Qt only in the requested mode.
  Incompatible mode/cross-build combinations fail as intended.
- Syntax checks pass for util.cpp, rpc/protocol.cpp, wallet/db.cpp,
  qt/guiutil.cpp, qt/paymentrequestplus.cpp, qt/paymentserver.cpp, and
  qt/test/compattests.cpp against the updated Boost/Qt/protobuf/OpenSSL headers.
- Matching protoc generates the payment-request C++ bindings successfully.
- The actual GUI filename-conversion functions pass empty, ASCII, accented,
  Chinese, and emoji roundtrips in an isolated compiled check.
- Diff whitespace checks pass.

No full dependency or application build was launched. Full compilation, linking,
GUI startup, and the integrated unit/GUI test executables still require the
manual build above.

## Upstream references

- https://www.boost.org/releases/1.90.0/
- https://download.qt.io/archive/qt/5.15/5.15.18/submodules/
- https://github.com/protocolbuffers/protobuf/releases/tag/v3.20.3
- https://github.com/fukuchi/libqrencode/releases/tag/v4.1.1
- https://zlib.net/

## Asset viewer follow-up

See [asset-viewer-updates.md](asset-viewer-updates.md) for the new details/image viewer, asset model fixes, configure minimums and protoc compatibility check, focused test results, and manual wallet checks. Regenerate with `./autogen.sh`; the new Qt tests run as part of `test_yerbas-qt`.
