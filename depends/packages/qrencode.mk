package=qrencode
$(package)_version=4.1.1
$(package)_download_path=https://github.com/fukuchi/libqrencode/archive/refs/tags
$(package)_download_file=v$($(package)_version).tar.gz
$(package)_file_name=$(package)-$($(package)_download_file)
$(package)_sha256_hash=5385bc1b8c2f20f3b91d258bf8ccc8cf62023935df2d2676b5b67049f31a049c

define $(package)_set_vars
$(package)_config_opts=--disable-shared --without-tools --without-tests --disable-dependency-tracking --enable-option-checking
$(package)_config_opts_linux=--with-pic
$(package)_config_opts_android=--with-pic
endef

define $(package)_preprocess_cmds
  autoreconf -fi && \
  cp -f $(BASEDIR)/config.guess $(BASEDIR)/config.sub use
endef

define $(package)_config_cmds
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
