"""Assemble a separate sealed upgrade from public source and a verified collector."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def assemble(source, collector, destination):
    source, collector, destination = map(Path, (source, collector, destination))
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination must not exist')
    manifest = json.loads((source / 'INSTALL-SHA256.json').read_text())
    payload = {}
    for name, digest in manifest.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe manifest path')
        path = collector if name == 'payload/collector.so' else source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError('Regular source file required: ' + name)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Pinned file differs: ' + name)
        payload[name] = raw
    # Validate everything before creating the output; publish only a complete package.
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix='.phase-package-') as temp:
        staged = Path(temp) / 'package'
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns('__pycache__'))
        for name, raw in payload.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        if destination.exists() or destination.is_symlink():
            raise ValueError('Destination appeared during assembly')
        staged.rename(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collector', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    assemble(Path(__file__).resolve().parent, args.collector, args.destination)
