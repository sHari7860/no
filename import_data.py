import pandas as pd
import re
import glob
import os
from models import normalize_text, normalize_phone
from database import get_db_connection


def extract_period_from_filename(filename):
    """Extrae el código del período del nombre del archivo."""
    match = re.search(r'(\d{5})\.(xlsx|xls)$', filename)
    if match:
        return match.group(1)

    matches = re.findall(r'\d+', filename)
    if matches:
        return max(matches, key=len)

    return '00000'


def clean_dataframe(df):
    """Limpia el DataFrame eliminando filas vacías y columnas no deseadas."""
    df = df.dropna(how='all')

    for idx, row in df.iterrows():
        if isinstance(row.iloc[0], str) and 'nro' in row.iloc[0].lower():
            df.columns = [str(col).strip() for col in row.values]
            df = df.iloc[idx + 1 :].reset_index(drop=True)
            break

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
        'Novedad': 'novedad',
    }

    df = df.rename(columns={col: column_mapping.get(col, col) for col in df.columns})

    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    return df


def process_telefono(telefono_str):
    if pd.isna(telefono_str) or telefono_str == 'nan':
        return '', ''

    partes = str(telefono_str).split('/')
    principal = normalize_phone(partes[0].strip()) if len(partes) > 0 else ''
    adicional = normalize_phone(partes[1].strip()) if len(partes) > 1 else ''
    return principal, adicional


