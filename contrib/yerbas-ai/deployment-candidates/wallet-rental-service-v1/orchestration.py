"""Owner-side fixed testnet adapters for the durable wallet workflow.

Deployment must pin this module and its dependencies. No arbitrary workload,
destination, signing-key path or command is accepted from the wallet.
"""
import json
import re
import subprocess
import time
from pathlib import Path
from context import OUT, digest, wallet
from paid_pilot import session
from binding_rules import checked_binding
from execution_window import require_window, require_preaccept_window


class Adapter:
    def __init__(self, context):
        self.context = context
        self.helper = OUT / 'yerbas-ai-wallet-5.0.0.0-workflow1/slot-provider-control/provider_start.py'

    def review(self, request):
        value = wallet('marketplace.reviewslotwork', {'assignment_id': request['assignment']})
        terms = value['terms']
        if (terms['quote_id'] != self.context.quote or terms['quote_id'] != request['quote'] or
                terms['assignment_id'] != request['assignment'] or
                digest(terms) != request['terms_sha256'] or
                value['assignment_sha256'] != request['terms_sha256']):
            raise ValueError('Exact authorized assignment required')
        return value

    def preflight(self, request):
        self.context.network()
        quote = wallet('marketplace.order', {'quote_id': request['quote']})
        terms = quote['terms']
        if (terms['quote_id'] != request['quote'] or terms['buyer'] != 'u26-2T' or
                terms['units'] != 1 or terms['parallelism'] != 1 or
                terms['maximum_work_cost_base_units'] != request['maximum_base_units'] or
                terms['payment_policy']['provider_reward_base_units'] != request['provider_reward_base_units'] or
                digest(terms) != quote['quote_sha256'] or quote['accepted'] is not True):
            raise ValueError('Exact accepted single-unit quote required')
        funding = self.context.funding()
        if funding['txid'] != request['deposit_txid'] or funding['vout'] != request['deposit_vout']:
            raise ValueError('Wallet deposit differs')
        review = self.review(request)
        require_preaccept_window(review, time.time())
        plan = {'quotes': [request['quote']], 'slots': ['gpu-1']}
        with session(self.context.state / 'commands', plan) as pilot:
            checked_binding(review, pilot.state(), pilot.ids, plan, int(time.time()))
        self.context.save_once('quote.json', quote)
        self.context.save_once('review.json', review)
        self.context.save_once('plan.json', plan)

    def helper_request(self, operation, request):
        result = subprocess.run(['/usr/bin/python3', '-I', '-B', str(self.helper)],
                                input=json.dumps({'operation': operation, 'assignment': request['assignment'],
                                                  'reviewed_digest': request['terms_sha256']}),
                                text=True, capture_output=True, timeout=100)
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError('Protected execution reply uncertain; reconciliation required')
        value = json.loads(result.stdout)
        if operation == 'preview' and value.get('review_ready') is not True:
            raise ValueError('Protected execution preview refused')
        if operation == 'run':
            receipt = value.get('protected_receipt', {})
            if (value.get('assignment') != request['assignment'] or
                    receipt.get('run_id') != request['assignment'] or
                    receipt.get('submission_acknowledged') is not True):
                raise ValueError('Protected execution acknowledgment differs')
        return value

    def perform(self, step, request, results):
        c = self.context
        if step == 'bind':
            with session(c.state / 'commands', c.load('plan.json')) as pilot:
                return pilot.bind(self.review(request), before_acceptance=True)
        if step == 'accept':
            return wallet('marketplace.acceptslotwork', {'assignment_id': request['assignment'],
                                                        'reviewed_digest': request['terms_sha256']})
        if step == 'execute':
            require_window(c.load('review.json'), results['accept'], time.time())
            preview = self.helper_request('preview', request)
            c.save_once('execution-preview.json', preview)
            require_window(c.load('review.json'), results['accept'], time.time())
            return self.helper_request('run', request)
        if step == 'collect':
            until = time.monotonic() + 240
            while True:
                status = wallet('provider.slot_status', {'run_id': request['assignment']})
                if status.get('state') == 'completed':
                    break
                if status.get('state') in ('failed', 'cancelled', 'interrupted') or time.monotonic() >= until:
                    raise ValueError('Work incomplete; retain deposit and execution for recovery')
                time.sleep(2)
            fence = wallet('provider.slot_fence', {'run_id': request['assignment']})
            status = wallet('provider.slot_status', {'run_id': request['assignment']})
            if status.get('state') != 'completed' or status.get('restart_blocked') is not True:
                raise ValueError('Completed fenced work required')
            value = c.remote('results')
            rows = value['results']
            if (len(rows) != 1 or rows[0]['assignment'] != request['assignment'] or
                    rows[0]['terms_sha256'] != request['terms_sha256'] or
                    not re.fullmatch('[a-f0-9]{32}', rows[0].get('receipt') or '')):
                raise ValueError('Exact completed receipt required')
            c.save_once('results.json', value)
            c.save_once('execution-fence.json', fence)
            return value
        if step == 'verify':
            from verification import verify, installed_command
            evidence = Path.home() / '.local/share/yerbas-ai-migration-v1/operator-v1/evidence'
            return verify(c, evidence, installed_command)
        if step == 'prepare_payment':
            from prepare_payment import prepare
            return prepare(c)
        if step in ('preview_payment', 'pay'):
            from payout import settle
            return settle(c, apply=step == 'pay')
        if step == 'confirm_payment':
            import sys
            sys.path.insert(0, str(OUT / 'coordinator-fencing-v1'))
            from chain_reader import node
            from payment_chain_anchor import anchor, agree
            from context import GENESIS
            txid = c.load('consensus-settlement.json')['result']['txid']
            if not re.fullmatch('[a-f0-9]{64}', txid):
                raise ValueError('Retained payout identity required')
            until = time.monotonic() + 3600
            while True:
                confirmations = [node(host)('getrawtransaction', txid, True).get('confirmations', 0)
                                 for host in ('u26-2T', 'anno2-u26')]
                if min(confirmations) >= 6:
                    anchors = [anchor(node(host), genesis=GENESIS, txid=txid)
                               for host in ('u26-2T', 'anno2-u26')]
                    agree(*anchors)
                    return {'txid': txid, 'anchors': anchors}
                if time.monotonic() >= until:
                    raise ValueError('Confirmation wait expired; observe original payout, never resend')
                time.sleep(5)
        if step == 'release':
            from close_payment import close
            return close(c)
        raise ValueError('Unknown wallet workflow stage')
