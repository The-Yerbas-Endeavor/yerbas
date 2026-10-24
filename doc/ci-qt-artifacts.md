# Qt wallet CI artifacts

The `Yerbas Build and Tests` workflow builds the wallet, daemon, CLI, native unit
suites and Qt wallet tests on every platform in its matrix:

| Artifact platform | Qt source | Wallet entry point |
| --- | --- | --- |
| Ubuntu 22 x86_64 | Pinned Qt sources from depends | `bin/yerbas-qt` |
| Ubuntu 24 x86_64 | Pinned Qt sources from depends | `bin/yerbas-qt` |
| Ubuntu 26 x86_64 | Ubuntu Qt packages, minimum 6.8 enforced | `bin/yerbas-qt` |
| Ubuntu 24 ARM64 | Pinned Qt sources from depends | `bin/yerbas-qt` |
| macOS 15 Intel | Pinned Qt sources from depends | `Yerbas-Qt.app` |
| Windows x86_64 | Pinned cross-built Qt from depends | See Windows package README |

Download the matching `yerbas-<platform>-binaries` artifact from a successful
workflow run, then extract the versioned archive inside. Version metadata comes
from `configure.ac` and `build.properties`; the archive also records the commit
and host and includes checksums. Use the artifact matching your OS and CPU.
This matrix does not provide a native Apple Silicon build.

Ubuntu 22/24 and ARM64 packages include shared Qt libraries, plugins and licenses.
Keep the extracted directory together and run the launcher under `bin`; it sets
the runtime paths relative to its location. The package README lists the required
Ubuntu desktop libraries. Ubuntu 26 uses the distribution Qt runtime listed in
its package README. These are not distribution-independent Linux binaries.

The macOS application includes its Qt dependencies via `macdeployqt` and is
ad-hoc signed. It requires macOS 15 or newer on Intel and is not notarized or
Developer ID signed. Windows retains the existing DLL/plugin deployment path.

`ci/build-native-qt.py` reads versions and SHA-256 hashes from the existing Qt
recipes in `depends/packages`; downloads must match those hashes before they
are extracted. The native Qt cache is separate for each runner platform and
invalidated when its builder or source recipes change. `QT_NATIVE_PREFIX`
selects that Qt installation in the native `USE_SYSTEM_QT=1` configure path.
It does not replace the pinned Core dependencies or affect cross-builds.

Native test artifacts are tar archives to retain executable modes and library
symlinks. Test jobs run the packaged GUI test executable on each target, using
Qt's minimal platform on Linux and the native macOS platform. The local packaging
unit tests exercise relocation and missing-binary failure; they do not establish
that a real wallet builds or starts. Successful target build and test jobs are
required before treating those platform artifacts as validated.
