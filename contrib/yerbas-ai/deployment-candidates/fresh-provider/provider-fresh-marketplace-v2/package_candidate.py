"""Create an exclusive public-source bundle; excludes wheels and all live state."""
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parent


def build():
    base=Path(tempfile.mkdtemp(prefix='fresh-provider-package-',dir=ROOT.parent))
    def copy(source,relative):
        if source.is_symlink() or not source.is_file():raise ValueError('Regular public source required')
        target=base/relative;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as f:f.write(source.read_bytes())
    fresh=ROOT.name;old='provider-fresh-host-candidate-v1';direct='provider-direct-collector-candidate-v1'
    for path in ROOT.glob('*.py'):copy(path,Path(fresh)/path.name)
    for name in ('README.txt','CONTROL-SOURCES.json'):copy(ROOT/name,Path(fresh)/name)
    sources=json.loads((ROOT/'CONTROL-SOURCES.json').read_text())['files']
    for name,row in sources.items():
        path=ROOT/'control-source'/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Control source changed')
        copy(path,Path(fresh)/'control-source'/name)
    staged=ROOT/'staged-direct-runtime'
    manifest=json.loads((staged/'MANIFEST.json').read_text())
    for name,h in manifest['files'].items():
        path=staged/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=h:raise ValueError('Staged runtime changed')
        copy(path,Path(fresh)/'staged-direct-runtime'/name)
    copy(staged/'MANIFEST.json',Path(fresh)/'staged-direct-runtime/MANIFEST.json')
    oldroot=ROOT.parent/old
    for name in ('provision_plan.py','owner_agent_plan.py','verify.py','guarded_writer.py',
                 'install_journal.py','reconcile_install.py','prepare_runtime.py',
                 'runtime_inventory.py','runtime_tree.py','owner_agent_phase.py'):
        copy(oldroot/name,Path(old)/name)
    for name in ('MANIFEST.json','owner-agent/wallet_agent.py','runtime/WHEELS.json','runtime/offline-requirements.txt'):
        copy(oldroot/name,Path(old)/name)
    manifest=json.loads((oldroot/'MANIFEST.json').read_text())
    for name,h in manifest['files'].items():
        path=oldroot/'rootfs'/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=h:raise ValueError('Legacy boundary source changed')
        copy(path,Path(old)/'rootfs'/name)
    directroot=ROOT.parent/direct
    for name in ('INSTALL-SHA256.json','PAYLOAD.json'):
        copy(directroot/name,Path(direct)/name)
    pins=json.loads((directroot/'INSTALL-SHA256.json').read_text())
    pins.update({'payload/'+n:h for n,h in json.loads((directroot/'PAYLOAD.json').read_text()).items()})
    for name,h in pins.items():
        path=directroot/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=h:raise ValueError('Direct source changed')
        copy(path,Path(direct)/name)
    run=subprocess.run([sys.executable,'-I','-B','-m','unittest','discover','-s',str(base/fresh),'-q'],
                       cwd=base,capture_output=True,text=True,timeout=120)
    (base/'TEST-RESULT.txt').write_text(run.stdout+run.stderr)
    if run.returncode:raise ValueError('Portable package tests failed; retained '+str(base))
    count=int(re.search(r'Ran (\d+) tests?',run.stdout+run.stderr).group(1))
    files={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in base.rglob('*') if p.is_file()}
    report=dict(schema=1,scope='private-pilot installer candidate; not fresh-host accepted',
                files=files,tests_passed=count,wheels_included=False,credentials_included=False,
                physical_fresh_host_acceptance=False)
    (base/'PACKAGE.json').write_text(json.dumps(report,indent=2)+'\n')
    archive=base.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(base.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(base))
    sha=hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(sha+'  '+archive.name+'\n')
    print(json.dumps(dict(archive=str(archive),sha256=sha,files=len(files),tests_passed=count,
                         physical_fresh_host_acceptance=False),indent=2))


if __name__=='__main__':build()
