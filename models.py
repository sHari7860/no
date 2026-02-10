import sqlite3
import unicodedata
import re

def normalize_text(text):
    """Normaliza texto: elimina tildes, convierte a minúsculas y limpia espacios"""
    if text is None:
        return ""
    
    # Convertir a string si no lo es
    text = str(text)
    
    # Eliminar tildes
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    
    # Convertir a minúsculas y eliminar espacios extra
    text = text.lower().strip()
    
    # Reemplazar múltiples espacios por uno solo
    text = re.sub(r'\s+', ' ', text)
    
    return text

def normalize_phone(phone):
    """Normaliza números de teléfono"""
    if phone is None:
        return ""
    
    phone = str(phone)
    # Mantener solo dígitos
    phone = ''.join(filter(str.isdigit, phone))
    
    # Para Colombia, verificar si tiene código de país
    if phone.startswith('57') and len(phone) > 10:
        phone = phone[2:]  # Quitar código de país
    
    return phone[:15]  # Limitar longitud

def init_db():
    """Inicializa la base de datos creando todas las tablas"""
    conn = sqlite3.connect('matriculas.db')
    cursor = conn.cursor()
    
    # Tabla de períodos académicos
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS periodos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo_periodo TEXT UNIQUE NOT NULL,
        nombre TEXT,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabla de programas académicos (normalizados)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS programas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre_normalizado TEXT UNIQUE NOT NULL,
        nombre_original TEXT,
        tipo_programa TEXT,  -- PREGRADO, ESPECIALIZACION, DIPLOMADO, etc.
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Tabla de estudiantes (información básica)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estudiantes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        documento TEXT UNIQUE NOT NULL,
        nombre_completo TEXT NOT NULL,
        nombre_normalizado TEXT NOT NULL,
        telefono_normalizado TEXT,
        telefono_adicional TEXT,
        correo_personal TEXT,
        correo_institucional TEXT,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(documento)
    )
    ''')
    
    # Tabla de categorías de estudiante
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS categorias (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL
    )
    ''')
    
    # Tabla de estados de matrícula
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS estados_matricula (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL
    )
    ''')
    
    # Tabla principal de matrículas
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matriculas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        periodo_id INTEGER NOT NULL,
        estudiante_id INTEGER NOT NULL,
        programa_id INTEGER NOT NULL,
        liquidacion_numero TEXT NOT NULL,
        categoria_id INTEGER NOT NULL,
        estado_matricula_id INTEGER NOT NULL,
        fecha_inscripcion TEXT,
        novedad TEXT,
        fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        archivo_origen TEXT,
        FOREIGN KEY (periodo_id) REFERENCES periodos (id),
        FOREIGN KEY (estudiante_id) REFERENCES estudiantes (id),
        FOREIGN KEY (programa_id) REFERENCES programas (id),
        FOREIGN KEY (categoria_id) REFERENCES categorias (id),
        FOREIGN KEY (estado_matricula_id) REFERENCES estados_matricula (id),
        UNIQUE(periodo_id, estudiante_id, programa_id, liquidacion_numero)
    )
    ''')
    
    # Tabla para registrar archivos importados
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS archivos_importados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre_archivo TEXT UNIQUE NOT NULL,
        periodo_id INTEGER,
        fecha_importacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        total_registros INTEGER,
        nuevos_registros INTEGER,
        registros_actualizados INTEGER,
        FOREIGN KEY (periodo_id) REFERENCES periodos (id)
    )
    ''')
    
    # Insertar categorías predefinidas
    categorias = ['NUEVO', 'ANTIGUO', 'REINTEGRO']
    for categoria in categorias:
        cursor.execute('INSERT OR IGNORE INTO categorias (nombre) VALUES (?)', (categoria,))
    
    # Insertar estados predefinidos
    estados = ['Confirmado', 'Por confirmar', 'Cancelado']
    for estado in estados:
        cursor.execute('INSERT OR IGNORE INTO estados_matricula (nombre) VALUES (?)', (estado,))
    
    conn.commit()
    conn.close()