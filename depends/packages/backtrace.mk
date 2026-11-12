package=backtrace
$(package)_version=0b9b49cf4a2c9229fc052d6716e1528b2f23e91a
$(package)_download_path=https://github.com/ianlancetaylor/libbacktrace/archive
$(package)_file_name=$($(package)_version).tar.gz
$(package)_sha256_hash=fabcb6868b3d09734d4c537637dacac0bf8c9aa28e07486de5c6ce2eb749d413

define $(package)_set_vars
$(package)_config_opts=--disable-shared --enable-host-shared --prefix=$(host_prefix)
endef

define $(package)_config_cmds
  cp -f $(BASEDIR)/config.guess $(BASEDIR)/config.sub . && \
  $($(package)_autoconf)
endef

define $(package)_build_cmds
  $(MAKE)
endef

define $(package)_stage_cmds
  $(MAKE) DESTDIR=$($(package)_staging_dir) install
endef

define $(package)_postprocess_cmds
  rm lib/*.la
endef
