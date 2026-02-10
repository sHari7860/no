import pandas as pd
import sqlite3
import os
import re
from datetime import datetime
from models import normalize_text, normalize_phone

def extract_period_from_filename(filename):
    """Extrae el código del período del nombre del archivo"""
    # Buscar 5 dígitos al final del nombre (antes de la extensión)
    match = re.search(r'(\d{5})\.(xlsx|xls)$', filename)
    if match:
        return match.group(1)
    
    # Alternativa: buscar cualquier secuencia de dígitos
    matches = re.findall(r'\d+', filename)
    if matches:
        # Tomar la secuencia más larga (probablemente el período)
        return max(matches, key=len)
    
    return "00000"

def clean_dataframe(df):
    """Limpia el DataFrame eliminando filas vacías y columnas no deseadas"""
    # Eliminar filas completamente vacías
    df = df.dropna(how='all')
    
    # Buscar la fila que contiene "Nro." para encontrar el encabezado
    for idx, row in df.iterrows():
        if isinstance(row.iloc[0], str) and 'nro' in row.iloc[0].lower():
            # Esta fila es el encabezado
            df.columns = [str(col).strip() for col in row.values]
            df = df.iloc[idx+1:].reset_index(drop=True)
            break
    
    # Renombrar columnas para consistencia
    column_mapping = {
        'Nro.': 'numero',
        'Documento': 'documento',
        'Nombre Estudiante': 'nombre_estudiante',
        'Liquidación Nro.': 'liquidacion_numero',
        'Programa': 'programa',
        'Estado Matricula': 'estado_matricula',
        'Fecha Inscripción': 'fecha_inscripcion',
        'Teléfonos': 'telefonos',
        'Correo Electrónico': 'correo_electronico',
        'Correo Institucional': 'correo_institucional',
        'Categoria': 'categoria',
        'Novedad': 'novedad'
    }
    
    df = df.rename(columns={col: column_mapping.get(col, col) for col in df.columns})
    
    # Convertir todos los valores a string y limpiar
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    
    return df

def process_telefono(telefono_str):
    """Procesa la columna de teléfonos separando en principal y adicional"""
    if pd.isna(telefono_str) or telefono_str == 'nan':
        return "", ""
    
    telefono_str = str(telefono_str)
    
    # Separar por /
    partes = telefono_str.split('/')
    
    principal = normalize_phone(partes[0].strip()) if len(partes) > 0 else ""
    adicional = normalize_phone(partes[1].strip()) if len(partes) > 1 else ""
    
    return principal, adicional

