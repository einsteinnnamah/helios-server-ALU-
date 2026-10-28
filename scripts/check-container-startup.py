"""Exercise the actual production entrypoint using CI-only PostgreSQL/credentials.

No deployment, production database or student account is used. The command also
checks the supervised completion process; importing Django alone misses this.
"""
import http.client
import json
import subprocess
import sys
import tempfile
import time
import uuid


def docker(*args, check=True):
    return subprocess.run(['docker', *args], check=check, text=True,
                          capture_output=True, timeout=120)


def probe(path, host='helios.example', secret=None):
    connection = http.client.HTTPConnection('127.0.0.1', 10001, timeout=3)
    headers = {'Host': host, 'X-Forwarded-Proto': 'https'}
    if secret:
        headers['Authorization'] = 'Bearer ' + secret
    try:
        connection.request('GET', path, headers=headers)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def enable_ci_postgres_tls(container):
    # Production settings require SSL. Exercise that setting instead of
    # weakening it for the test. Only the explicitly supplied CI service changes.
    image = docker('inspect', '--format', '{{.Config.Image}}', container).stdout.strip()
    if image != 'postgres:16':
        raise RuntimeError('Expected the isolated PostgreSQL 16 CI service')
    with tempfile.TemporaryDirectory(prefix='alu-ci-tls-') as directory:
        key, cert = directory + '/server.key', directory + '/server.crt'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                        '-nodes', '-days', '1', '-subj', '/CN=localhost',
                        '-keyout', key, '-out', cert], check=True,
                       capture_output=True, timeout=30)
        docker('cp', key, container + ':/tmp/alu-ci-server.key')
        docker('cp', cert, container + ':/tmp/alu-ci-server.crt')
    docker('exec', '--user', 'root', container, 'chown', 'postgres:postgres',
           '/tmp/alu-ci-server.key', '/tmp/alu-ci-server.crt')
    docker('exec', '--user', 'root', container, 'chmod', '600', '/tmp/alu-ci-server.key')
    for command in [
        "ALTER SYSTEM SET ssl_cert_file='/tmp/alu-ci-server.crt'",
        "ALTER SYSTEM SET ssl_key_file='/tmp/alu-ci-server.key'",
        "ALTER SYSTEM SET ssl='on'",
        'SELECT pg_reload_conf()',
    ]:
        docker('exec', container, 'psql', '-U', 'postgres', '-d', 'helios',
               '-v', 'ON_ERROR_STOP=1', '-c', command)


def main():
    if len(sys.argv) != 3:
        raise SystemExit('Usage: check-container-startup.py IMAGE POSTGRES_CI_CONTAINER_ID')
    enable_ci_postgres_tls(sys.argv[2])
    name = 'alu-startup-' + uuid.uuid4().hex[:12]
    recovery = 'ci-only-recovery-secret-with-more-than-thirty-two-bytes'
    env = {
        'DATABASE_URL': 'postgresql://postgres:postgres@127.0.0.1:5432/helios',
        'SECRET_KEY': 'ci-only-django-secret-with-more-than-thirty-two-bytes',
        'EMAIL_OPTOUT_SECRET': 'ci-only-optout-secret-with-more-than-thirty-two-bytes',
        'ALU_BRIDGE_SECRET': 'ci-only-bridge-secret-with-more-than-thirty-two-bytes',
        'RECOVERY_SECRET': recovery,
        'ALU_BRIDGE_APP_ORIGIN': 'https://alu.example',
        'ALU_BRIDGE_CLIENT_ID': 'alu-helios-demo',
        'ALU_STUDENT_DOMAIN': 'alustudent.com',
        'AUTH_ENABLED_SYSTEMS': 'alu',
        'URL_HOST': 'https://helios.example',
        'ALU_VOTE_VERIFICATION_BACKEND': 'database',
        'ALU_AUTOMATIC_COMPLETION': '1',
        'PORT': '10001',
    }
    args = ['run', '--detach', '--name', name, '--network', 'host']
    for key, value in env.items():
        args.extend(['--env', key + '=' + value])
    args.append(sys.argv[1])
    try:
        docker(*args)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = docker('inspect', '--format', '{{.State.Running}}', name)
            if state.stdout.strip() != 'true':
                raise RuntimeError('Production entrypoint exited before readiness')
            try:
                if probe('/', host='containerstarthealthcheck')[0] == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.5)
        else:
            raise RuntimeError('Production entrypoint did not become ready')
        # Allow background management commands to execute their initial queries.
        time.sleep(2)
        status, headers, _ = probe('/helios/elections/00000000-0000-4000-8000-000000000000/ui/ballot')
        if status != 404 or headers.get('X-Voting-Automatic-Completion') != 'enabled':
            raise RuntimeError('Automatic completion is not enabled in the live HTTP process')
        status, _, body = probe('/internal/verification-state', secret=recovery)
        if status != 200 or json.loads(body).get('pending') is not False:
            raise RuntimeError('Recovery/completion metadata queries failed')
        docker('exec', name, 'python', '-c', r'''
import django, pathlib
django.setup()
from django.db.migrations.recorder import MigrationRecorder
from helios.models import ElectionCompletionJob
assert MigrationRecorder.Migration.objects.filter(app='helios', name='0018_election_completion').exists()
assert not ElectionCompletionJob.objects.exists()
commands=[]
for path in pathlib.Path('/proc').glob('[0-9]*/cmdline'):
    try: commands.append(path.read_bytes().split(b'\x00'))
    except OSError: pass
for worker in (b'run_election_completion', b'run_vote_verifier', b'run_vote_confirmation_sender'):
    assert any(worker in cmd and b'manage.py' in cmd for cmd in commands), worker
''')
        print('Production entrypoint, migrations, HTTP, recovery and supervised workers passed.')
    except Exception:
        # This container receives only the public CI placeholder values above.
        logs = docker('logs', '--tail', '120', name, check=False)
        sys.stderr.write(logs.stdout + logs.stderr)
        raise
    finally:
        docker('stop', '--time', '5', name, check=False)
        docker('rm', name, check=False)


if __name__ == '__main__':
    main()
