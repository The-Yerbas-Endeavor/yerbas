"""Fixed tiny-MLP sequential handoff experiment. No arbitrary recipes or pickle."""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

SHAPES = ((16, 8), (16,), (1, 16), (1,))
CONFIG = {'runner': 'handoff-mlp-v1', 'steps': 40, 'split': 20, 'batch': 32,
          'lr': 0.05, 'momentum': 0.9, 'rng': 'none-after-explicit-initialization'}
MAX_BYTES = 65536


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(encode(value)).hexdigest()


def dataset():
    rng = random.Random(731)
    x = [[rng.randrange(-50, 51) / 50 for _ in range(8)] for _ in range(192)]
    y = [[float(sum(row[:4]) > 0)] for row in x]
    return x, y


def initial():
    return [[[((i * 13 + j * 7) % 31 - 15) / 100 for j in range(8)] for i in range(16)],
            [0.0] * 16, [[(i - 7.5) / 50 for i in range(16)]], [0.0]]


def identity():
    return {'config': CONFIG, 'dataset_sha256': sha(dataset()),
            'initial_sha256': sha(initial()),
            'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def tensor_shape(value, shape):
    if shape:
        if type(value) is not list or len(value) != shape[0]:
            raise ValueError('Tensor shape mismatch')
        for child in value:
            tensor_shape(child, shape[1:])
    elif type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
        raise ValueError('Invalid tensor scalar')


def validate(checkpoint):
    if type(checkpoint) is not dict or set(checkpoint) != {
            'schema', 'identity', 'step', 'sampler_position', 'parameters', 'momentum', 'torch'}:
        raise ValueError('Unexpected checkpoint fields')
    if type(checkpoint['schema']) is not int or checkpoint['schema'] != 1:
        raise ValueError('Wrong schema')
    if encode(checkpoint['identity']) != encode(identity()):
        raise ValueError('Runner, configuration, dataset or initial model changed')
    if type(checkpoint['step']) is not int or checkpoint['step'] != 20:
        raise ValueError('Expected step 20')
    if type(checkpoint['sampler_position']) is not int or checkpoint['sampler_position'] != 0:
        raise ValueError('Wrong deterministic sampler position')
    if checkpoint['torch'] != '2.14.1+cu126':
        raise ValueError('Unreviewed runtime version')
    for key in ('parameters', 'momentum'):
        if type(checkpoint[key]) is not list or len(checkpoint[key]) != 4:
            raise ValueError('Wrong tensor count')
        for value, shape in zip(checkpoint[key], SHAPES, strict=True):
            tensor_shape(value, shape)
    return checkpoint


def load_checkpoint(path, expected_sha):
    with open(path, 'rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('Checkpoint size or SHA256 mismatch')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    return validate(json.loads(raw, object_pairs_hook=unique))


def run(mode, output, checkpoint=None, expected_sha=None):
    import torch
    if torch.__version__ != '2.14.1+cu126' or not torch.cuda.is_available():
        raise RuntimeError('Expected reviewed CUDA runtime')
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.set_num_threads(1)
    device = torch.device('cuda:0')
    x, y = (torch.tensor(v, dtype=torch.float32, device=device) for v in dataset())

    def model_and_optimizer(values, buffers=None):
        model = torch.nn.Sequential(torch.nn.Linear(8, 16), torch.nn.Tanh(), torch.nn.Linear(16, 1)).to(device)
        opt = torch.optim.SGD(model.parameters(), lr=CONFIG['lr'], momentum=CONFIG['momentum'])
        with torch.no_grad():
            for i, (p, value) in enumerate(zip(model.parameters(), values, strict=True)):
                p.copy_(torch.tensor(value, dtype=torch.float32, device=device))
                if buffers is not None:
                    opt.state[p]['momentum_buffer'] = torch.tensor(buffers[i], dtype=torch.float32, device=device)
        return model, opt

    def train(model, opt, start, end):
        for step in range(start, end):
            offset = step * 32 % 128
            opt.zero_grad(set_to_none=True)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(model(x[offset:offset+32]), y[offset:offset+32])
            loss.backward()
            if not all(p.grad is not None and torch.isfinite(p.grad).all().item() for p in model.parameters()):
                raise RuntimeError('Non-finite gradient')
            opt.step()
        torch.cuda.synchronize()

    def evaluate(model):
        with torch.no_grad():
            loss = torch.nn.functional.binary_cross_entropy_with_logits(model(x[128:]), y[128:]).item()
        if not math.isfinite(loss):
            raise RuntimeError('Non-finite held-out loss')
        return loss

    model, opt = model_and_optimizer(initial())
    initial_loss = evaluate(model)
    if mode == 'segment':
        train(model, opt, 0, 20)
        state = {'schema': 1, 'identity': identity(), 'step': 20, 'sampler_position': 0,
                 'parameters': [p.detach().cpu().tolist() for p in model.parameters()],
                 'momentum': [opt.state[p]['momentum_buffer'].cpu().tolist() for p in model.parameters()],
                 'torch': torch.__version__}
        validate(state)
        raw = encode(state)
        if len(raw) > MAX_BYTES:
            raise RuntimeError('Checkpoint exceeds size limit')
        with (output / 'checkpoint.json').open('xb') as stream:
            stream.write(raw)
        report = {'mode': mode, 'step': 20, 'sha256': hashlib.sha256(raw).hexdigest(),
                  'bytes': len(raw), 'initial_loss': initial_loss, 'heldout_loss': evaluate(model)}
    else:
        state = load_checkpoint(checkpoint, expected_sha)
        train(model, opt, 0, 40)
        resumed, resumed_opt = model_and_optimizer(state['parameters'], state['momentum'])
        train(resumed, resumed_opt, 20, 40)
        maximum_error = 0.0
        for a, b in zip(model.parameters(), resumed.parameters(), strict=True):
            for left, right in ((a, b), (opt.state[a]['momentum_buffer'], resumed_opt.state[b]['momentum_buffer'])):
                torch.testing.assert_close(left, right, rtol=1e-6, atol=1e-7)
                maximum_error = max(maximum_error, (left-right).abs().max().item())
        baseline_loss, resumed_loss = evaluate(model), evaluate(resumed)
        if abs(baseline_loss-resumed_loss) > 1e-7 or not resumed_loss < initial_loss:
            raise RuntimeError('Held-out loss comparison or learning check failed')
        report = {'mode': mode, 'passed': True, 'checkpoint_sha256': expected_sha,
                  'baseline_steps': 40, 'resumed_from_step': 20, 'final_step': 40,
                  'initial_loss': initial_loss, 'baseline_loss': baseline_loss,
                  'resumed_loss': resumed_loss, 'max_tensor_error': maximum_error,
                  'transport': 'verified SSH; no HTTPS training endpoint tested',
                  'simulated_credit_settlement_tested': False}
    report.update({'gpu': torch.cuda.get_device_name(), 'torch': torch.__version__,
                   'runner_identity': identity()})
    with (output / 'report.json').open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['segment', 'compare'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    if args.mode == 'compare' and (args.checkpoint is None or args.sha256 is None):
        parser.error('compare requires checkpoint and SHA256')
    run(args.mode, args.output, args.checkpoint, args.sha256)
