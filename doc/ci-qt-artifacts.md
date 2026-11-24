# Qt wallet CI artifacts

The `Yerbas Build and Tests` workflow builds the wallet, daemon, CLI, native unit
suites and Qt wallet tests on every platform in its matrix:

| Artifact platform | Qt source | Wallet entry point |
| --- | --- | --- |
| Ubuntu 22 x86_64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| Ubuntu 24 x86_64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| Ubuntu 26 x86_64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| Debian 13 x86_64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| Ubuntu 24 ARM64 | Pinned static Qt sources from depends | `yerbas-build/yerbas-qt` |
| macOS 15 Intel | Pinned Qt sources from depends | `yerbas-build/Yerbas-Qt.app` |
| Windows x86_64 | Pinned cross-built Qt from depends | `yerbas-build/yerbas-qt.exe` |

Download the matching `yerbas-<platform>-binaries` artifact from a successful
workflow run, then extract the versioned archive inside. Version metadata comes
from `configure.ac` and `build.properties`; the archive also records the commit
and host and includes checksums. Use the artifact matching your OS and CPU.
This matrix does not provide a native Apple Silicon build.

Linux archives contain exactly three real executables in `yerbas-build/`:
`yerbas-cli`, `yerbasd`, and `yerbas-qt`. Qt and its selected plugins are linked
into the wallet; there is no Qt launcher or separate Qt runtime directory.
The wallet links X11/XCB, fontconfig and xkbcommon statically. It uses the
system C/C++ runtimes and needs a compatible display, fonts and keyboard data.

For these Linux builds, `build-info.txt`, `BINARY-SHA256SUMS`, Qt license files and the archive
checksum are alongside the versioned archive in the Actions artifact, not inside
`yerbas-build/`. Release publication must preserve that metadata and licensing
material as separate assets. `BINARY-SHA256SUMS` is checked from inside the
extracted `yerbas-build/` directory. Existing published archives are unchanged
until builds from this packaging change have passed validation and are uploaded.

The macOS application includes its Qt dependencies via `macdeployqt` and is
ad-hoc signed. It requires macOS 15 or newer on Intel and is not notarized or
Developer ID signed. Its archive contains the app bundle, daemon and CLI;
metadata and license notices are kept outside that archive. Windows uses static
Qt and compiler runtimes, with only `yerbasd.exe`, `yerbas-cli.exe` and
`yerbas-qt.exe` in the binary directory. Packaging rejects non-system DLL imports;
notices and checksums remain alongside the archive.

The static Linux builds use the default depends Qt SDK. Its Core5Compat recipe
uses Qt's CMake targets to resolve libraries and static plugin initialization
objects and emits pkg-config metadata for Autotools. macOS uses
`ci/build-native-qt.py` to build the shared Qt SDK and sets `QT_NATIVE_PREFIX`
for configure. Windows depends generates static link metadata while staging Core5Compat.
Autotools reads it from the generated depends prefix. Qt source versions and
archive checksums are pinned in `depends/packages`.

Native test artifacts are tar archives to retain executable modes and library
symlinks. Test jobs run the packaged GUI test executable on each target, using
Qt's minimal platform on Linux and the native macOS platform. The local packaging
unit tests exercise relocation and missing-binary failure; they do not establish
that a real wallet builds or starts. Successful target build and test jobs are
required before treating those platform artifacts as validated.

## Debian 13 CI build

The `debian13` build and test jobs run inside pinned Debian 13 containers on an
x86-64 GitHub-hosted runner. The `yerbas-debian13-binaries` artifact contains a
portable archive with only `yerbas-cli`, `yerbasd`, and `yerbas-qt` in
`yerbas-build/`. Qt is linked into the wallet; Debian's normal system libraries
remain runtime dependencies. Build metadata, checksums, and Qt licensing notices
are provided alongside the archive. No `.deb` installer is generated.

The Debian test job runs the packaged unit and Qt test executables in a separate
Debian 13 container. Release publication should wait for both jobs to pass.

### Debian 13 raw ELF runtime check

CI extracts the Debian build archive into a clean Ubuntu 24.04 runtime with
no desktop library packages installed. Xvfb, fonts and keyboard data come
from separate test infrastructure. The test checks the ELF, starts the wallet
under XCB, exercises regtest wallet and blockchain RPCs, and checks shutdown.
