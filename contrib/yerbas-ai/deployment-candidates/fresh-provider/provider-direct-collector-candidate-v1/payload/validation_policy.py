"""Restartable validation-based stopping policy; no GPU or network operations."""
import math

MIN_DELTA = 0.0001
PATIENCE = 5


def initial():
    return {'best_loss': None, 'best_step': None, 'last_step': 0,
            'bad_evaluations': 0, 'evaluations': 0, 'stopped': False}


def validate(state):
    if type(state) is not dict or set(state) != set(initial()):
        raise ValueError('Invalid selection state')
    for name in ('last_step', 'bad_evaluations', 'evaluations'):
        if type(state[name]) is not int or state[name] < 0:
            raise ValueError('Invalid selection counter')
    if type(state['stopped']) is not bool:
        raise ValueError('Invalid stopped flag')
    if state['evaluations'] == 0:
        if state != initial():
            raise ValueError('Invalid initial selection state')
    else:
        if type(state['best_loss']) not in (int, float) or not math.isfinite(state['best_loss']) or state['best_loss'] < 0:
            raise ValueError('Invalid best loss')
        if type(state['best_step']) is not int or not 0 < state['best_step'] <= state['last_step']:
            raise ValueError('Invalid best step')
        if state['bad_evaluations'] >= state['evaluations']:
            raise ValueError('Invalid patience counter')
        if state['stopped'] != (state['bad_evaluations'] >= PATIENCE):
            raise ValueError('Inconsistent stopping state')
    return state


def observe(state, step, loss):
    validate(state)
    if state['stopped']:
        raise ValueError('Job already stopped')
    if type(step) is not int or step <= state['last_step']:
        raise ValueError('Evaluation step must increase')
    if type(loss) not in (int, float) or not math.isfinite(loss) or loss < 0:
        raise ValueError('Invalid validation loss')
    result = dict(state)
    improved = state['best_loss'] is None or loss < state['best_loss'] - MIN_DELTA
    result.update(last_step=step, evaluations=state['evaluations'] + 1)
    if improved:
        result.update(best_loss=loss, best_step=step, bad_evaluations=0)
    else:
        result['bad_evaluations'] += 1
    result['stopped'] = result['bad_evaluations'] >= PATIENCE
    validate(result)
    return result, improved
