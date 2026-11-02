"""Add diagnostic boundaries around the pinned loop and persistence body."""
import ast
from contextlib import contextmanager
import hashlib
import inspect
from pathlib import Path
from loop_scope import RECIPE_SHA


def boundary(body, name):
    return [ast.With(items=[ast.withitem(context_expr=ast.Call(
        func=ast.Name(id='_timing_phase', ctx=ast.Load()),
        args=[ast.Constant(name)], keywords=[]))], body=body)]


def wrap(tree):
    f = tree.body[0]
    loops = [n for n in f.body if isinstance(n, ast.While)]
    saves = [n for n in f.body if isinstance(n, ast.FunctionDef) and n.name == 'persist']
    if len(loops) != 1 or len(saves) != 1:
        raise ValueError('Unexpected recipe structure')
    saves[0].body = boundary(saves[0].body, 'checkpoint')
    index = f.body.index(loops[0])
    f.body[index:index+1] = boundary([loops[0]], 'loop')
    return ast.fix_missing_locations(tree)


@contextmanager
def scoped(recipe, phase):
    path = Path(recipe.__file__)
    if hashlib.sha256(path.read_bytes()+path.with_name('text_baseline.py').read_bytes()).hexdigest() != RECIPE_SHA:
        raise ValueError('Recipe changed')
    original = recipe._train
    namespace = dict(original.__globals__, _timing_phase=phase)
    exec(compile(wrap(ast.parse(inspect.getsource(original))), str(path), 'exec'), namespace)
    recipe._train = namespace['_train']
    try:
        yield
    finally:
        recipe._train = original
