"""CLI client; the same HTTP API can be consumed asynchronously by Qt."""
import argparse
import http.client
import json
from pathlib import Path
import sys
import time


class APIClientError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Client:
    def __init__(self, directory):
        self.session = json.loads((directory / 'session.json').read_text())

    def request(self, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.session['port'], timeout=15)
        try:
            conn.request('GET' if body is None else 'POST', path,
                         None if body is None else json.dumps(body),
                         {'Authorization': 'Bearer '+self.session['token'],
                          'Content-Type': 'application/json'})
            response = conn.getresponse()
            value = json.loads(response.read())
            if response.status >= 400:
                raise APIClientError(response.status, value.get('error', 'Request failed'))
            return value
        finally:
            conn.close()

    def generate(self, model, messages, limit):
        job = self.request('/v1/jobs', {'mode': 'local', 'model': model,
                                      'messages': messages, 'max_output_tokens': limit})
        job_id = job['id']
        print(f'Local request: {job_id}', file=sys.stderr)
        try:
            while job['state'] in ('running', 'cancelling'):
                time.sleep(.2)
                job = self.request('/v1/jobs/'+job_id)
        except KeyboardInterrupt:
            self.request('/v1/jobs/'+job_id+'/cancel', {})
            raise RuntimeError('Cancellation requested; use status/job to confirm completion')
        if job['state'] != 'completed':
            raise RuntimeError(job.get('error', job['state']))
        return job['result']['text']


def main():
    parser = argparse.ArgumentParser(description='Yerbas AI CLI: local-only prototype')
    parser.add_argument('--state-dir', required=True, type=Path)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('models')
    commands.add_parser('hardware')
    commands.add_parser('runtime')
    provider = commands.add_parser('provider').add_subparsers(dest='provider_command', required=True)
    for name in ('status', 'pause', 'resume'):
        provider.add_parser(name)
    config = commands.add_parser('config').add_subparsers(dest='config_command', required=True)
    config.add_parser('show')
    config.add_parser('set-default-model').add_argument('model')
    config.add_parser('clear-default-model')
    schedule = commands.add_parser('schedule').add_subparsers(dest='schedule_command', required=True)
    schedule.add_parser('show')
    schedule.add_parser('disable')
    window = schedule.add_parser('set')
    window.add_argument('--timezone', required=True, help='IANA timezone, for example America/Los_Angeles')
    window.add_argument('--days', required=True, help='Comma-separated starting weekdays: mon,tue,wed,thu,fri,sat,sun')
    window.add_argument('--start', required=True, help='24-hour HH:MM')
    window.add_argument('--end', required=True, help='24-hour HH:MM; earlier than start means overnight')
    for name in ('job', 'cancel'):
        commands.add_parser(name).add_argument('id')
    for name in ('prompt', 'chat'):
        command = commands.add_parser(name)
        command.add_argument('--local', required=True, action='store_true')
        command.add_argument('--model', help='Installed model, or omit to use the saved default')
        command.add_argument('--max-output-tokens', type=int, default=256)
        if name == 'prompt':
            command.add_argument('text')
    args = parser.parse_args()
    try:
        client = Client(args.state_dir)
        if args.command in ('status', 'models', 'hardware', 'runtime'):
            print(json.dumps(client.request('/v1/'+args.command), indent=2))
        elif args.command == 'provider':
            body = None if args.provider_command == 'status' else {'paused': args.provider_command == 'pause'}
            print(json.dumps(client.request('/v1/provider/status' if body is None else '/v1/provider/control', body), indent=2))
        elif args.command in ('config', 'schedule'):
            prefs = client.request('/v1/preferences')
            changes = None
            if args.command == 'config':
                if args.config_command == 'show':
                    print(json.dumps(prefs, indent=2))
                else:
                    changes = {'default_model': args.model if args.config_command == 'set-default-model' else None}
            elif args.schedule_command == 'show':
                print(json.dumps({'schedule': prefs['schedule'],
                                  'availability': client.request('/v1/availability')}, indent=2))
            elif args.schedule_command == 'disable':
                changes = {'schedule': dict(prefs['schedule'], enabled=False)}
            else:
                names = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
                try:
                    days = [names.index(day.strip().lower()) for day in args.days.split(',')]
                except ValueError:
                    raise RuntimeError('Use comma-separated weekdays: mon,tue,wed,thu,fri,sat,sun') from None
                changes = {'schedule': {'enabled': True, 'timezone': args.timezone,
                                        'days': days, 'start': args.start, 'end': args.end}}
            if changes is not None:
                print(json.dumps(client.request('/v1/preferences',
                                               {'revision': prefs['revision'], 'changes': changes}), indent=2))
                if args.command == 'schedule':
                    print('Schedule saved as policy only; network contribution is not implemented.', file=sys.stderr)
        elif args.command in ('job', 'cancel'):
            path = '/v1/jobs/'+args.id
            result = client.request(path+'/cancel', {}) if args.command == 'cancel' else client.request(path)
            print(json.dumps(result, indent=2))
        elif args.command == 'prompt':
            print(client.generate(args.model, [{'role': 'user', 'content': args.text}], args.max_output_tokens))
        else:
            print('LOCAL chat. History stays in memory. /reset clears it; /quit exits.')
            messages = []
            while True:
                try:
                    prompt = input('you> ')
                except (EOFError, KeyboardInterrupt):
                    break
                if prompt == '/quit':
                    break
                if prompt == '/reset':
                    messages = []
                    continue
                proposed = messages + [{'role': 'user', 'content': prompt}]
                try:
                    answer = client.generate(args.model, proposed, args.max_output_tokens)
                except RuntimeError as exc:
                    print(f'Error: {exc}', file=sys.stderr)
                    continue
                print('ai> '+answer)
                messages = proposed + [{'role': 'assistant', 'content': answer}]
    except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
