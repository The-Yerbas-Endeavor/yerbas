#!/bin/bash
# use testnet settings,  if you need mainnet,  use ~/.yerbascore/yerbasd.pid file instead
yerbas_pid=$(<~/.yerbascore/testnet3/yerbasd.pid)
sudo gdb -batch -ex "source debug.gdb" yerbasd ${yerbas_pid}
