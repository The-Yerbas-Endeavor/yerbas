For a BDB-only build without sudo or Qt, run `sh contrib/build-bdb.sh` from
the repository root. See [local Berkeley DB instructions](../doc/berkeley-db-local.md).

Native Linux builds compile the pinned static Qt 6 SDK by default. See the
[local GUI build instructions](../doc/local-gui-build.md) for XCB build
dependencies, runtime checks, and distribution requirements. Use
`USE_SYSTEM_QT=1` to select an installed Qt 6.8+ SDK, or `NO_QT=1` for a headless
build. Native macOS uses an installed SDK. The Linux-to-MinGW build uses pinned
Qt and matching host tools. See [Windows builds](../doc/build-windows.md).

For the current headless CI dependency pins, validation status, and manual
rebuild commands, see [dependency updates](../doc/dependency-updates.md).

### Usage

To build dependencies for the native Linux graphical wallet:

    make -j10

This builds static Qt. `make -j10 USE_SYSTEM_QT=1` selects an installed SDK.

To build headless dependencies for the current arch+OS:

    make -j10 NO_QT=1

To build for another arch/OS:

    make NO_QT=1 HOST=host-platform-triplet

For example:

    make NO_QT=1 HOST=x86_64-w64-mingw32 -j4

A prefix will be generated that's suitable for plugging into Yerbas's
configure. In the above example, a dir named x86_64-w64-mingw32 will be
created. To use it for Yerbas:

    ./configure --prefix=`pwd`/depends/x86_64-w64-mingw32

Common `host-platform-triplets` for cross compilation are:

- `i686-w64-mingw32` for Win32
- `x86_64-w64-mingw32` for Win64
- `arm-linux-gnueabihf` for Linux ARM 32 bit
- `aarch64-linux-gnu` for Linux ARM 64 bit
- `riscv32-linux-gnu` for Linux RISC-V 32 bit
- `riscv64-linux-gnu` for Linux RISC-V 64 bit

No other options are needed, the paths are automatically configured.

Install the required dependencies: Ubuntu & Debian
--------------------------------------------------

For macOS, build natively with Xcode command-line tools. The old cross compiler
and DMG packaging stack are retired. CI uses macOS 15 Intel.

For Win32/Win64 cross compilation:

- see [build-windows.md](../doc/build-windows.md#cross-compilation-for-ubuntu-and-windows-subsystem-for-linux)

For linux (including i386, ARM) cross compilation:

    sudo apt-get install curl g++-aarch64-linux-gnu g++-4.8-aarch64-linux-gnu gcc-4.8-aarch64-linux-gnu binutils-aarch64-linux-gnu g++-arm-linux-gnueabihf g++-4.8-arm-linux-gnueabihf gcc-4.8-arm-linux-gnueabihf binutils-arm-linux-gnueabihf g++-4.8-multilib gcc-4.8-multilib binutils-gold bsdmainutils

For linux RISC-V 64-bit cross compilation (there are no packages for 32-bit):

    sudo apt-get install curl g++-riscv64-linux-gnu binutils-riscv64-linux-gnu

RISC-V known issue: gcc-7.3.0 and gcc-7.3.1 result in a broken `test_yerbas` executable (see https://github.com/bitcoin/bitcoin/pull/13543),
this is apparently fixed in gcc-8.1.0.

Dependency Options:
The following can be set when running make: make FOO=bar

    SOURCES_PATH: downloaded sources will be placed here
    BASE_CACHE: built packages will be placed here
    FALLBACK_DOWNLOAD_PATH: If a source file can't be fetched, try here before giving up
    USE_SYSTEM_QT: Use installed Qt 6.8+ instead of building Qt (default on native macOS)
    NO_QT: Don't download/build/cache qt and its dependencies
    NO_WALLET: Don't download/build/cache libs needed to enable the wallet
    NO_UPNP: Don't download/build/cache packages needed for enabling upnp
    DEBUG: disable some optimizations and enable more runtime checking
    HOST_ID_SALT: Optional salt to use when generating host package ids
    BUILD_ID_SALT: Optional salt to use when generating build package ids

If some packages are not built, for example `make NO_WALLET=1`, the appropriate
options will be passed to Yerbas Core's configure. In this case, `--disable-wallet`.

Additional targets:

    download: run 'make download' to fetch all sources without building them
    download-osx: fetch native macOS sources (macOS builders only)
    download-win: run 'make download-win' to fetch all sources needed for win builds
    download-linux: run 'make download-linux' to fetch all sources needed for linux builds

### Other documentation

- [description.md](description.md): General description of the depends system
- [packages.md](packages.md): Steps for adding packages

