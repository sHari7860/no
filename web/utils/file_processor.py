import pandas as pd
import re
from datetime import datetime
from database.connection import engine
from sqlalchemy import text

def extraer_periodo(nombre_archivo):
    """Extrae el periodo del nombre del archivo Excel"""
    # Buscar los ÚLTIMOS 5 dígitos antes de .xlsx
    match = re.search(r'(\d{5})\.xlsx$', nombre_archivo)
    
    if match:
        ultimos_5 = match.group(1)  # '20261'
        año = ultimos_5[:4]  # '2026'
        semestre = ultimos_5[4]  # '1'
        return f"{año}-{semestre}"
    return "2026-1"

def procesar_excel_completo(filepath, filename):
    """Procesa un archivo Excel completo"""
    resultados = []
    
    try:
        # Leer Excel
        df = pd.read_excel(filepath, header=None, skiprows=15)
        
        if len(df.columns) < 12:
            return resultados.append(("Error", False, "Formato incorrecto"))
        
        # Asignar columnas
        df.columns = [
            "consecutivo", "documento", "nombre_estudiante",
            "codigo_programa", "programa", "estado",
            "fecha_matricula", "codigo_academico", "correo_personal",
            "correo_institucional", "categoria", "extra"
        ]
        
        # 1. Extraer y cargar periodo
        periodo = extraer_periodo(filename)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO periodos (periodo) VALUES (:p) ON CONFLICT DO NOTHING"),
                {"p": periodo}
            )
        resultados.append(("Periodo", True, f"{periodo} cargado"))
        
        # 2. Cargar estudiantes
        estudiantes_df = df[[
            "documento", "nombre_estudiante", "correo_personal",
            "correo_institucional", "categoria"
        ]].drop_duplicates(subset=["documento"])
        
        estudiantes_df['documento'] = estudiantes_df['documento'].astype(str)
        
        with engine.begin() as conn:
            for _, row in estudiantes_df.iterrows():
                conn.execute(text("""
                    INSERT INTO estudiantes_base 
                    (documento, nombre_estudiante, correo_personal, correo_institucional, categoria)
                    VALUES (:doc, :nombre, :email_per, :email_inst, :cat)
                    ON CONFLICT (documento) DO UPDATE SET
                    nombre_estudiante = EXCLUDED.nombre_estudiante,
                    correo_personal = EXCLUDED.correo_personal,
                    correo_institucional = EXCLUDED.correo_institucional,
                    categoria = EXCLUDED.categoria
                """), {
                    "doc": str(row['documento']),
                    "nombre": row['nombre_estudiante'],
                    "email_per": row['correo_personal'],
                    "email_inst": row['correo_institucional'],
                    "cat": row['categoria']
                })
        resultados.append(("Estudiantes", True, f"{len(estudiantes_df)} cargados"))
        
        # 3. Cargar programas
        programas_df = df[["codigo_programa", "programa"]].drop_duplicates().dropna()
        programas_df['codigo_programa'] = programas_df['codigo_programa'].astype(str)
        
        with engine.begin() as conn:
            for _, row in programas_df.iterrows():
                conn.execute(text("""
                    INSERT INTO programas (codigo_programa, programa)
                    VALUES (:codigo, :programa)
                    ON CONFLICT (programa) DO UPDATE SET
                    codigo_programa = EXCLUDED.codigo_programa
                """), {
                    "codigo": row['codigo_programa'],
                    "programa": row['programa']
                })
        resultados.append(("Programas", True, f"{len(programas_df)} cargados"))
        
        # 4. Cargar matrículas
        # Obtener IDs
        with engine.connect() as conn:
            estudiantes_db = pd.read_sql("SELECT id, documento FROM estudiantes_base", conn)
            programas_db = pd.read_sql("SELECT id, programa FROM programas", conn)
            periodos_db = pd.read_sql(f"SELECT id FROM periodos WHERE periodo = '{periodo}'", conn)
            
            if len(periodos_db) == 0:
                resultados.append(("Matrículas", False, f"Periodo {periodo} no encontrado"))
                return resultados
            
            periodo_id = periodos_db.iloc[0]['id']
        
        # Preparar datos
        matriculas_df = df.dropna(subset=["documento", "programa", "estado"]).copy()
        matriculas_df['documento'] = matriculas_df['documento'].astype(str)
        estudiantes_db['documento'] = estudiantes_db['documento'].astype(str)
        
        # Merge para obtener IDs
        matriculas_df = matriculas_df.merge(
            estudiantes_db, on="documento", how="left", suffixes=('', '_est')
        )
        matriculas_df = matriculas_df.merge(
            programas_db, on="programa", how="left", suffixes=('', '_prog')
        )
        
        # Filtrar completos
        matriculas_completas = matriculas_df[
            ~matriculas_df['id'].isnull() & ~matriculas_df['id_prog'].isnull()
        ].copy()
        
        # Insertar
        with engine.begin() as conn:
            for _, row in matriculas_completas.iterrows():
                conn.execute(text("""
                    INSERT INTO matriculas 
                    (estudiante_id, programa_id, periodo_id, estado, fecha_matricula, fecha_carga, archivo_origen)
                    VALUES (:est_id, :prog_id, :per_id, :estado, :fecha_mat, :fecha_carga, :archivo)
                    ON CONFLICT (estudiante_id, programa_id, periodo_id) DO UPDATE SET
                    estado = EXCLUDED.estado,
                    fecha_matricula = EXCLUDED.fecha_matricula,
                    fecha_carga = EXCLUDED.fecha_carga
                """), {
                    "est_id": int(row['id']),
                    "prog_id": int(row['id_prog']),
                    "per_id": int(periodo_id),
                    "estado": row['estado'],
                    "fecha_mat": row['fecha_matricula'],
                    "fecha_carga": datetime.now(),
                    "archivo": filename
                })
        
        resultados.append(("Matrículas", True, f"{len(matriculas_completas)} cargadas"))
        
    except Exception as e:
        resultados.append(("Error", False, f"Error general: {str(e)}"))
    
    return resultados