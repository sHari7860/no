# init_db_corrected.py
from sqlalchemy import create_engine, text

engine = create_engine(
    "postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC"
)

with engine.connect() as conn:
    # 1. TABLA estudiantes_base (CON ID)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS estudiantes_base (
            id SERIAL PRIMARY KEY,
            documento VARCHAR(50) UNIQUE NOT NULL,
            nombre_estudiante TEXT,
            correo_personal TEXT,
            correo_institucional TEXT,
            categoria TEXT,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # 2. TABLA programas (FALTANTE)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS programas (
            id SERIAL PRIMARY KEY,
            codigo_programa VARCHAR(20),
            programa TEXT UNIQUE NOT NULL,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # 3. TABLA periodos (CORRECTA)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS periodos (
            id SERIAL PRIMARY KEY,
            periodo TEXT UNIQUE NOT NULL,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # 4. TABLA matriculas (ACTUALIZADA)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS matriculas (
            id SERIAL PRIMARY KEY,
            estudiante_id INTEGER REFERENCES estudiantes_base(id),
            programa_id INTEGER REFERENCES programas(id),
            periodo_id INTEGER REFERENCES periodos(id),
            estado TEXT,
            fecha_matricula TEXT,
            fecha_carga TIMESTAMP,
            archivo_origen TEXT,
            UNIQUE(estudiante_id, programa_id, periodo_id)
        )
    """))
    
    conn.commit()
    print("Estructura de base de datos creada")