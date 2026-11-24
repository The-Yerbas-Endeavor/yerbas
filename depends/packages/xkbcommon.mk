package=xkbcommon
$(package)_version=1.7.0
$(package)_download_path=https://xkbcommon.org/download
$(package)_file_name=libxkbcommon-$($(package)_version).tar.xz
$(package)_sha256_hash=65782f0a10a4b455af9c6baab7040e2f537520caa2ec2092805cdfd36863b247
$(package)_dependencies=native_meson native_ninja native_bison

ifeq ($(linux_qt_cross),1)
# Bison and Ninja run on the build machine. The Meson host machine is the
# machine that will run the resulting library.
$(package)_write_cross_file = printf '%s\n' \
    '[binaries]' "c = [$(foreach arg,$(host_CC),'$(arg)',)]" \
    "ar = '$(host_AR)'" "strip = '$(host_STRIP)'" "pkg-config = 'pkg-config'" \
    '[host_machine]' "system = 'linux'" \
    "cpu_family = '$(if $(filter i686,$(host_arch)),x86,$(host_arch))'" \
    "cpu = '$(host_arch)'" "endian = 'little'" \
    '[properties]' 'needs_exe_wrapper = true' \
    "pkg_config_libdir = [$(foreach dir,$(subst :, ,$(linux_qt_target_pc)),'$(dir)',)]" \
    > yerbas-cross.ini &&
$(package)_cross_option = --cross-file yerbas-cross.ini
endif

define $(package)_config_cmds
  $($(package)_write_cross_file) \
  $(linux_qt_pkg_env) PATH="$(build_prefix)/bin:$(PATH)" CC="$(host_CC)" \
    $(build_prefix)/bin/meson setup build $($(package)_cross_option) --prefix="$(host_prefix)" --libdir=lib --buildtype=release \
      --default-library=static -Db_staticpic=true -Denable-x11=true \
      -Denable-tools=false -Denable-wayland=false -Denable-xkbregistry=false \
      -Denable-bash-completion=false -Dxkb-config-root=/usr/share/X11/xkb \
      -Dx-locale-root=/usr/share/X11/locale
endef

define $(package)_build_cmds
  $(build_prefix)/bin/meson compile -C build -j 2
endef

define $(package)_stage_cmds
  DESTDIR=$($(package)_staging_dir) $(build_prefix)/bin/meson install -C build --no-rebuild && \
  mkdir -p $($(package)_staging_prefix_dir)/share/licenses/xkbcommon && \
  cp LICENSE $($(package)_staging_prefix_dir)/share/licenses/xkbcommon/
endef
