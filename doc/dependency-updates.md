# Headless dependency updates

This batch updates the pinned dependencies used by `Yerbas Build and Tests`.
It does not change public consensus parameters or BLS serialization.

| Package | Previous pin | New pin | Upstream |
| --- | --- | --- | --- |
| OpenSSL | 1.0.1k | 3.5.9 (3.5 LTS) | https://openssl-library.org/source/ |
| ZeroMQ | 4.2.3 | 4.3.5 | https://github.com/zeromq/libzmq/releases/tag/v4.3.5 |
| GMP | 6.2.1 | 6.3.0 | https://gmplib.org/list-archives/gmp-announce/2023-July/000050.html |

All three archive SHA-256 values were calculated from upstream downloads.
OpenSSL's value was also compared with its published SHA-256 file.
`depends` checks these hashes before extracting sources. Recipe changes alter
package cache keys; GMP's change also invalidates dependent BLS build packages.

## Recipe changes

OpenSSL uses its modern Configure targets, builds static libraries, and installs
headers, archives, and pkg-config files with `DESTDIR` and `install_dev`.
`--libdir=lib` keeps discovery consistent across hosts. `no-module` avoids a
runtime requirement for separate provider modules. The default provider remains
available in libcrypto. Applications and upstream test binaries are not built;
Yerbas's unit suites remain enabled in CI. The old musl patch and 1.0.x-only
options are no longer applied. Automatic configuration loading stays disabled.
OpenSSL 1.1 and newer manage their own locks and PRNG initialization; application
locking callbacks and Windows screen seeding are restricted to older versions.

ZeroMQ explicitly builds the stable, static API with drafts and CURVE disabled,
as before. The old MinGW <4 workaround and pre-glibc-2.12 thread-name patch are
no longer applied; those platforms predate the supported CI matrix.
GMP retains the existing static/PIC/C++ configuration.

## Validation completed

- OpenSSL 3.5.9 Configure accepted Linux x86_64, Linux ARM64, macOS Intel,
  and MinGW64 targets. This checks configuration, not cross-platform compilation.
- GMP 6.3.0 and ZeroMQ 4.3.5 configured successfully on Ubuntu 26.04.
- The actual depends Makefile expands the new versions and options correctly.
- OpenSSL generated headers were produced without building its libraries.
- Syntax checks against generated OpenSSL 3.5.9 headers passed for util.cpp,
  random.cpp, bip39.cpp, keepass.cpp, wallet/test/crypto_tests.cpp, and
  test/crypto_tests.cpp.
- A full dependency rebuild, link, and runtime tests have not been run. They
  are required before considering this batch verified.

## Manual build and validation

Use the new prefix rather than the older dependency prefix from previous local
builds. Run from the repository root on Linux x86_64:

```sh
make -C depends -j2 HOST=x86_64-pc-linux-gnu NO_QT=1 NO_UPNP=1
./autogen.sh
./configure --prefix="$PWD/depends/x86_64-pc-linux-gnu" \
  --without-gui --without-miniupnpc --disable-bench --enable-wallet --enable-tests
make -j2
python3 ci/run-unit-tests.py src/test/test_yerbas --output test-results-dependency-updates
```

The dependency rebuild is intentional: reusing a binary linked to the previous
libraries does not validate these pins. Hosted CI uses the same recipes on its
six platforms after publication. Existing unrelated legacy test failures must
remain visible. In particular, run crypto, wallet_crypto, bip39, bls, and quorum
suites against the newly linked executable.

## Follow-up migrations

Boost and the local GUI dependency configuration are now updated in the
[local GUI build instructions](local-gui-build.md). The BLS fork remains pinned
to preserve signature and serialization compatibility; Berkeley DB 4.8 remains
pinned for wallet compatibility. CMake, immer, and backtrace updates remain
separate work. The legacy Qt 5.9 source-build path is not modernized; use the
explicit native system-Qt mode for the local GUI.
