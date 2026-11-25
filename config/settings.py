import os
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = False

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '192.168.100.57',
     'uncured-persuader-ludicrous.ngrok-free.dev',
]

CSRF_TRUSTED_ORIGINS = ['https://uncured-persuader-ludicrous.ngrok-free.dev' ]

SECURE_PROXY_SSL_HEADER = (
    'HTTP_X_FORWARDED_PROTO', 'https'
)

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

INSTALLED_APPS=['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','core']
MIDDLEWARE=['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','core.middleware.BloqueoPinMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF='config.urls'
TEMPLATES=[{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[BASE_DIR/'templates'],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.debug','django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages','core.contexto.alertas']}}]
WSGI_APPLICATION='config.wsgi.application'
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':BASE_DIR/'db.sqlite3'}}
AUTH_PASSWORD_VALIDATORS=[{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE='es'; TIME_ZONE='America/Guayaquil'; USE_I18N=True; USE_TZ=True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
# CONFIGURACIÓN DE AUTENTICACIÓN

LOGIN_URL = 'bienvenida'
LOGIN_REDIRECT_URL = 'inicio'
LOGOUT_REDIRECT_URL = 'bienvenida'

# CONFIGURACIÓN DE SESIONES

SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend'  # el correo de recuperación se imprime en la terminal (demo)
DEFAULT_FROM_EMAIL='CuentaFácil <no-responder@cuentafacil.local>'

PIN_INACTIVIDAD_SEGUNDOS=300  # 5 minutos
PIN_MAX_INTENTOS=5
PIN_BLOQUEO_MINUTOS=5
