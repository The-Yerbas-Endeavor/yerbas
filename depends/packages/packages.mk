packages:=boost openssl libevent zeromq gmp chia_bls backtrace immer
native_packages:=native_cmake

qt_native_packages =
qt_packages = qrencode zlib

wallet_packages=bdb

upnp_packages=miniupnpc

# Native macOS builds use Xcode; obsolete cross/DMG toolchains are retired.
darwin_native_packages =
