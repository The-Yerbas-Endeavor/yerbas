packages:=boost openssl libevent zeromq gmp chia_bls backtrace immer
native_packages:=native_cmake

qt_native_packages =
qt_packages = qrencode zlib

wallet_packages=bdb

upnp_packages=miniupnpc

# Legacy Python DMG packaging is retired; native macOS builds need no packaging tools.
darwin_native_packages =

ifneq ($(build_os),darwin)
darwin_native_packages += native_cctools native_cdrkit native_libdmg-hfsplus
endif
