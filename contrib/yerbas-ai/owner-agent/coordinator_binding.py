"""Explicit locally trusted binding; never derive signing authority from a claim."""
import hashlib,ipaddress,json,os,re,stat
from pathlib import Path
from urllib.parse import urlsplit
LEGACY_ORIGIN='https://192.168.0.102:9444'
def origin(value):
    if not isinstance(value,str):raise ValueError('Invalid origin')
    p=urlsplit(value)
    try:ip=ipaddress.IPv4Address(p.hostname);port=p.port
    except (ValueError,TypeError):raise ValueError('Private literal IPv4 required')
    if (p.scheme!='https' or p.username is not None or p.password is not None or p.path or p.query or p.fragment or
        not port or not 1024<=port<=65535 or value!=f'https://{ip}:{port}' or
        not any(ip in ipaddress.ip_network(n) for n in ('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))):
        raise ValueError('Canonical private HTTPS origin required')
    return value

def validate(value):
    if not isinstance(value,dict) or set(value)!={'schema','origin','ca_sha256'} or type(value['schema']) is not int or value['schema']!=1:raise ValueError('Exact binding required')
    origin(value['origin'])
    if not isinstance(value['ca_sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['ca_sha256']):raise ValueError('Invalid CA digest')
    return value

def load(path,ca_path):
    path=Path(os.path.abspath(path))
    for parent in path.parents:
        i=parent.lstat()
        if not stat.S_ISDIR(i.st_mode) or i.st_uid not in (0,os.getuid()) or i.st_mode&0o022:raise ValueError('Unsafe binding ancestry')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        i=os.fstat(fd)
        if not stat.S_ISREG(i.st_mode) or i.st_uid not in (0,os.getuid()) or i.st_mode&0o022 or i.st_size>4096:raise ValueError('Unsafe binding file')
        def unique(items):
            result={}
            for k,v in items:
                if k in result:raise ValueError('Duplicate binding field')
                result[k]=v
            return result
        value=validate(json.loads(os.read(fd,4097),object_pairs_hook=unique))
    finally:os.close(fd)
    if hashlib.sha256(Path(ca_path).read_bytes()).hexdigest()!=value['ca_sha256']:raise ValueError('Installed CA differs from approved binding')
    return value

def require(claim,binding):
    validate(binding)
    if any(claim.get(k)!=binding[k] for k in ('origin','ca_sha256')):raise ValueError('Challenge coordinator binding differs')
