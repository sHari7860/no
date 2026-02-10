import sqlite3
import os
from models import init_db

def get_db_connection():
    """Establece conexión con la base de datos SQLite"""
    conn = sqlite3.connect('matriculas.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_app():
    """Inicializa la aplicación creando las tablas si no existen"""
    if not os.path.exists('matriculas.db'):
        init_db()
        print("Base de datos creada exitosamente")