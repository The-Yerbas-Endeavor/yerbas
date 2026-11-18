import base64,hashlib,json
from pathlib import Path
h=Path(__file__).resolve().parent
files={str(p.relative_to(h/'package')):p.read_bytes() for p in (h/'package').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
pins={n:hashlib.sha256(raw).hexdigest() for n,raw in sorted(files.items())}
tag=hashlib.sha256(json.dumps(pins,sort_keys=True).encode()).hexdigest()[:16]
dest='/opt/yerbas-ai/wallet-verifier-'+tag
s=(h/'install_template.py').read_text().replace('PAYLOAD = {} # GENERATED','PAYLOAD = '+repr({n:base64.b64encode(raw).decode() for n,raw in files.items()})).replace("DEST = Path('/opt/yerbas-ai/unset') # GENERATED",'DEST = Path('+repr(dest)+')')
(h/'install.py').write_text(s);(h/'install.py').chmod(0o600)
(h/'PACKAGE.json').write_text(json.dumps(dict(package=dest,files=pins,installer_sha256=hashlib.sha256(s.encode()).hexdigest()),indent=2)+'\n')
print(dest)
