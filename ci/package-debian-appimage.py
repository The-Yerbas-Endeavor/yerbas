#!/usr/bin/env python3
"""Package the static-Qt Debian executable plus its system GUI dependencies."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser()
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--runtime', type=Path, required=True)
p.add_argument('--icon', type=Path, required=True)
p.add_argument('--notices', type=Path, required=True)
a = p.parse_args()
a.binary = a.binary.resolve()
a.notices.mkdir(parents=True, exist_ok=True)
# glibc and the ELF loader remain supplied by the supported Debian 13 host.
exclude = re.compile(r'^(ld-linux.*|lib(c|m|pthread|dl|rt|resolv|util)\.so\..*)$')
with tempfile.TemporaryDirectory(prefix='yerbas-appimage-') as temp:
    root = Path(temp) / 'AppDir'
    lib = root / 'usr/lib'
    lib.mkdir(parents=True)
    (root / 'usr/bin').mkdir()
    shutil.copy2(a.binary, root / 'usr/bin/yerbas-qt')
    pending = [a.binary]
    copied = {}
    while pending:
        binary = pending.pop()
        result = subprocess.check_output(['ldd', str(binary)], text=True)
        if 'not found' in result:
            raise RuntimeError(result)
        for soname, path in re.findall(r'^\s*(\S+) => (/\S+)', result, re.M):
            if exclude.match(soname) or soname in copied:
                continue
            if soname.startswith('libQt'):
                raise RuntimeError('This package requires the static-Qt Debian build')
            shutil.copy2(path, lib / soname)
            copied[soname] = path
            pending.append(Path(path))
    # Include a fallback font so minimal hosts can render text without font packages.
    fonts = root / 'usr/share/fonts'
    fonts.mkdir(parents=True)
    shutil.copy2('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', fonts)
    (root / 'fonts.conf').write_text('''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig><dir prefix="relative">usr/share/fonts</dir><dir>/usr/share/fonts</dir>
<cachedir prefix="xdg">fontconfig</cachedir></fontconfig>
''')
    (root / 'AppRun').write_text('''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export LD_LIBRARY_PATH="$root/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export FONTCONFIG_FILE="$root/fonts.conf"
exec "$root/usr/bin/yerbas-qt" "$@"
''')
    (root / 'AppRun').chmod(0o755)
    shutil.copy2(a.icon, root / 'yerbas.png')
    (root / 'yerbas.desktop').write_text('[Desktop Entry]\nType=Application\nName=Yerbas Core\nExec=yerbas-qt\nIcon=yerbas\nCategories=Office;Finance;\n')
    # Preserve the installed Debian copyright notices for all bundled libraries.
    packages = {'fonts-dejavu-core'}
    for path in copied.values():
        owners = subprocess.check_output(['dpkg-query', '-S', str(Path(path).resolve())], text=True)
        packages.update(line.split(': /')[0] for line in owners.splitlines())
    for package in sorted(packages):
        name = package.split(':')[0]
        notice = Path('/usr/share/doc') / name / 'copyright'
        if not notice.exists():
            raise RuntimeError(f'Missing copyright notice for {package}')
        shutil.copy2(notice, a.notices / (name + '-copyright'))
    (a.notices / 'bundled-libraries.txt').write_text('\n'.join(f'{k}: {v}' for k, v in sorted(copied.items())) + '\n')
    squash = Path(temp) / 'payload.squashfs'
    subprocess.run(['mksquashfs', str(root), str(squash), '-noappend', '-all-root', '-comp', 'gzip', '-processors', '2'], check=True)
    output = Path(temp) / 'yerbas-qt'
    with output.open('wb') as f:
        f.write(a.runtime.read_bytes())
        with squash.open('rb') as payload:
            shutil.copyfileobj(payload, f)
    output.chmod(0o755)
    # A type-2 AppImage retains the official ELF magic marker.
    assert output.read_bytes()[8:11] == b'AI\x02'
    shutil.copy2(output, a.binary)
