package=miniupnpc
$(package)_version=2.3.3
$(package)_download_path=https://github.com/miniupnp/miniupnp/releases/download/miniupnpc_$(subst .,_,$($(package)_version))
$(package)_file_name=$(package)-$($(package)_version).tar.gz
$(package)_sha256_hash=d52a0afa614ad6c088cc9ddff1ae7d29c8c595ac5fdd321170a05f41e634bd1a
$(package)_patches=dont_leak_info.patch const-url-parsing.patch

define $(package)_set_vars
# Unix make moved the archive into build/; Makefile.mingw retains the root target.
$(package)_library=$(if $(filter mingw32,$(host_os)),libminiupnpc.a,build/libminiupnpc.a)
$(package)_build_opts=CC="$($(package)_cc)"
$(package)_build_opts_darwin=LIBTOOL="$($(package)_libtool)"
$(package)_build_opts_mingw32=-f Makefile.mingw
$(package)_build_env+=CFLAGS="$($(package)_cflags) $($(package)_cppflags)" AR="$($(package)_ar)"
endef

define $(package)_preprocess_cmds
  patch -p1 < $($(package)_patch_dir)/dont_leak_info.patch && \
  patch -p1 < $($(package)_patch_dir)/const-url-parsing.patch
endef

define $(package)_build_cmds
	$(MAKE) $($(package)_library) $($(package)_build_opts)
endef

define $(package)_stage_cmds
	mkdir -p $($(package)_staging_prefix_dir)/include/miniupnpc $($(package)_staging_prefix_dir)/lib &&\
	install include/*.h $($(package)_staging_prefix_dir)/include/miniupnpc &&\
	install $($(package)_library) $($(package)_staging_prefix_dir)/lib
endef