def import_excel_to_db(filepath, filename):
    """Importa un archivo Excel a la base de datos"""
    conn = sqlite3.connect('matriculas.db')
    cursor = conn.cursor()
    
    # Extraer período del nombre del archivo
    periodo_codigo = extract_period_from_filename(filename)
    
    # Verificar si el archivo ya fue importado
    cursor.execute('SELECT id FROM archivos_importados WHERE nombre_archivo = ?', (filename,))
    if cursor.fetchone():
        conn.close()
        return {"error": "Este archivo ya fue importado anteriormente"}
    
    # Leer el archivo Excel
    try:
        df = pd.read_excel(filepath)
    except Exception as e:
        conn.close()
        return {"error": f"Error al leer el archivo: {str(e)}"}
    
    # Limpiar los datos
    df = clean_dataframe(df)
    
    if df.empty:
        conn.close()
        return {"error": "El archivo no contiene datos válidos"}
    
    # Registrar el período
    cursor.execute('INSERT OR IGNORE INTO periodos (codigo_periodo) VALUES (?)', (periodo_codigo,))
    cursor.execute('SELECT id FROM periodos WHERE codigo_periodo = ?', (periodo_codigo,))
    periodo_id = cursor.fetchone()[0]
    
    # Contadores
    nuevos_estudiantes = 0
    nuevas_matriculas = 0
    programas_nuevos = 0
    
    # Procesar cada registro
    for _, row in df.iterrows():
        # Saltar filas vacías
        if pd.isna(row.get('documento')) or str(row.get('documento')).strip() == '':
            continue
        
        # Normalizar datos
        documento = str(row.get('documento', '')).strip()
        nombre_completo = str(row.get('nombre_estudiante', '')).strip()
        nombre_normalizado = normalize_text(nombre_completo)
        
        # Procesar teléfonos
        telefono_principal, telefono_adicional = process_telefono(row.get('telefonos', ''))
        
        # Insertar o actualizar estudiante
        cursor.execute('''
            INSERT OR IGNORE INTO estudiantes 
            (documento, nombre_completo, nombre_normalizado, telefono_normalizado, 
             telefono_adicional, correo_personal, correo_institucional)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            documento,
            nombre_completo,
            nombre_normalizado,
            telefono_principal,
            telefono_adicional,
            str(row.get('correo_electronico', '')).strip(),
            str(row.get('correo_institucional', '')).strip()
        ))
        
        if cursor.rowcount > 0:
            nuevos_estudiantes += 1
        
        cursor.execute('SELECT id FROM estudiantes WHERE documento = ?', (documento,))
        estudiante_id = cursor.fetchone()[0]
        
        # Insertar o actualizar programa
        programa_nombre = str(row.get('programa', '')).strip()
        programa_normalizado = normalize_text(programa_nombre)
        
        # Determinar tipo de programa
        tipo_programa = "PREGRADO"
        if 'especializacion' in programa_normalizado or 'especialización' in programa_normalizado.lower():
            tipo_programa = "ESPECIALIZACION"
        elif 'diplomado' in programa_normalizado:
            tipo_programa = "DIPLOMADO"
        elif 'curso' in programa_normalizado:
            tipo_programa = "CURSO"
        
        cursor.execute('''
            INSERT OR IGNORE INTO programas 
            (nombre_normalizado, nombre_original, tipo_programa)
            VALUES (?, ?, ?)
        ''', (programa_normalizado, programa_nombre, tipo_programa))
        
        if cursor.rowcount > 0:
            programas_nuevos += 1
        
        cursor.execute('SELECT id FROM programas WHERE nombre_normalizado = ?', (programa_normalizado,))
        programa_id = cursor.fetchone()[0]
        
        # Obtener IDs de categoría y estado
        categoria_nombre = str(row.get('categoria', 'ANTIGUO')).strip().upper()
        cursor.execute('SELECT id FROM categorias WHERE nombre = ?', (categoria_nombre,))
        categoria_result = cursor.fetchone()
        categoria_id = categoria_result[0] if categoria_result else 2  # Default: ANTIGUO
        
        estado_nombre = str(row.get('estado_matricula', 'Por confirmar')).strip()
        cursor.execute('SELECT id FROM estados_matricula WHERE nombre = ?', (estado_nombre,))
        estado_result = cursor.fetchone()
        estado_matricula_id = estado_result[0] if estado_result else 2  # Default: Por confirmar
        
        # Insertar matrícula (evitar duplicados)
        cursor.execute('''
            INSERT OR IGNORE INTO matriculas 
            (periodo_id, estudiante_id, programa_id, liquidacion_numero, 
             categoria_id, estado_matricula_id, fecha_inscripcion, novedad, archivo_origen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            periodo_id,
            estudiante_id,
            programa_id,
            str(row.get('liquidacion_numero', '')).strip(),
            categoria_id,
            estado_matricula_id,
            str(row.get('fecha_inscripcion', '')).strip(),
            str(row.get('novedad', '')).strip(),
            filename
        ))
        
        if cursor.rowcount > 0:
            nuevas_matriculas += 1
    
    # Registrar el archivo importado
    cursor.execute('''
        INSERT INTO archivos_importados 
        (nombre_archivo, periodo_id, total_registros, nuevos_registros)
        VALUES (?, ?, ?, ?)
    ''', (filename, periodo_id, len(df), nuevas_matriculas))
    
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "total_registros": len(df),
        "nuevos_estudiantes": nuevos_estudiantes,
        "nuevas_matriculas": nuevas_matriculas,
        "programas_nuevos": programas_nuevos,
        "periodo": periodo_codigo
    }