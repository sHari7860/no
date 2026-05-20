import os
from urllib.parse import urlparse, unquote
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    _DATABASE_DRIVER = 'psycopg2'
except ImportError:
    try:
        import pg8000
        _DATABASE_DRIVER = 'pg8000'
    except ImportError:
        _DATABASE_DRIVER = None

from config import SQLITE_DB


def get_database_url():
    """Retorna DATABASE_URL si está en entorno. Si no, detecta sqlite en data/ si existe."""
    env = os.getenv('DATABASE_URL')
    if env:
        return env

    # Si existe archivo sqlite local, usarlo por conveniencia
    if Path(SQLITE_DB).exists():
        return f'sqlite:///{Path(SQLITE_DB).as_posix()}'

    # Por defecto asumir PostgreSQL en desarrollo (no forzar cambios en SQL usado)
    return os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/UNITEC1")


def is_sqlite_database():
    return get_database_url().startswith('sqlite:')


class SqliteCursor:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, sql, params=None):
        sql = self._translate(sql)
        return self._inner.execute(sql, params or ())

    def executemany(self, sql, seq_of_params):
        sql = self._translate(sql)
        return self._inner.executemany(sql, seq_of_params)

    def executescript(self, sql_script):
        return self._inner.executescript(self._translate(sql_script))

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @staticmethod
    def _translate(sql):
        return sql.replace('%s', '?') if sql else sql


class SqliteConnection:
    def __init__(self, connection):
        object.__setattr__(self, '_connection', connection)
        self._connection.execute('PRAGMA foreign_keys = ON')

    def cursor(self, *args, **kwargs):
        return SqliteCursor(self._connection.cursor(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def __setattr__(self, name, value):
        if name == '_connection':
            object.__setattr__(self, name, value)
        else:
            setattr(self._connection, name, value)


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
    db_url = get_database_url()

    if db_url.startswith('sqlite:'):
        import sqlite3
        path = db_url.split(':///')[-1]
        raw_conn = sqlite3.connect(path, check_same_thread=False)
        conn = SqliteConnection(raw_conn)
        if dict_cursor:
            conn.row_factory = sqlite3.Row
        return conn

    if _DATABASE_DRIVER == 'psycopg2':
        cursor_factory = RealDictCursor if dict_cursor else None
        return psycopg2.connect(db_url, cursor_factory=cursor_factory)

    if _DATABASE_DRIVER == 'pg8000':
        db_params = _parse_database_url(db_url)
        import pg8000
        return pg8000.connect(
            user=db_params['user'],
            password=db_params['password'],
            host=db_params['host'],
            port=db_params['port'],
            database=db_params['database'],
        )

    raise RuntimeError('No se encontró un driver de base de datos disponible (psycopg2/pg8000).')


def init_app():
    """Inicializa la aplicación creando las tablas si no existen."""
    from models import init_db
    init_db()