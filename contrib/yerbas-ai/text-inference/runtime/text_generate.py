"""Portable bounded CPU sampling of the accepted tiny MLP; no Torch or network."""
import math,random,time
from text_model_load import load

def generate(directory,prompt='Alice ',length=200,seed=731):
    if type(length) is not int or not 1<=length<=1000:raise ValueError('Generate 1..1000 bytes')
    raw=prompt.encode('utf-8')
    if not raw or len(raw)>4096:raise ValueError('Prompt must contain 1..4096 UTF-8 bytes')
    meta,c=load(directory);p=c['parameters'];rng=random.Random(seed);output=bytearray(raw);started=time.monotonic()
    embedding=p['embedding.weight'];hidden=p['hidden.weight'];weights=p['output.weight']
    hrows=[hidden[i*128:(i+1)*128] for i in range(128)];orows=[weights[i*128:(i+1)*128] for i in range(256)]
    for _ in range(length):
        if time.monotonic()-started>30:raise TimeoutError('CPU generation exceeded thirty seconds')
        prefix=list(output[-8:]);prefix=[0]*(8-len(prefix))+prefix
        x=[v for b in prefix for v in embedding[b*16:(b+1)*16]]
        h=[math.tanh(p['hidden.bias'][i]+sum(a*b for a,b in zip(row,x))) for i,row in enumerate(hrows)]
        scores=[p['output.bias'][i]+sum(a*b for a,b in zip(row,h)) for i,row in enumerate(orows)]
        peak=max(scores);probabilities=[math.exp(s-peak) for s in scores]
        output.append(rng.choices(range(256),weights=probabilities)[0])
    return {'text':output.decode('utf-8',errors='replace'),'generated_bytes':length,'seed':seed,'device':'CPU (Python float64)',
            'checkpoint_sha256':meta['checkpoint_sha256'],'elapsed_seconds':round(time.monotonic()-started,3),
            'note':'Sampling is not bit-identical to the Torch float32 sampler; no training or GPU workload started.'}
