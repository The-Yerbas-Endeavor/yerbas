# Local Linux GUI build: Qt 6

The native Linux depends build compiles pinned static Qt 6.12.0, including
Core5Compat, the XCB platform plugin and its desktop libraries. Bake can package the resulting
`src/qt/yerbas-qt` executable directly. System Qt 6.8 or newer is also supported
with `USE_SYSTEM_QT=1`. Use `NO_QT=1` for a headless depends build.
See [CI artifacts](ci-qt-artifacts.md) for the release workflow's packaging.

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

Allow at least 10 GB of free disk space for the build. Install the build tools
and XCB development libraries on Debian 13:

```sh
sudo apt-get install build-essential autoconf automake libtool pkg-config \
  curl ca-certificates perl python3 bsdextrautils xz-utils bzip2 \
  libbrotli-dev \
  libfontconfig1-dev libx11-xcb-dev libxcb1-dev libxcb-cursor-dev \
  libxcb-icccm4-dev libxcb-image0-dev libxcb-keysyms1-dev libxcb-util-dev \
  libxcb-randr0-dev libxcb-render0-dev libxcb-render-util0-dev \
  libxcb-shape0-dev libxcb-shm0-dev libxcb-sync-dev libxcb-xfixes0-dev \
  libxcb-xkb-dev libxkbcommon-dev libxkbcommon-x11-dev
```

Qt's `xcb_syslibs` test checks the XCB extension headers and libraries together.
An installation with only `libxcb1-dev` can find `XCB::XCB` and still fail
`TEST_xcb_syslibs`. The Qt recipes allow native pkg-config discovery for these
system dependencies. If the test fails, check the Qt build's
`CMakeFiles/CMakeConfigureLog.yaml` and confirm that the extension development
packages and `xkbcommon-x11` are visible to pkg-config.

From a clean Yerbas checkout:

```sh
make -C depends -j2
./autogen.sh
./configure --prefix="$PWD/depends/$(cd depends && ./config.guess)" --with-gui=qt6
make -j2
```

On an existing checkout, clean the application objects before switching Qt
SDKs. The pinned depends SDK provides the Qt development libraries, `moc`,
`uic`, `rcc` and Linguist tools. The system Qt option requires corresponding Qt
6.8+ development packages and tools separately. See
[Berkeley DB instructions](berkeley-db-local.md) for the independent BDB-only build.

Depends also supplies OpenSSL 3.5.9 LTS. System builds need OpenSSL 3.5 or newer.
With tests enabled, run the core and GUI test binaries after building:

```sh
python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results-gui-deps
QT_QPA_PLATFORM=minimal src/qt/test/test_yerbas-qt
```

## Cross-compiling on Linux

Bake's `i686-pc-linux-gnu` and `aarch64-linux-gnu` targets use the same
static Qt GUI build. Depends builds and runs matching native Qt tools and
uses the target compiler for Qt, xkbcommon, and the link probe. The examples
below use Debian 13 and also describe the Debian/Ubuntu multiarch layout.
The target architecture package names on those distributions are `i386` and
`arm64`.

For another distribution or a separate target SDK, export the colon-separated
`LINUX_QT_TARGET_PKG_CONFIG_LIBDIR` before running depends or Bake. Point it at
target-only pkg-config directories whose metadata resolves to actual target
paths on the builder. Supply `LINUX_QT_TARGET_LIBRARY_PATH` and
`LINUX_QT_TARGET_INCLUDE_PATH` if CMake needs additional target search paths.
Use the compiler and static development archives for the same target ABI.
These settings apply only to Linux GUI cross builds.

Install the appropriate compiler and libc development sysroot. For i686,
`g++-i686-linux-gnu libc6-dev-i386-cross` works alongside the AArch64 tools.
Yerbas also supports `g++-multilib` with `gcc -m32` and `g++ -m32` for
i686. For AArch64 use `g++-aarch64-linux-gnu libc6-dev-arm64-cross`.

Enable Debian multiarch and install the target desktop development packages
and their static archives. Run the following for each architecture you build:

