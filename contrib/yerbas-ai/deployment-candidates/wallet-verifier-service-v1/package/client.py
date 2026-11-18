"""Fixed local socket client. Requires the enrolled owner; never invokes sudo."""
import json,socket,struct,sys
if len(sys.argv)!=3:raise ValueError('Action and run ID required')
with socket.socket(socket.AF_UNIX) as connection:
 connection.settimeout(50);connection.connect('/run/yerbas-wallet-verifier/control.sock')
 if struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]!=0:raise ValueError('Protected verifier service required')
 connection.sendall(json.dumps({'action':sys.argv[1],'run_id':sys.argv[2]}).encode()+b'\n')
 raw=connection.makefile('rb').readline(4097)
 if len(raw)>4096:raise ValueError('Bounded reply required')
 result=json.loads(raw)
 if not result.get('ok'):raise RuntimeError(result.get('error','Service refused'))
 print(json.dumps(result['result']))
