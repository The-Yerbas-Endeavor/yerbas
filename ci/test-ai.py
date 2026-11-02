"""Disposable Python checks only; no service, GPU or payment."""
import os,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,'-B',str(root/'ci/check-ai-source.py')],check=True)
if sys.platform.startswith('linux'):
 subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(root/'contrib/yerbas-ai/owner-agent'),'-p','test_*.py','-v'],check=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
 local=root/'contrib/yerbas-ai/local-service'
 subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(local/'tests'),'-v'],cwd=local,check=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(local)))
 subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(root/'contrib/yerbas-ai/payments'),'-v'],check=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
