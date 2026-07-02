#!/usr/bin/env bash
set -euo pipefail

SVG="share/pixmaps/yerbas_logo.svg"
PIXMAPS="share/pixmaps"

if [ ! -f "$SVG" ]; then
    echo "ERROR: Cannot find $SVG"
    exit 1
fi

mkdir -p "$PIXMAPS"

echo "Generating Yerbas icons..."

for size in 16 22 24 32 48 64 128 256; do
    inkscape "$SVG" \
        --export-type=png \
        --export-filename="$PIXMAPS/yerbas${size}.png" \
        -w "$size" -h "$size"

    cp "$PIXMAPS/yerbas${size}.png" \
       "$PIXMAPS/yerbas-HighContrast-${size}.png"

    echo "  ✓ ${size}x${size}"
done

echo "Generating horizontal logo..."

inkscape "$SVG" \
    --export-type=png \
    --export-filename="$PIXMAPS/yerbas_logo_horizontal.png" \
    -w 512

echo "Installing icons..."

sudo install -Dm644 "$PIXMAPS/yerbas128.png" \
    /usr/share/icons/hicolor/128x128/apps/yerbas128.png

sudo install -Dm644 "$PIXMAPS/yerbas256.png" \
    /usr/share/icons/hicolor/256x256/apps/yerbas128.png

sudo gtk-update-icon-cache -f /usr/share/icons/hicolor
sudo update-desktop-database /usr/share/applications

echo
echo "Done."
echo "Now rebuild Yerbas:"
echo "  make -j\$(nproc)"
