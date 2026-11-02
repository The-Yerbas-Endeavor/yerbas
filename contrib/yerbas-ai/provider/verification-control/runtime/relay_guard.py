"""Pause only the receipt relay while the strict provider-idle supervisor runs."""
import contextlib
import subprocess
UNITS=('yerbas-ai-reward-request.socket','yerbas-ai-reward-request.service')
def state(unit):
    return subprocess.check_output(['/usr/bin/systemctl','show',unit,'-p','ActiveState','--value'],text=True,timeout=10).strip()
def control(action,units):
    subprocess.run(['/usr/bin/systemctl',action,*units],check=True,timeout=30)
@contextlib.contextmanager
def paused():
    original={u:state(u) for u in UNITS}
    if any(v not in ('active','inactive') for v in original.values()):
        raise RuntimeError('Reward relay is transitioning; no verification started')
    try:
        # Stop socket first as well as service, so queries cannot reactivate it.
        control('stop',UNITS)
        if any(state(u)!='inactive' for u in UNITS):
            raise RuntimeError('Reward relay did not stop; no verification started')
        yield
    finally:
        active=tuple(u for u in UNITS if original[u]=='active')
        if active:control('start',active)
        actual={u:state(u) for u in UNITS}
        if actual!=original:raise RuntimeError('Reward relay restoration differs: '+str(actual))
