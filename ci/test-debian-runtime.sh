#!/usr/bin/env bash
# Run inside a fresh Debian 13 container, against the downloaded build artifact.
set -euo pipefail
artifact=$(realpath "${1:?artifact directory required}")
logs=$(realpath -m "${2:?log directory required}")
mkdir -p "$logs"
exec > >(tee "$logs/runtime.log") 2>&1
# No Qt runtime or development packages may mask accidental dynamic linkage.
if dpkg-query -W -f='${db:Status-Abbrev} ${binary:Package}\n' | grep -E '^ii .*([Qq]t6|[Qq]t5)'; then
  echo 'Unexpected Qt packages in runtime image'; exit 1
fi
work=$(mktemp -d)
pid=
cleanup() {
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then kill "$pid"; wait "$pid" || true; fi
  cp "$work/data/regtest/debug.log" "$logs/debug.log" 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT
(cd "$artifact" && sha256sum -c SHA256SUMS)
archives=("$artifact"/*.tar.gz)
[[ ${#archives[@]} == 1 ]]
tar -xzf "${archives[0]}" -C "$work"
bin="$work/yerbas-build"
[[ $(find "$bin" -mindepth 1 -maxdepth 1 | wc -l) == 3 ]]
(cd "$bin" && sha256sum -c "$artifact/BINARY-SHA256SUMS")
for name in yerbas-cli yerbasd yerbas-qt; do
  [[ -x "$bin/$name" ]]
  ldd "$bin/$name" | tee "$logs/$name.ldd"
  if grep -Eq 'libQt[56]|not found' "$logs/$name.ldd"; then exit 1; fi
  QT_QPA_PLATFORM=minimal "$bin/$name" -version
 done
mkdir "$work/data"
# Exercise the real XCB graphical backend, wallet initialization and local RPC.
xvfb-run -a "$bin/yerbas-qt" -regtest -datadir="$work/data" \
  -server -listen=0 -dnsseed=0 -connect=0 -upnp=0 -splash=0 \
  >"$logs/gui.log" 2>&1 &
pid=$!
ready=false
for ((i=0; i<90; i++)); do
  kill -0 "$pid" || { cat "$logs/gui.log"; exit 1; }
  if "$bin/yerbas-cli" -regtest -datadir="$work/data" getblockchaininfo >"$logs/blockchain.json" 2>/dev/null; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]]
"$bin/yerbas-cli" -regtest -datadir="$work/data" getwalletinfo >"$logs/wallet.json"
"$bin/yerbas-cli" -regtest -datadir="$work/data" stop
for ((i=0; i<30; i++)); do
  if ! kill -0 "$pid" 2>/dev/null; then wait "$pid"; pid=; echo 'Debian packaged wallet startup and shutdown passed'; exit 0; fi
  sleep 1
done
echo 'Wallet did not shut down cleanly'; exit 1
