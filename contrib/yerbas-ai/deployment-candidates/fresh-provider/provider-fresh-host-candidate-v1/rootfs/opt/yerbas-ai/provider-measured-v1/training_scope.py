"""In-memory diagnostic wrappers around the pinned recipe's training body.
Frozen source files and recipe identity remain unchanged. This instrumentation
has a separately reported identity and never approves reward time.
"""
import ast,hashlib,inspect
from contextlib import contextmanager
from pathlib import Path
RECIPE_SHA='a6a32ed7204376bbe207cfbfcc52862d780bb546fa10c32babddd7e77839f32f'
PREFIX='yerbas_training_step:'

class Instrument(ast.NodeTransformer):
 def __init__(self):self.changed=0
 def visit_While(self,node):
  # The pinned _train function has exactly one training loop. Wrap only
  # generator/index selection, forward/backward and SGD; exclude checkpointing.
  calls=[i for i,s in enumerate(node.body) if isinstance(s,ast.Expr) and isinstance(s.value,ast.Call) and ast.unparse(s.value.func)=='optimizer.step']
  if len(calls)!=1:raise ValueError('Expected one SGD boundary')
  boundary=calls[0]+1
  wrapped=ast.With(items=[ast.withitem(context_expr=ast.Call(func=ast.Name(id='_yerbas_training_scope',ctx=ast.Load()),args=[ast.Name(id='step',ctx=ast.Load())],keywords=[]))],body=node.body[:boundary])
  advance=ast.Expr(value=ast.Call(func=ast.Name(id='_yerbas_capture_boundary',ctx=ast.Load()),args=[],keywords=[]))
  node.body=[wrapped,advance,*node.body[boundary:]];self.changed+=1
  return node

@contextmanager
def instrument(recipe,torch,profiler,device="cuda"):
 if device not in ("cpu","cuda"):raise ValueError("Unknown instrumentation device")
 source=Path(recipe.__file__)
 if hashlib.sha256(source.read_bytes()+source.with_name('text_baseline.py').read_bytes()).hexdigest()!=RECIPE_SHA:raise ValueError('Unapproved recipe source')
 original=recipe._train;tree=ast.parse(inspect.getsource(original));edit=Instrument();tree=edit.visit(tree)
 if edit.changed!=1:raise ValueError('Expected exactly one training loop')
 ast.fix_missing_locations(tree)
 @contextmanager
 def scope(step):
  if device=="cuda":torch.cuda.synchronize()
  with torch.profiler.record_function(PREFIX+str(step)):
   try:yield
   finally:
    if device=="cuda":torch.cuda.synchronize()
 namespace=dict(original.__globals__,_yerbas_training_scope=scope,_yerbas_capture_boundary=profiler.step)
 exec(compile(tree,str(source),'exec'),namespace)
 recipe._train=namespace['_train']
 try:yield
 finally:recipe._train=original

def instrumentation_sha256():
 return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