def import_excel_to_db(filepath, filename, actor=None):
    """Importa un archivo Excel a PostgreSQL."""
    conn = get_db_connection()
    cursor = conn.cursor()

    periodo_codigo = extract_period_from_filename(filename)

    cursor.execute('SELECT id FROM archivos_importados WHERE nombre_archivo = %s', (filename,))
    if cursor.fetchone():
        conn.close()
        return {'error': 'Este archivo ya fue importado anteriormente'}

    try:
        df = pd.read_excel(filepath)
    except Exception as exc:
        conn.close()
        return {'error': f'Error al leer el archivo: {str(exc)}'}

    df = clean_dataframe(df)
    if df.empty:
        conn.close()
        return {'error': 'El archivo no contiene datos válidos'}

    cursor.execute(
        'INSERT INTO periodos (codigo_periodo) VALUES (%s) ON CONFLICT (codigo_periodo) DO NOTHING',
        (periodo_codigo,),
    )
    cursor.execute('SELECT id FROM periodos WHERE codigo_periodo = %s', (periodo_codigo,))
    periodo_id = cursor.fetchone()[0]

    nuevos_estudiantes = 0
    nuevas_matriculas = 0
    programas_nuevos = 0
    registros_duplicados = 0
    estudiantes_existentes = 0
    programas_existentes = 0

    for _, row in df.iterrows():
        if pd.isna(row.get('documento')) or str(row.get('documento')).strip() == '':
            continue

        documento = str(row.get('documento', '')).strip()
        nombre_completo = str(row.get('nombre_estudiante', '')).strip()
        nombre_normalizado = normalize_text(nombre_completo)
        telefono_principal, telefono_adicional = process_telefono(row.get('telefonos', ''))

        cursor.execute(
            '''
            INSERT INTO estudiantes (
                documento, nombre_completo, nombre_normalizado, telefono_normalizado,
                telefono_adicional, correo_personal, correo_institucional
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (documento, nombre_normalizado) DO NOTHING
            ''',
            (
                documento,
                nombre_completo,
                nombre_normalizado,
                telefono_principal,
                telefono_adicional,
                str(row.get('correo_electronico', '')).strip(),
                str(row.get('correo_institucional', '')).strip(),
            ),
        )
        if cursor.rowcount > 0:
            nuevos_estudiantes += 1
        else:
            estudiantes_existentes += 1

        cursor.execute(
            'SELECT id FROM estudiantes WHERE documento = %s AND nombre_normalizado = %s',
            (documento, nombre_normalizado),
        )
        estudiante_id = cursor.fetchone()[0]

        programa_nombre = str(row.get('programa', '')).strip()
        programa_normalizado = normalize_text(programa_nombre)

        tipo_programa = 'PREGRADO'
        if 'especializacion' in programa_normalizado:
            tipo_programa = 'ESPECIALIZACION'
        elif 'diplomado' in programa_normalizado:
            tipo_programa = 'DIPLOMADO'
        elif 'curso' in programa_normalizado:
            tipo_programa = 'CURSO'

        cursor.execute(
            '''
            INSERT INTO programas (nombre_normalizado, nombre_original, tipo_programa)
            VALUES (%s, %s, %s)
            ON CONFLICT (nombre_normalizado) DO NOTHING
            ''',
            (programa_normalizado, programa_nombre, tipo_programa),
        )
        if cursor.rowcount > 0:
            programas_nuevos += 1
        else:
            programas_existentes += 1

        cursor.execute('SELECT id FROM programas WHERE nombre_normalizado = %s', (programa_normalizado,))
        programa_id = cursor.fetchone()[0]

        categoria_nombre = str(row.get('categoria', 'ANTIGUO')).strip().upper()
        cursor.execute('SELECT id FROM categorias WHERE nombre = %s', (categoria_nombre,))
        categoria_result = cursor.fetchone()
        categoria_id = categoria_result[0] if categoria_result else 2

        estado_nombre = str(row.get('estado_matricula', 'Por confirmar')).strip()
        cursor.execute('SELECT id FROM estados_matricula WHERE nombre = %s', (estado_nombre,))
        estado_result = cursor.fetchone()
        estado_matricula_id = estado_result[0] if estado_result else 2

        cursor.execute(
            '''
            INSERT INTO matriculas (
                periodo_id, estudiante_id, programa_id, liquidacion_numero,
                categoria_id, estado_matricula_id, fecha_inscripcion, novedad, archivo_origen
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (periodo_id, estudiante_id, programa_id) DO NOTHING
            ''',
            (
                periodo_id,
                estudiante_id,
                programa_id,
                str(row.get('liquidacion_numero', '')).strip(),
                categoria_id,
                estado_matricula_id,
                str(row.get('fecha_inscripcion', '')).strip(),
                str(row.get('novedad', '')).strip(),
                filename,
            ),
        )
        if cursor.rowcount > 0:
            nuevas_matriculas += 1
        else:
            registros_duplicados += 1

    cursor.execute(
        '''
        INSERT INTO archivos_importados (nombre_archivo, periodo_id, total_registros, nuevos_registros)
        VALUES (%s, %s, %s, %s)
        ''',
        (filename, periodo_id, len(df), nuevas_matriculas),
    )

    if actor:
        cursor.execute(
            '''
            INSERT INTO auditoria (username, accion, detalle)
            VALUES (%s, %s, %s)
            ''',
            (
                actor,
                'IMPORT_EXCEL',
                f'Archivo={filename}, periodo={periodo_codigo}, nuevas_matriculas={nuevas_matriculas}',
            ),
        )

    conn.commit()
    conn.close()

    # Borrar archivos Excel previos (mantener solo el último importado)
    try:
        for ext in ['*.xlsx', '*.xls']:
            for archivo in glob.glob(os.path.join(os.path.dirname(filepath), ext)):
                # No borrar el archivo actual
                if archivo != filepath:
                    try:
                        os.remove(archivo)
                    except Exception as e:
                        print(f'Advertencia: No se pudo borrar {archivo}: {str(e)}')
    except Exception as e:
        print(f'Advertencia: Error al limpiar archivos previos: {str(e)}')

    return {
        'success': True,
        'total_registros': len(df),
        'nuevos_estudiantes': nuevos_estudiantes,
        'estudiantes_existentes': estudiantes_existentes,
        'nuevas_matriculas': nuevas_matriculas,
        'registros_duplicados': registros_duplicados,
        'programas_nuevos': programas_nuevos,
        'programas_existentes': programas_existentes,
        'periodo': periodo_codigo,
    }
