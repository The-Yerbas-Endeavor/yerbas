# Qt host tools and Windows libraries must use the same source version.
package=qt5compat
$(package)_version=6.12.0
$(package)_download_path=https://download.qt.io/official_releases/qt/6.12/$($(package)_version)/submodules
$(package)_file_name=qt5compat-everywhere-src-$($(package)_version).tar.xz
$(package)_sha256_hash=78cf1c283795312a7fa31c73eb7f7f556b48374adc484f10ad5a3c0bcb59264e
$(package)_dependencies=qt

# Qt 6.12.0 already contains both CVE-2026-101201 corrections.

$(package)_config_opts_mingw32 = \
    -DCMAKE_SYSTEM_NAME=Windows \
    -DCMAKE_RC_COMPILER="$(host)-windres" \
    -DQT_HOST_PATH=$(build_prefix) \
    -DCMAKE_FIND_ROOT_PATH=$(host_prefix) \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER

$(package)_config_opts_linux = $(linux_qt_cmake_cross) \
    -DOPENSSL_ROOT_DIR="$(host_prefix)" \
    -DOPENSSL_USE_STATIC_LIBS=ON

ifeq ($(host_os),linux)
$(package)_stage_metadata = && \
  $(linux_qt_pkg_env) CC="$(host_CC)" CXX="$(host_CXX)" \
  python3 $(BASEDIR)/../ci/build-native-qt.py --static-linux --metadata-only \
    --prefix "$(host_prefix)" --staging-prefix "$($(package)_staging_prefix_dir)" \
    --probe-dir "$($(package)_build_dir)/static-link" \
    --cmake "$(build_prefix)/bin/cmake" \
    $(if $(linux_qt_cross),--linux-host "$(host_arch)" --target-pkg-config-libdir "$(linux_qt_target_pc)" \
      $(foreach option,$(linux_qt_cmake_cross),--cmake-arg=$(option)))
else ifeq ($(host_os),mingw32)
$(package)_stage_metadata = && \
  python3 $(BASEDIR)/../ci/build-native-qt.py --metadata-only --windows-host "$(host)" \
    --prefix "$(host_prefix)" --staging-prefix "$($(package)_staging_prefix_dir)" \
    --probe-dir "$($(package)_build_dir)/static-link" \
    --cmake "$(build_prefix)/bin/cmake"
endif

define $(package)_config_cmds
  $(if $(filter linux,$(host_os)),$(linux_qt_pkg_env)) \
  $(build_prefix)/bin/cmake -S . -B build -G "Unix Makefiles" \
    -DCMAKE_INSTALL_PREFIX=$(host_prefix) \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_COMPILER="$(firstword $(host_CC))" \
    -DCMAKE_C_COMPILER_ARG1="$(wordlist 2,99,$(host_CC))" \
    -DCMAKE_CXX_COMPILER="$(firstword $(host_CXX))" \
    -DCMAKE_CXX_COMPILER_ARG1="$(wordlist 2,99,$(host_CXX))" \
    -DBUILD_SHARED_LIBS=OFF \
    -DQT_BUILD_TESTS=OFF \
    -DQT_BUILD_EXAMPLES=OFF \
    -DCMAKE_INSTALL_LIBDIR=lib \
    $($(package)_config_opts) \
    -DCMAKE_PREFIX_PATH=$(host_prefix)
endef

define $(package)_build_cmds
  $(MAKE) -C build
endef

define $(package)_stage_cmds
  DESTDIR=$($(package)_staging_dir) $(build_prefix)/bin/cmake --install build && \
  mkdir -p $($(package)_staging_prefix_dir)/share/licenses/qt5compat && \
  cp -R LICENSES/. $($(package)_staging_prefix_dir)/share/licenses/qt5compat/ $($(package)_stage_metadata)
endef
