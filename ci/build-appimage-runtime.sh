#!/usr/bin/env bash
# Official type-2 runtime, with only default extraction behavior changed.
set -euo pipefail
out=$(realpath -m "${1:?output directory}")
mkdir -p "$out"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
commit=fedfad51acc2860b2916a1eef32ba4a500ff31ef
git clone https://github.com/AppImage/type2-runtime.git "$work/source"
git -C "$work/source" checkout --detach "$commit"
python3 - "$work/source/src/runtime/runtime.c" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
s = p.read_text()
old = 'if (getenv("APPIMAGE_EXTRACT_AND_RUN") != NULL || (arg && strcmp(arg, "appimage-extract-and-run") == 0)) {'
assert s.count(old) == 1
p.write_text(s.replace(old, 'if (1) { /* Yerbas: always extract; no FUSE installation required. */'))
PY
sed 's|^FROM alpine:3.21$|FROM alpine:3.21@sha256:bc21487101ae47172509130ee1092cc273a831968d64b617776d1f69c81e42ab|' "$work/source/scripts/docker/Dockerfile" > "$work/source/Dockerfile"
cat >> "$work/source/Dockerfile" <<'DOCKER'
COPY . /runtime
WORKDIR /runtime
RUN echo 'Yerbas-no-fuse-fedfad51' > src/runtime/version && bash scripts/build-runtime.sh
DOCKER
image=yerbas-appimage-runtime:fedfad51
# stdin works with local and remote Docker daemons.
tar -czf - -C "$work/source" . | docker build -t "$image" -
docker run --rm --network none "$image" cat /runtime/out/runtime-x86_64 > "$out/runtime-x86_64"
chmod +x "$out/runtime-x86_64"
cp "$work/source/LICENSE" "$out/LICENSE-AppImage-runtime"
printf '%s\n' "$commit; default extract-and-run enabled" > "$out/runtime-source.txt"
(cd "$out" && sha256sum runtime-x86_64 > SHA256SUMS)
