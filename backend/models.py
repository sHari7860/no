# -*- coding: utf-8 -*-
import os
import unicodedata
import re
from werkzeug.security import generate_password_hash


def normalize_text(text):
    """Normaliza texto: elimina tildes, convierte a minusculas y limpia espacios."""
    if text is None:
        return ""
    text = str(text)
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def normalize_phone(phone):
    """Normaliza numeros de telefono."""
    if phone is None:
        return ""
    phone = str(phone)
    phone = ''.join(filter(str.isdigit, phone))
    if phone.startswith('57') and len(phone) > 10:
        phone = phone[2:]
    return phone[:15]


def _translate_query(sql, is_sqlite):
    return sql.replace('%s', '?') if is_sqlite and sql else sql


def _execute(cursor, sql, params=None, is_sqlite=False):
    return cursor.execute(_translate_query(sql, is_sqlite), params or ())


def _executemany(cursor, sql, seq_of_params, is_sqlite=False):
    return cursor.executemany(_translate_query(sql, is_sqlite), seq_of_params)


def init_db():
    """Inicializa la base de datos creando tablas, constraints y datos base."""
    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/UNITEC1")
    is_sqlite = database_url.startswith('sqlite:')

    if is_sqlite:
        import sqlite3
        db_path = database_url.split(':///')[-1]
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute('PRAGMA foreign_keys = ON')
    else:
        import psycopg2
        conn = psycopg2.connect(database_url)

    cursor = conn.cursor()
    primary_key_type = 'INTEGER PRIMARY KEY AUTOINCREMENT' if is_sqlite else 'SERIAL PRIMARY KEY'

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS periodos (
        id {primary_key_type},
        codigo_periodo VARCHAR(20) UNIQUE NOT NULL,
        nombre VARCHAR(120),
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS programas (
        id {primary_key_type},
        nombre_normalizado TEXT UNIQUE NOT NULL,
        nombre_original TEXT,
        tipo_programa VARCHAR(40),
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS estudiantes (
        id {primary_key_type},
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

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS categorias (
        id {primary_key_type},
        nombre VARCHAR(50) UNIQUE NOT NULL
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS estados_matricula (
        id {primary_key_type},
        nombre VARCHAR(50) UNIQUE NOT NULL
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS matriculas (
        id {primary_key_type},
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

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS archivos_importados (
        id {primary_key_type},
        nombre_archivo TEXT UNIQUE NOT NULL,
        periodo_id INTEGER REFERENCES periodos(id),
        fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_registros INTEGER,
        nuevos_registros INTEGER,
        registros_actualizados INTEGER
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS usuarios (
        id {primary_key_type},
        username VARCHAR(60) UNIQUE NOT NULL,
        email VARCHAR(120) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        nombre_completo TEXT NOT NULL,
        rol VARCHAR(30) NOT NULL DEFAULT 'operador' CHECK (rol IN ('admin', 'operador')),
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        requiere_cambio_password BOOLEAN NOT NULL DEFAULT FALSE,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS email VARCHAR(120) UNIQUE")
    cursor.execute("UPDATE usuarios SET email = username || '@unitec.edu.co' WHERE email IS NULL")
    if not is_sqlite:
        cursor.execute("ALTER TABLE usuarios ALTER COLUMN email SET NOT NULL")
    try:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS requiere_cambio_password BOOLEAN NOT NULL DEFAULT FALSE")
    except Exception:
        pass
    try:
        cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS security_questions_configured BOOLEAN NOT NULL DEFAULT FALSE")
    except Exception:
        pass

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS security_questions (
        id {primary_key_type},
        pregunta TEXT UNIQUE NOT NULL,
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        orden INTEGER NOT NULL DEFAULT 0,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS user_security_answers (
        id {primary_key_type},
        user_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        question_id INTEGER NOT NULL REFERENCES security_questions(id) ON DELETE RESTRICT,
        answer_hash TEXT NOT NULL,
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, question_id)
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS password_recovery_attempts (
        id {primary_key_type},
        user_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        ip_origen VARCHAR(45),
        user_agent TEXT,
        exitoso BOOLEAN NOT NULL DEFAULT FALSE,
        fecha_intento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS password_recovery_locks (
        id {primary_key_type},
        user_id INTEGER UNIQUE NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        locked_until TIMESTAMP NOT NULL,
        motivo TEXT,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_security_questions_activo_orden ON security_questions(activo, orden, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_security_answers_user ON user_security_answers(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recovery_attempts_user_date ON password_recovery_attempts(user_id, fecha_intento DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recovery_attempts_ip_date ON password_recovery_attempts(ip_origen, fecha_intento DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_recovery_locks_user_until ON password_recovery_locks(user_id, locked_until)")

    security_questions = [
        ('Cual fue el nombre de un profesor que recuerdas especialmente?', 10),
        ('Cual era el apodo de tu mejor amigo o amiga de la infancia?', 20),
        ('Cual fue el nombre de tu primera mascota o de una mascota que recuerdas?', 30),
        ('En que ciudad o barrio viviste cuando tenias 10 anos?', 40),
        ('Cual fue el primer concierto, evento o partido al que asististe?', 50),
        ('Cual era el nombre de un libro, pelicula o serie favorita de tu adolescencia?', 60),
        ('Cual fue el primer lugar al que viajaste fuera de tu ciudad?', 70),
        ('Cual era el nombre de tu primer jefe, mentor o entrenador?', 80),
    ]
    for pregunta, orden in security_questions:
        _execute(
            cursor,
            '''
            INSERT INTO security_questions (pregunta, orden)
            VALUES (%s, %s)
            ON CONFLICT (pregunta) DO UPDATE SET activo = TRUE, orden = EXCLUDED.orden
            ''',
            (pregunta, orden),
            is_sqlite=is_sqlite,
        )

    cursor.execute('''
    UPDATE usuarios u
    SET security_questions_configured = TRUE
    WHERE EXISTS (
        SELECT 1 FROM user_security_answers usa
        WHERE usa.user_id = u.id AND usa.activo = TRUE
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS password_recovery_codes (
        id {primary_key_type},
        email VARCHAR(120) NOT NULL,
        codigo VARCHAR(6) NOT NULL,
        fecha_expiracion TIMESTAMP NOT NULL,
        utilizado BOOLEAN NOT NULL DEFAULT FALSE,
        fecha_uso TIMESTAMP,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute(f'''
    CREATE TABLE IF NOT EXISTS auditoria (
        id {primary_key_type},
        usuario_id INTEGER REFERENCES usuarios(id),
        username VARCHAR(60),
        accion VARCHAR(100) NOT NULL,
        detalle TEXT,
        ip_origen VARCHAR(45),
        fecha_evento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    for categoria in ['NUEVO', 'ANTIGUO', 'REINTEGRO']:
        _execute(
            cursor,
            'INSERT INTO categorias (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING',
            (categoria,),
            is_sqlite=is_sqlite,
        )

    for estado in ['Confirmado', 'Por confirmar', 'Cancelado']:
        _execute(
            cursor,
            'INSERT INTO estados_matricula (nombre) VALUES (%s) ON CONFLICT (nombre) DO NOTHING',
            (estado,),
            is_sqlite=is_sqlite,
        )

    default_user = os.getenv('APP_ADMIN_USER', 'admin')
    default_password = os.getenv('APP_ADMIN_PASSWORD', 'admin123')
    default_name = os.getenv('APP_ADMIN_NAME', 'Administrador')
    default_email = os.getenv('APP_ADMIN_EMAIL', 'admin@unitec.edu.co')

    _execute(
        cursor,
        '''
        INSERT INTO usuarios (username, email, password_hash, nombre_completo, rol)
        VALUES (%s, %s, %s, %s, 'admin')
        ON CONFLICT (username) DO NOTHING
        ''',
        (default_user, default_email, generate_password_hash(default_password), default_name),
        is_sqlite=is_sqlite,
    )

    conn.commit()
    conn.close()