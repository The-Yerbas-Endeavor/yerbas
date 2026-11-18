"""Explicit recovery only for a returned failure before assignment issuance.

The fixed operator creates its evidence folder before issuing an assignment.
An absent folder plus a retained nonzero exit is required; uncertain outcomes
and all existing evidence require separate reconciliation. No record is erased.
"""
import fcntl,json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from workflow import Journal,validate_request
from control import ROOT
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'wallet-rental-service-v1'))
from context import Context
from verification import verify,installed_command
from orchestration import Adapter

def eligible(journal,evidence_root):
 request=journal.read('authorization.json');binding=validate_request(request)
 if journal.read('verify-intent.json')!={'step':'verify','authorization_sha256':binding} or journal.read('verify-result.json') is not None:raise ValueError('Exact unfinished verification required')
 result=journal.read('verification-command-result.json')
 if not result or type(result.get('exit_code'))is not int or result['exit_code']==0:raise ValueError('Returned failure required; uncertain outcome refused')
 intent=journal.read('verification-intent.json');path=Path(intent['evidence'])
 if path.parent!=evidence_root or os.path.lexists(path):raise ValueError('Existing verification evidence requires reconciliation')
 return request,binding

def main():
 os.umask(0o077)
 if len(sys.argv)!=2:raise ValueError('Exact retained quote required')
 quote=sys.argv[1];directory=ROOT/quote;journal=Journal(directory)
 evidence=Path.home()/'.local/share/yerbas-ai-migration-v1/operator-v1/evidence'
 request,binding=eligible(journal,evidence)
 if request['quote']!=quote:raise ValueError('Quote differs')
 fd=os.open(directory/'workflow.lock',os.O_RDWR|os.O_NOFOLLOW)
 try:
  fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
  request,binding=eligible(journal,evidence)
  recovery=directory/'verification-recovery-1';recovery.mkdir(mode=0o700)
  context=Context(quote,directory);sub=Context(quote,recovery)
  sub.save('results.json',context.load('results.json'))
  journal.retain('verification-recovery-intent.json',{'original':journal.read('verification-intent.json'),'failure':journal.read('verification-command-result.json'),'new_state':str(recovery),'previous_assignment_not_issued':True})
  value=verify(sub,evidence,installed_command)
  context.save_once('verification-reference.json',value)
  journal.retain('verify-result.json',{'authorization_sha256':binding,'value':value})
 finally:os.close(fd)
 result=journal.run(request,Adapter(context))
 journal.retain('complete.json',{'passed':True,'result':result['release'],'explicit_preassignment_recovery':True})
 print(json.dumps({'passed':True,'quote':quote,'recovered':True}))
if __name__=='__main__':main()
