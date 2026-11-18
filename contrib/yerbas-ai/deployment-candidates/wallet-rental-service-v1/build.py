import base64,hashlib,json
from pathlib import Path
h=Path(__file__).resolve().parent
files={p.name:p.read_bytes() for p in (h/'package').glob('*.py')}
pins={n:hashlib.sha256(v).hexdigest() for n,v in sorted(files.items())}
files['manifest.json']=json.dumps(pins,sort_keys=True).encode()
tag=hashlib.sha256(files['manifest.json']).hexdigest()[:16];dest='/opt/yerbas-ai/wallet-rental-'+tag
s=(h/'install_template.py').read_text().replace('PAYLOAD={} # GENERATED','PAYLOAD='+repr({n:base64.b64encode(v).decode() for n,v in files.items()})).replace("DEST=Path('/opt/yerbas-ai/unset') # GENERATED",'DEST=Path('+repr(dest)+')')
(h/'install.py').write_text(s);(h/'install.py').chmod(0o600)
(h/'PACKAGE.json').write_text(json.dumps(dict(package=dest,files=pins,installer_sha256=hashlib.sha256(s.encode()).hexdigest()),indent=2)+'\n')
(h/'yerbas-wallet-rental.service').write_text((h/'install_template.py').read_text().split("UNIT='''",1)[1].split("'''",1)[0].replace('PACKAGE',dest))
print(dest)
