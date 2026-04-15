import os
import unicodedata
import re
from werkzeug.security import generate_password_hash
import psycopg2


def normalize_text(text):
    """Normaliza texto: elimina tildes, convierte a minúsculas y limpia espacios."""
    if text is None:
        return ""

    text = str(text)
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def normalize_phone(phone):
    """Normaliza números de teléfono."""
    if phone is None:
        return ""

    phone = str(phone)
    phone = ''.join(filter(str.isdigit, phone))

    if phone.startswith('57') and len(phone) > 10:
        phone = phone[2:]

    return phone[:15]


def init_db():
    """Inicializa PostgreSQL creando tablas, constraints y datos base."""
    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/UNITEC")
    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS periodos (
        id SERIAL PRIMARY KEY,
        codigo_periodo VARCHAR(20) UNIQUE NOT NULL,
        nombre VARCHAR(120),
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS programas (
        id SERIAL PRIMARY KEY,
        nombre_normalizado TEXT UNIQUE NOT NULL,
        nombre_original TEXT,
        tipo_programa VARCHAR(40),
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estudiantes (
        id SERIAL PRIMARY KEY,
        documento VARCHAR(50) NOT NULL,
        nombre_completo TEXT NOT NULL,
        nombre_normalizado TEXT NOT NULL,
        telefono_normalizado VARCHAR(20),
        telefono_adicional VARCHAR(20),
        correo_personal TEXT,
        correo_institucional TEXT,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (documento, nombre_normalizado)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS categorias (
        id SERIAL PRIMARY KEY,
        nombre VARCHAR(50) UNIQUE NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estados_matricula (
        id SERIAL PRIMARY KEY,
        nombre VARCHAR(50) UNIQUE NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matriculas (
        id SERIAL PRIMARY KEY,
        periodo_id INTEGER NOT NULL REFERENCES periodos(id),
        estudiante_id INTEGER NOT NULL REFERENCES estudiantes(id),
        programa_id INTEGER NOT NULL REFERENCES programas(id),
        liquidacion_numero TEXT,
        categoria_id INTEGER NOT NULL REFERENCES categorias(id),
        estado_matricula_id INTEGER NOT NULL REFERENCES estados_matricula(id),
        fecha_inscripcion TEXT,
        novedad TEXT,
        fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        archivo_origen TEXT,
        UNIQUE (periodo_id, estudiante_id, programa_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS archivos_importados (
        id SERIAL PRIMARY KEY,
        nombre_archivo TEXT UNIQUE NOT NULL,
        periodo_id INTEGER REFERENCES periodos(id),
        fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_registros INTEGER,
        nuevos_registros INTEGER,
        registros_actualizados INTEGER
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS usuarios (
        id SERIAL PRIMARY KEY,
        username VARCHAR(60) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        nombre_completo TEXT NOT NULL,
        rol VARCHAR(30) NOT NULL DEFAULT 'operador',
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS password_reset_tokens (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        token VARCHAR(255) UNIQUE NOT NULL,
        fecha_expiracion TIMESTAMP NOT NULL,
        utilizado BOOLEAN NOT NULL DEFAULT FALSE,
        fecha_uso TIMESTAMP,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS auditoria (
        id SERIAL PRIMARY KEY,
        usuario_id INTEGER REFERENCES usuarios(id),
        username VARCHAR(60),
        accion VARCHAR(100) NOT NULL,
        detalle TEXT,
        ip_origen VARCHAR(45),
        fecha_evento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    for categoria in ['NUEVO', 'ANTIGUO', 'REINTEGRO']:
        cursor.execute(
            'INSERT INTO categorias (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING',
            (categoria,),
        )

    for estado in ['Confirmado', 'Por confirmar', 'Cancelado']:
        cursor.execute(
            'INSERT INTO estados_matricula (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING',
            (estado,),
        )

    default_user = os.getenv('APP_ADMIN_USER', 'admin')
    default_password = os.getenv('APP_ADMIN_PASSWORD', 'admin123')
    default_name = os.getenv('APP_ADMIN_NAME', 'Administrador')

    cursor.execute(
        '''
        INSERT INTO usuarios (username, password_hash, nombre_completo, rol)
        VALUES (%s, %s, %s, 'admin')
        ON CONFLICT (username) DO NOTHING
        ''',
        (default_user, generate_password_hash(default_password), default_name),
    )

    conn.commit()
    conn.close()
