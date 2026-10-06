"""Render Free demo only: synchronous crypto tasks, no worker and no SMTP."""
import os
import re
import uuid
from django.core.exceptions import ImproperlyConfigured
from settings import *

if os.environ.get('HELIOS_DEMO_MODE') != '1':
  raise ImproperlyConfigured('This settings module requires HELIOS_DEMO_MODE=1.')
for required in ('DATABASE_URL', 'SECRET_KEY', 'EMAIL_OPTOUT_SECRET',
                 'ALU_BRIDGE_APP_ORIGIN', 'ALU_BRIDGE_SECRET', 'ALU_STUDENT_DOMAIN'):
  if not os.environ.get(required):
    raise ImproperlyConfigured(f'Missing required demo setting: {required}')

DEBUG = False
AUTH_ENABLED_SYSTEMS = ['alu']
AUTH_DEFAULT_SYSTEM = 'alu'
HELIOS_ADMIN_ONLY = True
HELIOS_VOTERS_UPLOAD = False
if len(ALU_BRIDGE_SECRET.encode()) < 32:
  raise ImproperlyConfigured('ALU_BRIDGE_SECRET must contain at least 32 bytes.')
from helios_auth.bridge_protocol import https_origin
ALU_BRIDGE_APP_ORIGIN = https_origin(ALU_BRIDGE_APP_ORIGIN)
if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', ALU_BRIDGE_CLIENT_ID):
  raise ImproperlyConfigured('Invalid bridge client identifier.')
try:
  if any(str(uuid.UUID(value)) != value for value in ALU_BRIDGE_ELECTIONS):
    raise ValueError()
except ValueError as exc:
  raise ImproperlyConfigured('Use canonical comma-separated election UUIDs.') from exc
ALU_STUDENT_DOMAIN = os.environ['ALU_STUDENT_DOMAIN'].strip().lower().lstrip('@')
if ALU_STUDENT_DOMAIN != 'alustudent.com':
  raise ImproperlyConfigured('This bridge requires the exact alustudent.com domain.')
hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
URL_HOST = os.environ.get('URL_HOST') or (f'https://{hostname}' if hostname else '')
URL_HOST = URL_HOST.rstrip('/')
if not URL_HOST.startswith('https://'):
  raise ImproperlyConfigured('Set an HTTPS URL_HOST or RENDER_EXTERNAL_HOSTNAME.')
URL_HOST = https_origin(URL_HOST)
SECURE_URL_HOST = URL_HOST
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', hostname or '').split(',')
if not all(ALLOWED_HOSTS) or '*' in ALLOWED_HOSTS:
  raise ImproperlyConfigured('Set exact ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME.')
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SECURE = True
TIME_ZONE = 'Africa/Kigali'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
# Even eager .delay() serializes tasks; a memory transport avoids broker access.
CELERY_BROKER_URL = 'memory://'
# Notifications still run, but SMTP failures cannot interrupt casting/tallying.
# No email content or ballot trackers are printed to logs.
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
