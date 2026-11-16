"""Local-only authority and configuration for isolated recovery-network tests."""
import hashlib
import json
import os
from pathlib import Path

from test_framework.key import CECKey


def prepare_recovery_devnet(test):
    test.chain = 'devnet'
    secret = os.urandom(32)
    key = CECKey()
    key.set_secretbytes(secret)

    def base58(payload):
        data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
        n = int.from_bytes(data, 'big')
        text = ''
        alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        while n:
            n, r = divmod(n, 58)
            text = alphabet[r] + text
        return '1' * (len(data) - len(data.lstrip(b'\0'))) + text

    authority = base58(bytes([140]) + hashlib.new('ripemd160', hashlib.sha256(key.get_pubkey()).digest()).digest())
    private = base58(bytes([239]) + secret)
    test.extra_args = [['-llmqrecoverydevnet', '-llmqrecoveryauthority=' + authority,
                        '-dnsseed=0', '-listenonion=0'] for _ in range(test.num_nodes)]
    return authority, private


def finish_recovery_devnet(test, authority, private):
    for i in range(test.num_nodes):
        config = Path(test.options.tmpdir) / ('node%d' % i) / 'yerbas.conf'
        config.write_text(config.read_text().replace('devnet=devnet1', 'devnet=llmq-recovery-v1'))
    config = Path(test.options.tmpdir) / 'node0' / 'yerbas.conf'
    os.chmod(config, 0o600)
    with config.open('a') as output:
        output.write('sporkkey=' + private + '\n')
    (Path(test.options.tmpdir) / 'network-identity.json').write_text(json.dumps(
        {'chain': 'devnet', 'name': 'llmq-recovery-v1', 'authority_address': authority,
         'accelerated_mining': True, 'public_network': False}, indent=2))
