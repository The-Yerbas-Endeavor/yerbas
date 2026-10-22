# Windows Qt wallet builds

GitHub Actions cross-compiles the Windows x86_64 Qt wallet from Linux using the
existing depends and Autotools build. The Windows job in
`.github/workflows/build.yaml` uses Ubuntu 26.04 and MinGW's POSIX-thread compiler.
Matching Qt 6.12.0 Linux tools and Windows shared libraries are built from pinned
sources. The wallet includes the existing asset viewer.

## GitHub build and download

Push to dev or manually run **Yerbas Build and Tests**. Windows selects GUI
dependencies and `--with-gui=qt6`; other platform jobs retain headless builds.
The `yerbas-win64-binaries` artifact contains a ZIP with `bin/yerbas-qt.exe`, daemon,
CLI, required DLLs/plugins, checksums, licenses and build information. Extract the
whole ZIP and launch `bin/yerbas-qt.exe`. Packaging fails on missing non-system
DLLs or required plugins.

The Windows test job runs every enabled core suite, Qt tests including the asset
viewer, and checks that the wallet version dialog opens. Logs are retained on
failure. The version-dialog check does not validate transactions or asset usage.

## Equivalent manual Linux cross-build

GitHub is the primary build route. For a manual build, install the same tools
listed in the workflow, including the POSIX MinGW compiler pair. Do not reuse
native Linux object files: run `make distclean` before switching an already
configured checkout, preserving any local configuration first. Build dependencies
and the application without sudo.

```bash
make -C depends -j2 HOST=x86_64-w64-mingw32 NO_UPNP=1
./autogen.sh
./configure --prefix="$PWD/depends/x86_64-w64-mingw32" \
  --with-gui=qt6 --with-qrencode --with-qtdbus=no \
  --without-miniupnpc --disable-bench --enable-wallet --enable-tests
make -j2
python3 contrib/windeploy/package.py --depends depends/x86_64-w64-mingw32 \
  --output windows-package --tests-output windows-tests
```

Packaging output directories must be empty. GitHub additionally creates the ZIP
and checksums. Native Linux GUI builds still use system Qt; Windows builds need
matching host tools from depends rather than the system's Qt version.

## Validation status

Qt host configuration and focused package checks pass locally. Complete Windows
compilation, packaging and runtime tests require the hosted run. No complete local
Windows build was launched for this change.

Upstream references: [cross-compilation](https://doc.qt.io/qt-6/cross-compiling-qt.html)
and [Windows](https://doc.qt.io/qt-6/windows.html). Ubuntu's MinGW compiler is
Yerbas source-build coverage, not a claim that it matches Qt's officially tested
binary-distribution toolchain.
