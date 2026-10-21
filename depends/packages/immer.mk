package=immer
$(package)_version=v0.9.1
$(package)_download_path=https://github.com/arximboldi/immer/archive
$(package)_download_file=$($(package)_version).tar.gz
$(package)_file_name=$(package)-$($(package)_download_file)
$(package)_sha256_hash=b18b92ba60ec3186dc36ef671d3c2ae542cbb63eb6dc0e258476c6111a67c971
# immer is header-only; do not build upstream examples, tests, or toolchains.
define $(package)_stage_cmds
  mkdir -p $($(package)_staging_prefix_dir)/include && \
  cp -a immer $($(package)_staging_prefix_dir)/include/
endef
