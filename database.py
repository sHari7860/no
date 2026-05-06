import os
from urllib.parse import urlparse, unquote

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    _DATABASE_DRIVER = 'psycopg2'
except ImportError:
    import pg8000
    _DATABASE_DRIVER = 'pg8000'

from models import init_db


def get_database_url():
    return os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/UNITEC")


def _parse_database_url(url: str):
    parsed = urlparse(url)
    return {
        'user': unquote(parsed.username) if parsed.username else None,
        'password': unquote(parsed.password) if parsed.password else None,
        'host': parsed.hostname or 'localhost',
        'port': parsed.port or 5432,
        'database': parsed.path.lstrip('/') if parsed.path else None,
    }


def get_db_connection(dict_cursor: bool = False):
    """Establece conexión con PostgreSQL."""
    db_url = get_database_url()

    if _DATABASE_DRIVER == 'psycopg2':
        cursor_factory = RealDictCursor if dict_cursor else None
        return psycopg2.connect(db_url, cursor_factory=cursor_factory)

    db_params = _parse_database_url(db_url)
    return pg8000.connect(
        user=db_params['user'],
        password=db_params['password'],
        host=db_params['host'],
        port=db_params['port'],
        database=db_params['database'],
    )


def init_app():
    """Inicializa la aplicación creando las tablas si no existen."""
    init_db()
