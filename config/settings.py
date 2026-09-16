import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
TESTING = 'test' in __import__('sys').argv or 'pytest' in __import__('sys').modules
SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG or TESTING:
        SECRET_KEY = 'local-development-only-do-not-deploy-this-secret'
    else:
        raise ImproperlyConfigured('Configure SECRET_KEY before starting the server.')
PUBLIC_URL = os.getenv('PUBLIC_URL', 'http://localhost:8000').rstrip('/')
ALLOWED_HOSTS = [x.strip() for x in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',') if x.strip()]
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv('CSRF_TRUSTED_ORIGINS', PUBLIC_URL).split(',') if x.strip()]
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','django_otp','django_otp.plugins.otp_totp','django_otp.plugins.otp_static','portal.apps.PortalConfig']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django_otp.middleware.OTPMiddleware','portal.middleware.StaffMFAMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware','portal.middleware.SecurityHeadersMiddleware','portal.analytics.AnalyticsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR / 'portal' / 'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','portal.context.site_context']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': dj_database_url.config(default=f'sqlite:///{BASE_DIR / "db.sqlite3"}', conn_max_age=0, conn_health_checks=True)}
if TESTING:
    DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'}}
if not DEBUG and not TESTING and DATABASES['default']['ENGINE'].endswith('sqlite3'):
    raise ImproperlyConfigured('Production requires DATABASE_URL for PostgreSQL.')
if DATABASES['default']['ENGINE'].endswith('postgresql'):
    DATABASES['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
AUTH_USER_MODEL = 'portal.User'
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator','OPTIONS':{'min_length':12}},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher','django.contrib.auth.hashers.PBKDF2PasswordHasher']
PASSWORD_RESET_TIMEOUT = 3600
LOGIN_URL = '/iniciar-sesion/'
LOGIN_REDIRECT_URL = '/panel/'
LOGOUT_REDIRECT_URL = '/'
LANGUAGE_CODE = 'es-mx'
TIME_ZONE = 'America/Mexico_City'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = Path(os.getenv('MEDIA_ROOT', str(BASE_DIR / 'media')))
STORAGES = {'default':{'BACKEND':'portal.storage.PrivateStorage'},'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage' if not DEBUG else 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FILES = 1
FILE_UPLOAD_PERMISSIONS = 0o600
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o700
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 86400 * 7
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG and not TESTING
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
STAFF_MFA_REQUIRED = True
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND','django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST','')
EMAIL_PORT = int(os.getenv('EMAIL_PORT','587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER','')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD','')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS','true').lower() == 'true'
EMAIL_USE_SSL = os.getenv('EMAIL_USE_SSL','false').lower() == 'true'
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL','IMC México <no-reply@localhost>')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
ADMIN_EMAIL = os.getenv('ADMIN_EMAIL','')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY','')
OPENAI_MODEL = os.getenv('OPENAI_MODEL','gpt-4.1-mini')
OPENAI_TIMEOUT = int(os.getenv('OPENAI_TIMEOUT','90'))
AI_JOB_STALE_SECONDS = int(os.getenv('AI_JOB_STALE_SECONDS','600'))
FFMPEG_BINARY = os.getenv('FFMPEG_BINARY','ffmpeg')
FFPROBE_BINARY = os.getenv('FFPROBE_BINARY','ffprobe')
for key in ['PRIVATE_S3_BUCKET','PRIVATE_S3_ENDPOINT_URL','PRIVATE_S3_REGION','PRIVATE_S3_ACCESS_KEY_ID','PRIVATE_S3_SECRET_ACCESS_KEY']:
    globals()[key] = os.getenv(key,'')
LOGGING = {'version':1,'disable_existing_loggers':False,'formatters':{'redacted':{'()':'portal.security.RedactingFormatter','format':'%(levelname)s %(name)s %(message)s'}},'handlers':{'console':{'class':'logging.StreamHandler','formatter':'redacted'}},'root':{'handlers':['console'],'level':'INFO'},'loggers':{'httpx':{'level':'WARNING'},'httpcore':{'level':'WARNING'},'httpx2':{'level':'WARNING'},'httpcore2':{'level':'WARNING'},'openai':{'level':'WARNING'}}}
