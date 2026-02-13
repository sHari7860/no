import os
import psycopg2
from psycopg2.extras import RealDictCursor
from models import init_db


def get_database_url():
    return os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/UNITEC")


def get_db_connection(dict_cursor: bool = False):
    """Establece conexión con PostgreSQL."""
    cursor_factory = RealDictCursor if dict_cursor else None
    return psycopg2.connect(get_database_url(), cursor_factory=cursor_factory)


def init_app():
    """Inicializa la aplicación creando las tablas si no existen."""
    init_db()
