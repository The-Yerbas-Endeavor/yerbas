#!/usr/bin/env bash
# Host-side test: clean Debian receives no package installations, FUSE or network.
set -euo pipefail
artifact=$(realpath "${1:?artifact directory}")
logs=$(realpath -m "${2:?logs directory}")
mkdir -p "$logs"
work=$(mktemp -d)
volume="yerbas-x11-$$"
xserver="yerbas-xvfb-$$"
cleanup() {
  docker rm -f "$xserver" >/dev/null 2>&1 || true
  docker volume rm "$volume" >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
image=debian:13@sha256:9c6e381421d0f48d1b8133e573f33c185ee16cbf505eda9c4a8a4791b25ea8a6
# X server is test infrastructure, never installed in the wallet's container.
printf 'FROM %s\nRUN apt-get update && apt-get install -y --no-install-recommends xvfb\n' "$image" |
  docker build -t yerbas-appimage-xserver - >"$logs/xserver-build.log" 2>&1
docker volume create "$volume" >/dev/null
docker run -d --name "$xserver" --network none -v "$volume:/tmp/.X11-unix" \
  yerbas-appimage-xserver Xvfb :99 -screen 0 1024x768x24 -ac -nolisten tcp >/dev/null
for ((i=0; i<30; i++)); do
  if docker exec "$xserver" test -S /tmp/.X11-unix/X99; then break; fi
  sleep 1
done
docker exec "$xserver" test -S /tmp/.X11-unix/X99
cp -a "$artifact" "$work/artifact"
cat > "$work/run.sh" <<'RUN'
#!/bin/bash
set -euo pipefail
cd /tmp/test
before=$(dpkg-query -W)
(cd artifact && sha256sum -c SHA256SUMS)
archives=(artifact/*.tar.gz)
[[ ${#archives[@]} == 1 ]]
tar -xzf "${archives[0]}"
[[ $(find yerbas-build -mindepth 1 -maxdepth 1 | wc -l) == 3 ]]
(cd yerbas-build && sha256sum -c ../artifact/BINARY-SHA256SUMS)
[[ $(od -An -tx1 -j8 -N3 yerbas-build/yerbas-qt | xargs) == '41 49 02' ]]
! test -e /dev/fuse
! dpkg-query -W -f='${db:Status-Abbrev} ${binary:Package}\n' | grep -E '^ii .*(libqt|libxcb|libxkbcommon|libfuse)'
export HOME=/tmp/test/home
mkdir "$HOME"
for name in yerbas-cli yerbasd yerbas-qt; do ./yerbas-build/$name -version; done
mkdir data
./yerbas-build/yerbas-qt -regtest -datadir=/tmp/test/data -server -listen=0 -connect=0 -dnsseed=0 -upnp=0 -splash=0 >gui.log 2>&1 &
pid=$!
trap 'cat gui.log; cat data/regtest/debug.log 2>/dev/null || true; kill "$pid" 2>/dev/null || true' EXIT
ready=false
for ((i=0; i<90; i++)); do
  kill -0 "$pid"
  if ./yerbas-build/yerbas-cli -regtest -datadir=/tmp/test/data getblockchaininfo 2>/dev/null; then ready=true; break; fi
  sleep 1
done
[[ "$ready" == true ]]
./yerbas-build/yerbas-cli -regtest -datadir=/tmp/test/data getwalletinfo
./yerbas-build/yerbas-cli -regtest -datadir=/tmp/test/data stop
for ((i=0; i<30; i++)); do
  if ! kill -0 "$pid" 2>/dev/null; then
    wait "$pid"
    [[ "$before" == "$(dpkg-query -W)" ]]
    echo 'PASS: packaged AppImage graphical wallet, unchanged clean Debian 13, no extra packages or FUSE'
    exit 0
  fi
  sleep 1
done
exit 1
RUN
# Transfer input by stdin: avoids exposing the host checkout or any user wallet.
tar -czf - -C "$work" . | docker run --rm -i --user 65534:65534 --network none \
  -e DISPLAY=:99 -e QT_QPA_PLATFORM=xcb -e LC_ALL=C.UTF-8 \
  -v "$volume:/tmp/.X11-unix:ro" "$image" \
  bash -c 'mkdir /tmp/test; tar -xz -C /tmp/test; bash /tmp/test/run.sh' \
  >"$logs/runtime.log" 2>&1
cat "$logs/runtime.log"
