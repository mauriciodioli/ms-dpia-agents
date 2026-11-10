from dotenv import load_dotenv
import os

from pathlib import Path
from utils.google_oauth import google_client_id

BASE_DIR = Path(__file__).resolve().parent

for env_path in (
	BASE_DIR / '.env',
	Path('/src/.env'),
):
	if env_path.exists():
		load_dotenv(env_path)


user = os.environ["MYSQL_USER"]
password = os.environ["MYSQL_PASSWORD"]
host = os.environ["MYSQL_HOST"]
database = os.environ["MYSQL_DATABASE"]
port = os.environ["MYSQL_PORT"]  # Asegúrate de tener la variable de entorno MYSQL_PORT configurada



# Configuración de la base de datos de producción
MYSQL_USER_PRODUCCION = os.environ["MYSQL_USER_PRODUCCION"]
MYSQL_PASSWORD_PRODUCCION = os.environ["MYSQL_PASSWORD_PRODUCCION"]
MYSQL_HOST_PRODUCCION = os.environ["MYSQL_HOST_PRODUCCION"]
MYSQL_PORT_PRODUCCION = os.environ["MYSQL_PORT_PRODUCCION"]
DATABASE_CONNECTION_URI = f'mysql+pymysql://{MYSQL_USER_PRODUCCION}:{MYSQL_PASSWORD_PRODUCCION}@{MYSQL_HOST_PRODUCCION}:{MYSQL_PORT_PRODUCCION}/{database}?charset=utf8mb4'
#DATABASE_CONNECTION_URI = f'mysql+pymysql://{user}:{password}@{host}/{database}'
#DATABASE_CONNECTION_URI = f'mysql+pymysql://{user}:{password}@{host}:{port}/{database}'
#DATABASE_CONNECTION_URI = f'mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4'

#print(DATABASE_CONNECTION_URI)

# Obtener las variables de entorno
sdk_prueba = os.getenv('sdk_prueba')#test
sdk_produccion = os.getenv('sdk_produccion') #test
MERCADOPAGO_KEY_API = os.getenv('MERCADOPAGO_KEY_API')#para produccion
MERCADOPAGO_URL = os.getenv('MERCADOPAGO_URL')
DOMAIN = os.getenv('DOMAIN')
SIP_PROVIDER = os.getenv('SIP_PROVIDER')
SIP_SERVER = os.getenv('SIP_SERVER')
SIP_USER = os.getenv('SIP_USER')
SIP_PASSWORD = os.getenv('SIP_PASSWORD')
SIP_CALLER_ID = os.getenv('SIP_CALLER_ID')
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')


# ===== Configuración de Flask (app.config.from_object(config) solo toma los MAYÚSCULA) =====
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "local-demo-only-change-before-deployment")
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_NAME = "ms_dpia_agents_session"

GOOGLE_OAUTH_CREDENTIAL = Path(os.environ.get(
    "GOOGLE_OAUTH_CREDENTIAL", "utils/google_oauth_credentials.json"))
if not GOOGLE_OAUTH_CREDENTIAL.is_absolute():
    GOOGLE_OAUTH_CREDENTIAL = BASE_DIR / GOOGLE_OAUTH_CREDENTIAL
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip() or google_client_id(GOOGLE_OAUTH_CREDENTIAL)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8302"))
DEBUG = os.environ.get("FLASK_ENV", "development") != "production"

# Flask-SQLAlchemy lee específicamente SQLALCHEMY_DATABASE_URI
SQLALCHEMY_DATABASE_URI = DATABASE_CONNECTION_URI
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Server-side DPIA catalogs (never rendered into templates).
SCRAPEADOR_SERVICE_KEY = os.environ.get("SCRAPEADOR_SERVICE_KEY", "")
DPIA_CONNECT_TIMEOUT = float(os.environ.get("DPIA_CONNECT_TIMEOUT", "3.05"))
DPIA_READ_TIMEOUT = float(os.environ.get("DPIA_READ_TIMEOUT", "10"))
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')


# Server-only credential with scraper:write for explicit marketplace dispatch.
DPIA_SCRAPING_KEY = os.environ.get('DPIA_SCRAPING_KEY', '')
MAX_CONTENT_LENGTH = 10 * 1024 * 1024

# Explicit opt-in required before any live OpenAI/Apify functional test.
LIVE_PROVIDER_CALLS_ENABLED = os.environ.get('LIVE_PROVIDER_CALLS_ENABLED', 'false').lower() == 'true'

# Explicit opt-in; the route also requires Flask development/debug mode.
ENABLE_TEST_SCRAPING_CREDITS = os.environ.get('ENABLE_TEST_SCRAPING_CREDITS', 'false').lower() == 'true'

# Analytics uses the existing logs table; never creates or migrates tables.
ACTIVITY_LOGGING_ENABLED = os.getenv('ACTIVITY_LOGGING_ENABLED', 'true').lower() == 'true'
# Configure only actual reverse-proxy IPs/subnets. X-Real-IP must be overwritten by that proxy.
ACTIVITY_TRUSTED_PROXIES = os.getenv('ACTIVITY_TRUSTED_PROXIES', '')

# Configuration only: no Redis client, connection or agent queue is started here.
REDIS_HOST = os.environ.get('REDIS_HOST', '').strip()
REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
REDIS_DB = int(os.environ.get('REDIS_DB', '0'))
REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')

# Exact WSGI peer IPs only. Enable after verifying the Nginx header contract;
# no default trust in loopback, Docker networks, or client-supplied headers.
AGENTS_TRUSTED_PROXY_IPS = os.getenv('AGENTS_TRUSTED_PROXY_IPS', '').strip()

# Shared across web and external workers; never store this master key in MySQL.
AGENTS_INTEGRATION_MASTER_KEY = os.getenv('AGENTS_INTEGRATION_MASTER_KEY', '')
DPIA_SCRAPER_BASE_URL = os.getenv('DPIA_SCRAPER_BASE_URL', 'https://api.dpia.site/api/scraper/v1')
DPIA_SCRAPER_ALLOWED_HOSTS = tuple(filter(None, (x.strip().lower() for x in os.getenv(
    'DPIA_SCRAPER_ALLOWED_HOSTS', 'api.dpia.site').split(','))))
DPIA_SCRAPER_TIMEOUT_SECONDS = int(os.getenv('DPIA_SCRAPER_TIMEOUT_SECONDS', '120'))
# Explicit model allowlist, not a claim of access. Enable also verifies /models/{id}.
AGENTS_OPENAI_MODELS = tuple(filter(None, (x.strip() for x in os.getenv(
    'AGENTS_OPENAI_MODELS', OPENAI_MODEL).split(','))))
