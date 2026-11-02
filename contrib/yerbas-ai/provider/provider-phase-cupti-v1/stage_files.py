import os,stat,shutil,tempfile
from pathlib import Path
def stage_files(destination,files):
    if os.path.lexists(destination):
        if destination.is_symlink() or not destination.is_dir():raise ValueError('Unexpected runtime destination')
        if {p.name for p in destination.iterdir()}!=set(files):raise ValueError('Existing candidate contents differ')
        for name,raw in files.items():
            p=destination/name;info=p.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or p.read_bytes()!=raw:raise ValueError('Existing candidate differs')
        return
    temp=Path(tempfile.mkdtemp(prefix='.measured-',dir=destination.parent))
    try:
        temp.chmod(0o755)
        for name,raw in files.items():
            p=temp/name;p.write_bytes(raw);p.chmod(0o644)
        os.rename(temp,destination)
    finally:
        if temp.exists():shutil.rmtree(temp)


