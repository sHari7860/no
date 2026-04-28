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
        'Nombre Completo': 'nombre_estudiante',
        'Liquidación Nro.': 'liquidacion_numero',
        'Formulario Nro.': 'formulario_numero',
        'Programa': 'programa',
        'Estado Matricula': 'estado_matricula',
        'Estado': 'estado',
        'Estado Inscripciones': 'estado_inscripciones',
        'Fecha Inscripción': 'fecha_inscripcion',
        'Teléfonos': 'telefonos',
        'Correo Electrónico': 'correo_electronico',
        'Correo Institucional': 'correo_institucional',
        'Jornada': 'jornada',
        'Usuario CRM': 'usuario_crm',
        'Categoria': 'categoria',
        'Novedad': 'novedad',
        'Observaciones': 'observaciones',
        'Observación': 'observaciones',
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


def detect_file_type(df):
    """Detecta si el archivo corresponde a matrículas o CRM de inscripciones."""
    cols = set(df.columns)
    if {'liquidacion_numero', 'estado_matricula', 'categoria'}.intersection(cols):
        return 'MATRICULAS'
    if {'formulario_numero', 'estado', 'estado_inscripciones', 'usuario_crm', 'jornada'}.intersection(cols):
        return 'CRM_INSCRIPCIONES'
    return 'MATRICULAS'


def upsert_student_and_program(cursor, row):
    documento = str(row.get('documento', '')).strip()
    nombre_completo = str(row.get('nombre_estudiante', '')).strip()
    nombre_normalizado = normalize_text(nombre_completo)
    telefono_principal, telefono_adicional = process_telefono(row.get('telefonos', ''))

    cursor.execute(
        'SELECT id FROM estudiantes WHERE documento = %s AND nombre_normalizado = %s',
        (documento, nombre_normalizado),
    )
    estudiante_existia = cursor.fetchone() is not None

    cursor.execute(
        '''
        INSERT INTO estudiantes (
            documento, nombre_completo, nombre_normalizado, telefono_normalizado,
            telefono_adicional, correo_personal, correo_institucional
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (documento, nombre_normalizado) DO UPDATE SET
            telefono_normalizado = COALESCE(NULLIF(EXCLUDED.telefono_normalizado, ''), estudiantes.telefono_normalizado),
            telefono_adicional = COALESCE(NULLIF(EXCLUDED.telefono_adicional, ''), estudiantes.telefono_adicional),
            correo_personal = COALESCE(NULLIF(EXCLUDED.correo_personal, ''), estudiantes.correo_personal),
            correo_institucional = COALESCE(NULLIF(EXCLUDED.correo_institucional, ''), estudiantes.correo_institucional)
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
    estudiante_creado = not estudiante_existia
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

    cursor.execute('SELECT id FROM programas WHERE nombre_normalizado = %s', (programa_normalizado,))
    programa_existia = cursor.fetchone() is not None

    cursor.execute(
        '''
        INSERT INTO programas (nombre_normalizado, nombre_original, tipo_programa)
        VALUES (%s, %s, %s)
        ON CONFLICT (nombre_normalizado) DO NOTHING
        ''',
        (programa_normalizado, programa_nombre, tipo_programa),
    )
    programa_creado = not programa_existia
    cursor.execute('SELECT id FROM programas WHERE nombre_normalizado = %s', (programa_normalizado,))
    programa_id = cursor.fetchone()[0]
    return estudiante_id, programa_id, programa_normalizado, estudiante_creado, programa_creado


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
    tipo_archivo = detect_file_type(df)

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
    warnings = []
    documentos_programas = {}

    for _, row in df.iterrows():
        if pd.isna(row.get('documento')) or str(row.get('documento')).strip() == '':
            continue

        documento = str(row.get('documento', '')).strip()
        estudiante_id, programa_id, programa_normalizado, estudiante_creado, programa_creado = upsert_student_and_program(cursor, row)
        if estudiante_creado:
            nuevos_estudiantes += 1
        else:
            estudiantes_existentes += 1
        if programa_creado:
            programas_nuevos += 1
        else:
            programas_existentes += 1

        # Detectar casos en que el mismo CC aparece en más de un programa dentro de un mismo archivo.
        if documento:
            programas_previos = documentos_programas.get(documento, set())
            if programa_normalizado and programa_normalizado not in programas_previos and programas_previos:
                warnings.append(
                    f'El documento {documento} aparece en varios programas académicos ({", ".join(sorted(programas_previos))}). Verifica que CC y programa coincidan.'
                )
            programas_previos.add(programa_normalizado)
            documentos_programas[documento] = programas_previos

        if tipo_archivo == 'CRM_INSCRIPCIONES':
            cursor.execute(
                '''
                INSERT INTO inscripciones_crm (
                    periodo_id, estudiante_id, programa_id, formulario_numero, estado,
                    estado_inscripciones, jornada, fecha_inscripcion, usuario_crm, archivo_origen
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (periodo_id, estudiante_id, programa_id, formulario_numero_norm) DO UPDATE SET
                    estado = EXCLUDED.estado,
                    estado_inscripciones = EXCLUDED.estado_inscripciones,
                    jornada = EXCLUDED.jornada,
                    fecha_inscripcion = EXCLUDED.fecha_inscripcion,
                    usuario_crm = EXCLUDED.usuario_crm,
                    archivo_origen = EXCLUDED.archivo_origen
                ''',
                (
                    periodo_id,
                    estudiante_id,
                    programa_id,
                    str(row.get('formulario_numero', '')).strip(),
                    str(row.get('estado', '')).strip(),
                    str(row.get('estado_inscripciones', '')).strip(),
                    str(row.get('jornada', '')).strip(),
                    str(row.get('fecha_inscripcion', '')).strip(),
                    str(row.get('usuario_crm', '')).strip(),
                    filename,
                ),
            )
            nuevas_matriculas += 1
        else:
            categoria_nombre = str(row.get('categoria', 'ANTIGUO')).strip().upper()
            cursor.execute('SELECT id FROM categorias WHERE nombre = %s', (categoria_nombre,))
            categoria_result = cursor.fetchone()
            categoria_id = categoria_result[0] if categoria_result else 2

            observaciones = str(row.get('observaciones', '')).strip()
            if observaciones and 'semestre cancelado' in observaciones.lower():
                estado_nombre = 'Cancelado'
            else:
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
                ON CONFLICT (periodo_id, estudiante_id, programa_id) DO UPDATE SET
                    liquidacion_numero = EXCLUDED.liquidacion_numero,
                    categoria_id = EXCLUDED.categoria_id,
                    estado_matricula_id = EXCLUDED.estado_matricula_id,
                    fecha_inscripcion = EXCLUDED.fecha_inscripcion,
                    novedad = EXCLUDED.novedad,
                    archivo_origen = EXCLUDED.archivo_origen
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
        INSERT INTO archivos_importados (nombre_archivo, periodo_id, tipo_datos, total_registros, nuevos_registros)
        VALUES (%s, %s, %s, %s, %s)
        ''',
        (filename, periodo_id, tipo_archivo, len(df), nuevas_matriculas),
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
                f'Archivo={filename}, tipo={tipo_archivo}, periodo={periodo_codigo}, registros={nuevas_matriculas}',
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
        'tipo_archivo': tipo_archivo,
        'warnings': warnings,
    }
