linux_CFLAGS=-pipe
linux_CXXFLAGS=$(linux_CFLAGS) -static-libstdc++

linux_release_CFLAGS=-O2
linux_release_CXXFLAGS=$(linux_release_CFLAGS)

linux_debug_CFLAGS=-O1
linux_debug_CXXFLAGS=$(linux_debug_CFLAGS)

linux_debug_CPPFLAGS=-D_GLIBCXX_DEBUG -D_GLIBCXX_DEBUG_PEDANTIC

ifeq (86,$(findstring 86,$(build_arch)))
# Bake uses i686-pc-linux-gnu, while Debian names its dedicated tools
# i686-linux-gnu. Keep support for builders with the multilib compiler.
i686_linux_CC=gcc -m32
i686_linux_CXX=g++ -m32
i686_linux_AR=ar
i686_linux_RANLIB=ranlib
i686_linux_NM=nm
i686_linux_STRIP=strip
ifneq ($(host_arch),$(build_arch))
ifneq ($(shell command -v i686-linux-gnu-g++ 2>/dev/null),)
i686_linux_CC=i686-linux-gnu-gcc
i686_linux_CXX=i686-linux-gnu-g++
i686_linux_AR=i686-linux-gnu-ar
i686_linux_RANLIB=i686-linux-gnu-ranlib
i686_linux_NM=i686-linux-gnu-nm
i686_linux_STRIP=i686-linux-gnu-strip
endif
endif

x86_64_linux_CC=gcc -m64
x86_64_linux_CXX=g++ -m64
x86_64_linux_AR=ar
x86_64_linux_RANLIB=ranlib
x86_64_linux_NM=nm
x86_64_linux_STRIP=strip
else
i686_linux_CC=$(default_host_CC) -m32
i686_linux_CXX=$(default_host_CXX) -m32
x86_64_linux_CC=$(default_host_CC) -m64
x86_64_linux_CXX=$(default_host_CXX) -m64
endif
