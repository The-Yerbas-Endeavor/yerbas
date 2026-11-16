# Berkeley DB 4.8 without administrator privileges

Build only the wallet database dependency in a user-owned directory:

```sh
cd ~/yerbas
sh contrib/build-bdb.sh
./autogen.sh
./configure --with-bdb="$PWD/depends/bdb" [your other configure options]
```

Replace the bracketed text with the options for your build, or omit it. No
system Berkeley DB package, sudo, Qt installation, or full dependency build is
required for this BDB step. A C/C++ compiler, make, patch, tar, curl and SHA-256
tool must already be available. The helper builds only the two static libraries
and installs only headers/libraries into `depends/bdb`. It does not touch wallets.

The default is two build jobs; use `JOBS=4 sh contrib/build-bdb.sh` to change it.
An optional first argument chooses a different installation directory. Set CC,
CXX, CFLAGS and CXXFLAGS if needed to match the application's compiler. This
helper is for native builds; cross builds should use the existing depends recipe.

The download is pinned to Oracle Berkeley DB 4.8.30.NC and the same SHA-256 as
`depends/packages/bdb.mk`. The existing C++ atomic compatibility patch is reused.
The source archive contains read-only files; the helper makes its own extracted
copy writable. Failed build directories are retained under `depends/work` for
inspection; successful temporary build directories are removed. Cached source
archives are verified before every build.

Configure now accepts `--with-bdb=DIR`, or detects BDB 4.8 in the requested
installation prefix and then `depends/bdb` before probing system headers.
It checks the local header version and links a real C++ Db object against the
selected archive. An explicit missing or incompatible directory is an error,
not permission to silently use system Berkeley DB. Existing BDB_CFLAGS/BDB_LIBS
manual overrides remain available. BDB's wallet format stays at 4.8.

The full application still needs its other build dependencies. This helper
neither installs system packages nor changes GUI/headless selection.

## Validation

On Ubuntu 26.04, the helper downloaded and checksum-verified the source, built
both static libraries, and installed into the repository as an unprivileged
user. A compiled BDB 4.8.30 test wrote a temporary database, closed it, reopened
it and read the stored value successfully. Configure checks passed for an
explicit directory, the installation prefix and automatic `depends/bdb`
detection. Missing directories and wrong-version headers were rejected.
Autotools regeneration and generated shell syntax checks passed. No full
Yerbas rebuild or existing-wallet migration was performed.

## Modern compiler warnings

Both the local helper and the depends recipe explicitly compile Berkeley DB's
C sources as GNU C17. GCC 15 defaults to C23, which removed the K&R function
definitions used throughout this legacy library. Choosing its supported C
language mode avoids those default-mode warnings without rewriting database
logic or disabling the old-style-definition warning globally. C++ stays at C++17.
The existing implicit-function-declaration error downgrade remains necessary
for old configure probes; compiler warnings remain visible.

The shared `format-security.patch` changes both transaction allocation error
messages to `__db_errx(env, "%s", TxnAlloc)`, preserving the message while using
a literal format string. Both build paths apply the same patch. Berkeley DB
remains pinned to 4.8.30.NC; these changes do not alter its file format.

After pulling the changes, rerun `sh contrib/build-bdb.sh` to replace the local
libraries with a freshly patched build. The helper always rebuilds from the
checksum-verified archive; no sudo or manual deletion is needed.

Validation on Ubuntu 26.04 / GCC 15.2: a fresh build of both static libraries
completed with zero warnings in the build output, and the C++ write/close/reopen/
read smoke test passed against the new libraries. The depends recipe flag/patch
expansion and helper shell syntax checks also passed.

The local installation ignore rule is anchored to `depends/bdb/` so new patches
in `depends/patches/bdb/` are tracked normally.
