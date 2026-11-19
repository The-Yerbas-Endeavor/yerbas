"""Verify staged code/service composition. Does not install or execute payload."""
import ast,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RUNTIME_PINS = {'runtime/WHEELS.json': '824ea43bffb31fc9afd9d5bb7c187e0fffd91543093d310c92bde2b2e2b1ed9a', 'runtime/offline-requirements.txt': '78facd4a894d41b8c720e33ba8a3105b8fb367a503a3cc9912c585909fc1d545'}
AGENT_SHA256 = '409e1083ea7f6f7bd85640e3ddcec349b30ade4adf122b2a632e639a1594c444'
DATA_PINS = {'dataset/manifest.json': 'c814209c81bfb94c58b51db35f729595831f8c9ff78d046802cffa062bfe1fa8', 'dataset/train.jsonl': 'd78ec2c19bc097fc92ba62ef3797530ef4aadefb4968fe29145bf36f8e19a7f6', 'dataset/validation.jsonl': '3b4402864bafb8f305d493c5eb4e4a0fc3beefe96cd6337af92aba054b4585c8', 'source-license/source.json': '12f7d6d69f9b9b3de419b94e2357f3802d79d8ee393ff20130eff844d3029a23', 'source-license/source-with-license.txt': '01b38ea4c710a84bc18d0bd41271a5a1a92b94e97b2812f4dece97d4a694725e'}
RESUME='c29419ec0a6494ce58e29beab552549c5ae702b981d0078136918a22f7980328'
def verify(root):
 if hashlib.sha256((root/"owner-agent/wallet_agent.py").read_bytes()).hexdigest()!=AGENT_SHA256:raise ValueError("Owner agent changed")
 for name,h in RUNTIME_PINS.items():
  if hashlib.sha256((root/name).read_bytes()).hexdigest()!=h:raise ValueError('Runtime lock changed')
 manifest=json.loads((root/'MANIFEST.json').read_text());base=root/'rootfs'
 expected=set(manifest['files']);observed=set()
 for p in base.rglob('*'):
  if p.is_symlink():raise ValueError('Symlink refused')
  if p.is_file():observed.add(p.relative_to(base).as_posix())
 if expected!=observed:raise ValueError('Unexpected or missing payload')
 for name,digest in manifest['files'].items():
  if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Unsafe destination')
  p=base/name
  if hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('Payload hash mismatch')
  if p.suffix=='.py':compile(p.read_bytes(),name,'exec')
 if hashlib.sha256((base/'opt/yerbas-ai/broker-v1/provider_broker.py').read_bytes()).hexdigest()!=RESUME:raise ValueError('Resume fix absent')
 measured=base/'opt/yerbas-ai/provider-measured-v1'
 tree=ast.parse((measured/'measurement_policy.py').read_text())
 pins=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PINS' for t in n.targets)]
 if len(pins)!=1:raise ValueError('Measured pins absent')
 for name,digest in pins[0].items():
  if hashlib.sha256((measured/name).read_bytes()).hexdigest()!=digest:raise ValueError('Measured allowlist mismatch')
 for mode,seconds,memory in [('provider',275,'2G'),('replay',135,'512M')]:
  path=base/('etc/systemd/system/yerbas-text-'+mode+'@.service');text=path.read_text();lines=text.splitlines()
  required=['RemainAfterExit=yes','User=yerbas-provider','Group=yerbas-provider','NoNewPrivileges=yes','ProtectSystem=strict','ProtectHome=yes','KillMode=control-group','Restart=no','MemorySwapMax=0','RuntimeMaxSec='+str(seconds),'MemoryMax='+memory]
  if any(v not in lines for v in required):raise ValueError('Service boundary differs')
  if '/var/lib/yerbas-training-experiment/environment/venv' in text:raise ValueError('Obsolete runtime path')
  if sum(v.startswith('ExecStart=/opt/yerbas-ai/runtime-v1/venv/bin/python ') for v in lines)!=1:raise ValueError('Runtime differs')
  override=Path(str(path)+'.d')/'50-measured-router.conf';t=override.read_text()
  if 'ExecStart=\n' not in t or '/opt/yerbas-ai/provider-measured-v1/runtime_router.py' not in t or (' --replay-only' in t)!=(mode=='replay'):raise ValueError('Measured routing differs')
 dataset_root=base/'opt/yerbas-ai/provider-v1'
 for name,h in DATA_PINS.items():
  if hashlib.sha256((dataset_root/name).read_bytes()).hexdigest()!=h:raise ValueError('Approved dataset/license bytes differ')
 source=json.loads((dataset_root/'source-license/source.json').read_text())
 raw=(dataset_root/'source-license/source-with-license.txt').read_bytes()
 if len(raw)!=source['bytes'] or hashlib.sha256(raw).hexdigest()!=source['sha256']:raise ValueError('Source attribution binding differs')
 corpus=json.loads((dataset_root/'dataset/manifest.json').read_text())
 canonical=json.dumps(corpus,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
 if hashlib.sha256(canonical).hexdigest()!='91d43e60d41b056dcaf787b6d68393d4d02e738c12dde14bebefdd83565ddca8':raise ValueError('Accepted dataset identity differs')
 return dict(passed=True,files=len(expected),measured_pins=len(pins[0]),approved_dataset_and_source_verified=True,runtime_path_reconciled=True,resume_fix_present=True,installed=False,fresh_host_acceptance=False)
if __name__=='__main__':print(json.dumps(verify(ROOT),indent=2))
