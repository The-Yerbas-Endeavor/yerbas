"""Conservative payment observation policy; never signs, sends or retries a payment.
Inputs must be collected by a trusted read-only node adapter. This module alone
is not proof that a transaction paid a particular reward or passed script checks.
"""
import re

def assess(binding, observation, previous=None, required_confirmations=6):
    if type(required_confirmations) is not int or not 1 <= required_confirmations <= 100:
        raise ValueError('Bounded confirmation policy required')
    base=dict(schema=1,required_confirmations=required_confirmations,
              automatic_retry=False,spending_authorized=False,irreversible=False)
    # An unsigned candidate txid cannot identify a subsequent signed payment.
    if binding is None:
        return dict(base,status='awaiting_signed_transaction_binding',confirmed=False)
    if (not isinstance(binding,dict) or set(binding)!={'plan_sha256','signed_txid','signed_transaction_verified'}
        or binding['signed_transaction_verified'] is not True
        or any(not isinstance(binding[k],str) or not re.fullmatch('[a-f0-9]{64}',binding[k]) for k in ('plan_sha256','signed_txid'))):
        raise ValueError('Verified signed transaction binding required')
    base.update(plan_sha256=binding['plan_sha256'],signed_txid=binding['signed_txid'])
    if previous is not None and any(previous.get(k)!=binding[k] for k in ('plan_sha256','signed_txid')):
        raise ValueError('Previous observation belongs to another payment')
    if observation is None or observation.get('available') is not True:
        return dict(base,status='unknown',confirmed=False,reason='node observation unavailable')
    if observation.get('txid')!=binding['signed_txid']:
        raise ValueError('Observed transaction differs')
    confirmations=observation.get('confirmations')
    if type(confirmations) is not int: raise ValueError('Integer confirmations required')
    if confirmations < 0 or observation.get('conflicted') is True:
        return dict(base,status='conflicted',confirmed=False)
    was_confirmed=previous is not None and previous.get('confirmed') is True
    if confirmations==0:
        status='reorged' if was_confirmed else ('mempool' if observation.get('in_mempool') is True else 'not_seen')
        return dict(base,status=status,confirmed=False)
    height=observation.get('block_height');tip=observation.get('tip_height')
    block=observation.get('blockhash');active=observation.get('active_hash_at_height')
    if type(height) is not int or type(tip) is not int or not 0<=height<=tip:
        raise ValueError('Valid block and tip heights required')
    if not isinstance(block,str) or not re.fullmatch('[a-f0-9]{64}',block):
        raise ValueError('Valid transaction block hash required')
    if not isinstance(active,str) or not re.fullmatch('[a-f0-9]{64}',active):
        raise ValueError('Active-chain lookup required')
    if active!=block:
        return dict(base,status='reorged',confirmed=False)
    if confirmations!=tip-height+1:
        return dict(base,status='inconsistent_snapshot',confirmed=False)
    confirmed=confirmations>=required_confirmations
    return dict(base,status='confirmed' if confirmed else 'confirming',confirmed=confirmed,
                confirmations=confirmations,blockhash=block,block_height=height,tip_height=tip,
                confirmation_lost=bool(was_confirmed and not confirmed))
