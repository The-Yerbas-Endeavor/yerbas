"""Deterministic byte-bigram baseline; CPU only, no pickle or network access."""
import hashlib,json,math,random,time
from pathlib import Path

def load_dataset(directory):
    directory=Path(directory);m=json.loads((directory/'manifest.json').read_text());splits={}
    for item in m['splits']:
        name=item['split']
        if name not in ('train','validation') or name in splits:raise ValueError('Invalid split')
        raw=(directory/(name+'.jsonl')).read_bytes()
        if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Corpus hash mismatch')
        docs=[json.loads(line) for line in raw.decode('utf-8').splitlines()]
        if len(docs)!=item['documents']:raise ValueError('Document count mismatch')
        for doc in docs:
            if hashlib.sha256(doc['text'].encode('utf-8')).hexdigest()!=doc['sha256']:raise ValueError('Document changed')
        splits[name]=docs
    if set(splits)!= {'train','validation'}:raise ValueError('Missing split')
    if set(d['sha256'] for d in splits['train']) & set(d['sha256'] for d in splits['validation']):raise ValueError('Train/validation leakage')
    return m,splits

def run(dataset,output):
    output=Path(output)
    if output.exists():raise ValueError('Output already exists')
    m,splits=load_dataset(dataset);start=time.monotonic();alpha=.1
    counts=[[0]*256 for _ in range(256)];unigram=[0]*256
    for doc in splits['train']:
        raw=doc['text'].encode('utf-8')
        for b in raw:unigram[b]+=1
        for a,b in zip(raw,raw[1:]):counts[a][b]+=1
    totals=[sum(row) for row in counts];nll=0.;uni_nll=0.;tokens=0
    for doc in splits['validation']:
        raw=doc['text'].encode('utf-8')
        for a,b in zip(raw,raw[1:]):
            nll-=math.log((counts[a][b]+alpha)/(totals[a]+256*alpha))
            uni_nll-=math.log((unigram[b]+alpha)/(sum(unigram)+256*alpha));tokens+=1
    if not tokens:raise ValueError('Empty held-out evaluation')
    rng=random.Random(731);sample=bytearray(b'A')
    for _ in range(399):sample.append(rng.choices(range(256),weights=[v+alpha for v in counts[sample[-1]]])[0])
    model={'schema':1,'recipe':'byte-bigram-baseline-v1','alpha':alpha,'counts':counts,'dataset_splits':m['splits']}
    raw=json.dumps(model,separators=(',',':')).encode('utf-8')
    report={'recipe':model['recipe'],'device':'CPU','gpu_training':False,'heldout_bytes_predicted':tokens,
            'heldout_nats_per_byte':nll/tokens,'heldout_bits_per_byte':nll/tokens/math.log(2),
            'unigram_bits_per_byte':uni_nll/tokens/math.log(2),'beats_unigram':nll<uni_nll,
            'elapsed_seconds':round(time.monotonic()-start,3),'model_sha256':hashlib.sha256(raw).hexdigest(),
            'dataset_splits':m['splits'],'sample_seed':731,'limitations':'Byte bigram diagnostic baseline, not a neural model or conversational AI'}
    output.mkdir(mode=0o700);(output/'model.json').write_bytes(raw)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'sample.txt').write_text(sample.decode('utf-8',errors='replace')+'\n')
    return report
