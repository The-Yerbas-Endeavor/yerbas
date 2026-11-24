package=native_meson
$(package)_version=1.7.0
$(package)_download_path=https://github.com/mesonbuild/meson/releases/download/$($(package)_version)
$(package)_file_name=meson-$($(package)_version).tar.gz
$(package)_sha256_hash=08efbe84803eed07f863b05092d653a9d348f7038761d900412fddf56deb0284

define $(package)_stage_cmds
  mkdir -p $($(package)_staging_prefix_dir)/bin $($(package)_staging_prefix_dir)/share/meson && \
  cp -R meson.py mesonbuild COPYING $($(package)_staging_prefix_dir)/share/meson/ && \
  ln -s ../share/meson/meson.py $($(package)_staging_prefix_dir)/bin/meson
endef
