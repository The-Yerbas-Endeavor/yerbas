# Qt host tools and Windows libraries must use the same source version.
package=qt5compat
$(package)_version=6.12.0
$(package)_download_path=https://download.qt.io/official_releases/qt/6.12/$($(package)_version)/submodules
$(package)_file_name=qt5compat-everywhere-src-$($(package)_version).tar.xz
$(package)_sha256_hash=78cf1c283795312a7fa31c73eb7f7f556b48374adc484f10ad5a3c0bcb59264e
$(package)_dependencies=qt

$(package)_patches=CVE-2026-101201-0001.patch CVE-2026-101201-0002.patch

define $(package)_preprocess_cmds
  patch -p1 < $($(package)_patch_dir)/CVE-2026-101201-0001.patch && \
  patch -p1 < $($(package)_patch_dir)/CVE-2026-101201-0002.patch
endef

define $(package)_config_cmds
  $(build_prefix)/bin/cmake -S . -B build -G "Unix Makefiles" \
    -DCMAKE_INSTALL_PREFIX=$(host_prefix) \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DQT_BUILD_TESTS=OFF \
    -DQT_BUILD_EXAMPLES=OFF \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_SYSTEM_NAME=Windows \
    -DCMAKE_C_COMPILER="$(host_CC)" \
    -DCMAKE_CXX_COMPILER="$(host_CXX)" \
    -DCMAKE_RC_COMPILER="$(host)-windres" \
    -DQT_HOST_PATH=$(build_prefix) \
    -DCMAKE_FIND_ROOT_PATH=$(host_prefix) \
    -DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
    -DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
    -DCMAKE_PREFIX_PATH=$(host_prefix)
endef

define $(package)_build_cmds
  $(MAKE) -C build
endef

define $(package)_stage_cmds
  DESTDIR=$($(package)_staging_dir) $(build_prefix)/bin/cmake --install build && \
  mkdir -p $($(package)_staging_prefix_dir)/share/licenses/qt5compat && \
  cp -R LICENSES/. $($(package)_staging_prefix_dir)/share/licenses/qt5compat/
endef