```sh
arch=i386                         # Use arm64 for AArch64.
set --
sudo dpkg --add-architecture "$arch"
sudo apt-get update
for pkg in libfontconfig-dev libbrotli-dev libx11-xcb-dev libxcb1-dev \
  libxcb-cursor-dev libxcb-icccm4-dev libxcb-image0-dev libxcb-keysyms1-dev \
  libxcb-util-dev libxcb-randr0-dev libxcb-render0-dev libxcb-render-util0-dev \
  libxcb-shape0-dev libxcb-shm0-dev libxcb-sync-dev libxcb-xfixes0-dev \
  libxcb-xkb-dev libxau-dev libxdmcp-dev; do
  set -- "$@" "$pkg:$arch"
done
sudo apt-get install "$@"
```

Select the target in Bake or run the usual build steps with its host triplet:

```sh
host=i686-pc-linux-gnu            # Or aarch64-linux-gnu.
make -C depends -j2 HOST="$host"
./autogen.sh
./configure --prefix="$PWD/depends/$host" --with-gui=qt6
make -j2
```

Check the unstripped program on the build host. Use `aarch64` for the ARM64
build. The checker verifies the ELF architecture, static XCB plugin symbol and
remaining shared-library requirements without executing the cross binary:

```sh
python3 ci/build-native-qt.py --check-linux-elf src/qt/yerbas-qt --linux-host i686
readelf -dW src/qt/yerbas-qt
readelf --version-info src/qt/yerbas-qt
```

i686 requires a 32-bit kernel or 32-bit compatibility support on x86-64 and
a compatible 32-bit Linux loader and runtime. AArch64 requires the AArch64
loader and runtime. Check the glibc and compiler-runtime symbol versions
against the destination when targeting older distributions.

## Linux runtime verification

On the destination, run these checks against a copy of the executable:

```sh
readelf -d ./yerbas-qt | grep -E 'NEEDED|RPATH|RUNPATH'
ldd ./yerbas-qt
QT_QPA_PLATFORM=xcb ./yerbas-qt -version
```

The static Qt build should show no `libQt6*.so`, missing libraries, or build-host
runtime paths. The version command initializes the XCB platform, so run it
inside an X11 or XWayland session, or under `xvfb-run -a` for a smoke test.
A normal launch should display the wallet.

The raw ELF uses the host's compatible CPU, Linux loader, glibc, compiler
runtime, X11 or XWayland display, fonts and keyboard data. It statically
links X11/XCB, xkbcommon, fontconfig and their desktop library dependencies.
The builder needs the static archives from its development packages. Depends
builds the pinned xkbcommon archives because Debian ships shared xkbcommon in
its development packages. Depends supplies Meson, Ninja and Bison for that
build. The final link probe rejects other shared libraries.
HTTPS features use the system CA certificates.

Mint 22.3 uses the Ubuntu 24.04 base. Static Qt does not lower the system ABI
baseline. Check the actual Debian-built executable on the destination. For
example, inspect its highest glibc symbol version with
`readelf --version-info ./yerbas-qt | grep -oE 'GLIBC_[0-9.]+' | sort -Vu | tail -1`.
If a build requires a newer ABI than the destination provides, use a
destination-compatible toolchain/sysroot or build against Ubuntu 24.04.

## Distributing static Qt builds

The depends prefix contains Qt license texts under `share/licenses`. Preserve
the relevant license texts, copyright notices, and third-party attributions
when distributing. Bake's executable archive alone does not satisfy those
obligations. For LGPLv3 distribution, provide the required corresponding Qt
source, including any changes, and the application object files or equivalent
materials and instructions that let recipients relink and run the application
with a modified Qt. Provide installation information where required and allow
the reverse engineering needed to debug modifications. Alternatively, use a
compatible GPL distribution or a commercial Qt license that covers the
distribution. Review the licenses of the actual modules and third-party code
included in the build, including the distribution packages that supply the
static desktop archives. See [Qt licensing](https://www.qt.io/licensing/open-source-lgpl-obligations).
