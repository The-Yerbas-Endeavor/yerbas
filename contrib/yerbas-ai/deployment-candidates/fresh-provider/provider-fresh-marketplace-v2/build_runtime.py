"""Build public runtime staging only. Never reads installed credentials or state."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import shutil

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / 'provider-direct-collector-candidate-v1'


def checked(base, name, expected):
    relative = Path(name)
    if relative.is_absolute() or '..' in relative.parts or str(relative) != name:
        raise ValueError('Unsafe source path')
    path = base / relative
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError('Source symlink refused')
        if component == base:
            break
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Source hash mismatch: ' + name)
    if path.suffix == '.py':
        compile(raw, name, 'exec')
    return raw


def build(destination):
    destination = Path(destination)
    if os.path.lexists(destination):
        raise ValueError('Existing destination preserved')
    pins = json.loads((SOURCE / 'INSTALL-SHA256.json').read_text())
    payload = json.loads((SOURCE / 'PAYLOAD.json').read_text())
    files = {}
    runtime = {}
    for name in ('provider_executor.py', 'measurement_policy.py', 'direct_policy.py', 'bootstrap.py'):
        runtime[name] = checked(SOURCE, name, pins[name])
    runtime['direct_router.py'] = (ROOT / 'direct_router.py').read_bytes()
    compile(runtime['direct_router.py'], 'direct_router.py', 'exec')
    runtime['RUNTIME.json'] = (json.dumps({'schema': 1, 'files': {
        n: hashlib.sha256(raw).hexdigest() for n, raw in runtime.items()}}, sort_keys=True) + '\n').encode()
    files.update({'runtime/' + n: raw for n, raw in runtime.items()})
    for name, digest in payload.items():
        files['payload/' + name] = checked(SOURCE / 'payload', name, digest)
    manifest = dict(schema=1, scope='fresh-host public direct runtime staging only',
                    installed=False, installable=False, submissions_enabled=False,
                    fresh_host_acceptance=False, files={
                        n: hashlib.sha256(raw).hexdigest() for n, raw in files.items()})
    temporary = Path(tempfile.mkdtemp(prefix='.fresh-runtime-', dir=destination.parent))
    try:
        for name, raw in files.items():
            path = temporary / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (temporary / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
        # Refuse concurrent destinations as well as the initial preflight.
        destination.mkdir()
        for path in temporary.iterdir():
            path.rename(destination / path.name)
    finally:
        shutil.rmtree(temporary)
    return manifest


if __name__ == '__main__':
    result = build(ROOT / 'staged-direct-runtime')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'} | {'files': len(result['files'])}))
