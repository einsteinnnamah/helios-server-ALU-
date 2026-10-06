"""Render Free demo only: synchronous crypto tasks, no worker and no SMTP."""
import os
from django.core.exceptions import ImproperlyConfigured
from settings import *

if os.environ.get('HELIOS_DEMO_MODE') != '1':
  raise ImproperlyConfigured('This settings module requires HELIOS_DEMO_MODE=1.')
for required in ('DATABASE_URL', 'SECRET_KEY', 'EMAIL_OPTOUT_SECRET',
                 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'ALU_STUDENT_DOMAIN'):
  if not os.environ.get(required):
    raise ImproperlyConfigured(f'Missing required demo setting: {required}')

DEBUG = False
AUTH_ENABLED_SYSTEMS = ['google']
ALU_STUDENT_DOMAIN = os.environ['ALU_STUDENT_DOMAIN'].strip().lower().lstrip('@')
if not ALU_STUDENT_DOMAIN or '@' in ALU_STUDENT_DOMAIN or '/' in ALU_STUDENT_DOMAIN:
  raise ImproperlyConfigured('ALU_STUDENT_DOMAIN must be a bare email domain.')
hostname = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
URL_HOST = os.environ.get('URL_HOST') or (f'https://{hostname}' if hostname else '')
URL_HOST = URL_HOST.rstrip('/')
if not URL_HOST.startswith('https://'):
  raise ImproperlyConfigured('Set an HTTPS URL_HOST or RENDER_EXTERNAL_HOSTNAME.')
SECURE_URL_HOST = URL_HOST
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', hostname or '').split(',')
if not all(ALLOWED_HOSTS) or '*' in ALLOWED_HOSTS:
  raise ImproperlyConfigured('Set exact ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME.')
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
TIME_ZONE = 'Africa/Kigali'
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
# Even eager .delay() serializes tasks; a memory transport avoids broker access.
CELERY_BROKER_URL = 'memory://'
# Notifications still run, but SMTP failures cannot interrupt casting/tallying.
# No email content or ballot trackers are printed to logs.
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
