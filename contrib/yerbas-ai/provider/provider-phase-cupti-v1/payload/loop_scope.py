"""Wrap only the pinned recipe's training loop without changing its body."""
import ast
from contextlib import contextmanager
import hashlib
import inspect
from pathlib import Path

RECIPE_SHA = 'a6a32ed7204376bbe207cfbfcc52862d780bb546fa10c32babddd7e77839f32f'


def wrap(tree):
    function = tree.body[0]
    loops = [(i, node) for i, node in enumerate(function.body) if isinstance(node, ast.While)]
    if len(loops) != 1:
        raise ValueError('One pinned training loop required')
    index, loop = loops[0]
    function.body[index] = ast.With(items=[ast.withitem(context_expr=ast.Call(
        func=ast.Name(id='_collector_training_loop', ctx=ast.Load()), args=[], keywords=[]))], body=[loop])
    return ast.fix_missing_locations(tree)


@contextmanager
def scoped(recipe, boundary):
    source = Path(recipe.__file__)
    if hashlib.sha256(source.read_bytes()+source.with_name('text_baseline.py').read_bytes()).hexdigest() != RECIPE_SHA:
        raise ValueError('Approved recipe changed')
    original = recipe._train
    tree = wrap(ast.parse(inspect.getsource(original)))
    namespace = dict(original.__globals__, _collector_training_loop=boundary)
    exec(compile(tree, str(source), 'exec'), namespace)
    recipe._train = namespace['_train']
    try:
        yield
    finally:
        recipe._train = original
