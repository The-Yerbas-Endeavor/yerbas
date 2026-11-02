"""Construct and verify an unsigned single-input private-testnet reward candidate."""
from decimal import Decimal
import json
import re

MAX_MONEY = 21000000 * 100000000

def units(value):
    if isinstance(value, bool): raise ValueError('Invalid money')
    number = Decimal(str(value))*100000000
    if not number.is_finite() or number != number.to_integral_value() or not 0 <= number <= MAX_MONEY:
        raise ValueError('Invalid money')
    return int(number)

def amount(value):
    return f'{value//100000000}.{value%100000000:08d}'

def candidate(plan, txid, vout, utxo, treasury, scripts, fee):
    if not re.fullmatch('[a-f0-9]{64}', txid) or type(vout) is not int or not 0 <= vout <= 0xffffffff:
        raise ValueError('Invalid outpoint')
    if type(fee) is not int or not 1 <= fee <= 10000:
        raise ValueError('Explicit bounded draft fee required')
    if not utxo or utxo.get('coinbase') is not True or type(utxo.get('confirmations')) is not int or utxo['confirmations'] < 11:
        raise ValueError('Unspent mature private-testnet coinbase required')
    script = utxo['scriptPubKey']
    if script.get('addresses') != [treasury] or script.get('hex') != scripts.get(treasury):
        raise ValueError('Treasury input script mismatch')
    for s in scripts.values():
        if not re.fullmatch('76a914[a-f0-9]{40}88ac', s): raise ValueError('Only P2PKH supported')
    outputs = {}
    for o in plan['outputs']:
        address = o['address']; value = o['amount_base_units']
        if address == treasury or address in outputs or address not in scripts:
            raise ValueError('Reward/change address conflict')
        if type(value) is not int or not 546 <= value <= MAX_MONEY:
            raise ValueError('Reward below default dust or invalid amount')
        outputs[address] = value
    if not outputs or sum(outputs.values()) != plan['total_base_units']:
        raise ValueError('Reward total mismatch')
    incoming = units(utxo['value'])
    change = incoming-sum(outputs.values())-fee
    if change < 546: raise ValueError('Insufficient input or dust change')
    outputs[treasury] = change
    return dict(inputs=[dict(txid=txid,vout=vout,sequence=4294967295)],
                outputs=outputs, input_base_units=incoming, fee_base_units=fee,
                reward_base_units=plan['total_base_units'], change_base_units=change,
                scripts={a:scripts[a] for a in outputs})

def verify_decoded(decoded, expected):
    if decoded.get('locktime') != 0 or decoded.get('type',0) != 0 or len(decoded.get('vin',[])) != 1:
        raise ValueError('Unexpected transaction structure')
    vin=decoded['vin'][0]; wanted=expected['inputs'][0]
    if any(vin.get(k)!=v for k,v in wanted.items()) or vin.get('scriptSig',{}).get('hex') != '' or vin.get('txinwitness'):
        raise ValueError('Unexpected or signed input')
    outputs={}
    for out in decoded['vout']:
        addresses=out['scriptPubKey'].get('addresses',[])
        if len(addresses)!=1 or addresses[0] in outputs: raise ValueError('Ambiguous output')
        address=addresses[0]
        if expected['scripts'].get(address)!=out['scriptPubKey'].get('hex'): raise ValueError('Output script differs')
        outputs[address]=units(out['value'])
    if outputs!=expected['outputs'] or expected['input_base_units']-sum(outputs.values())!=expected['fee_base_units']:
        raise ValueError('Outputs or fee differ')
    return True
