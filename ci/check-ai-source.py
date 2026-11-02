"""Verify public AI source, versions and absence of private deployment files."""
import ast,hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ai=ROOT/'contrib/yerbas-ai'
m=json.loads((ai/'SOURCE.json').read_text());expected=m['files']
actual={str(p.relative_to(ai)) for p in ai.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
if actual!=set(expected)|{'SOURCE.json'}:raise ValueError('Unexpected AI source file')
for name,digest in expected.items():
 p=ai/name
 if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('AI source differs: '+name)
 if p.suffix in ('.key','.pem','.sqlite','.sqlite3','.db') or p.name in ('wallet.dat','enrollment.json'):raise ValueError('Private state forbidden')
 text=p.read_text()
 if re.search(r'-----BEGIN [A-Z ]*PRIVATE KEY-----',text):raise ValueError('Private key forbidden')
 if p.suffix=='.py':ast.parse(text,filename=str(p))
assert 'release-version=5.0.0.0' in (ROOT/'build.properties').read_text()
for key,value in [('MAJOR',5),('MINOR',0),('REVISION',0),('BUILD',0)]:
 assert f'define(_CLIENT_VERSION_{key}, {value})' in (ROOT/'configure.ac').read_text()
print(json.dumps(dict(passed=True,source_files=len(expected),wallet_version='5.0.0.0',private_state=False)))
