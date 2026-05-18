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
    cursor.execute("ALTER TABLE usuarios ALTER COLUMN email SET NOT NULL")
    cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS requiere_cambio_password BOOLEAN NOT NULL DEFAULT FALSE")
    cursor.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS security_questions_configured BOOLEAN NOT NULL DEFAULT FALSE")

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS security_questions (
        id SERIAL PRIMARY KEY,
        pregunta TEXT UNIQUE NOT NULL,
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        orden INTEGER NOT NULL DEFAULT 0,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_security_answers (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
        question_id INTEGER NOT NULL REFERENCES security_questions(id) ON DELETE RESTRICT,
        answer_hash TEXT NOT NULL,
        activo BOOLEAN NOT NULL DEFAULT TRUE,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (user_id, question_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS password_recovery_attempts (
        id SERIAL PRIMARY KEY,
        user_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
        ip_origen VARCHAR(45),
        user_agent TEXT,
        exitoso BOOLEAN NOT NULL DEFAULT FALSE,
        fecha_intento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS password_recovery_locks (
        id SERIAL PRIMARY KEY,
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
        ('¿Cuál fue el nombre de un profesor que recuerdas especialmente?', 10),
        ('¿Cuál era el apodo de tu mejor amigo o amiga de la infancia?', 20),
        ('¿Cuál fue el nombre de tu primera mascota o de una mascota que recuerdas?', 30),
        ('¿En qué ciudad o barrio viviste cuando tenías 10 años?', 40),
        ('¿Cuál fue el primer concierto, evento o partido al que asististe?', 50),
        ('¿Cuál era el nombre de un libro, película o serie favorita de tu adolescencia?', 60),
        ('¿Cuál fue el primer lugar al que viajaste fuera de tu ciudad?', 70),
        ('¿Cuál era el nombre de tu primer jefe, mentor o entrenador?', 80),
    ]
    for pregunta, orden in security_questions:
        cursor.execute(
            '''
            INSERT INTO security_questions (pregunta, orden)
            VALUES (%s, %s)
            ON CONFLICT (pregunta) DO UPDATE SET activo = TRUE, orden = EXCLUDED.orden
            ''',
            (pregunta, orden),
        )

    cursor.execute('''
    UPDATE usuarios u
    SET security_questions_configured = TRUE
    WHERE EXISTS (
        SELECT 1 FROM user_security_answers usa
        WHERE usa.user_id = u.id AND usa.activo = TRUE
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS password_recovery_codes (
        id SERIAL PRIMARY KEY,
        email VARCHAR(120) NOT NULL,
        codigo VARCHAR(6) NOT NULL,
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
    default_email = os.getenv('APP_ADMIN_EMAIL', 'admin@unitec.edu.co')

    cursor.execute(
        '''
        INSERT INTO usuarios (username, email, password_hash, nombre_completo, rol)
        VALUES (%s, %s, %s, %s, 'admin')
        ON CONFLICT (username) DO NOTHING
        ''',
        (default_user, default_email, generate_password_hash(default_password), default_name),
    )

    conn.commit()
    conn.close()
