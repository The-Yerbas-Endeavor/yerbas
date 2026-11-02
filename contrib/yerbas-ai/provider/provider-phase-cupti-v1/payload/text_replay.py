"""Receipt-only HTTPS recovery: no training executor, GPU query or Torch import."""
import argparse
import hashlib
import json
import signal
import threading
from pathlib import Path
from text_neural import identity
from text_https import Client
from text_worker import run_once


def replay(directory,client,provider,contribution,origin,approved,stop):
    def never_execute(*args):
        raise RuntimeError('Training is forbidden in receipt-only recovery')
    return run_once(directory,client,provider,contribution,origin,approved,
                    never_execute,stop,result_only=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True)
    args=parser.parse_args()
    from provider_executor import read_json
    import os
    config=read_json(args.config,owner=os.getuid())
    approved=identity(Path(config['dataset']))
    if approved!=config['expected_identity']:raise ValueError('Approved recipe or corpus changed')
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    client=Client(config['url'],config['token'],config['ca'])
    origin=hashlib.sha256(json.dumps([config['url'],hashlib.sha256(config['token'].encode()).hexdigest(),hashlib.sha256(Path(config['ca']).read_bytes()).hexdigest()]).encode()).hexdigest()
    receipt=replay(args.state,client,config['provider'],config['contribution'],origin,approved,stop)
    print(json.dumps({'receipt':receipt,'receipt_verified':True,'training_executed':False}))

if __name__=='__main__':main()
