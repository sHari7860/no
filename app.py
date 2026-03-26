from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
import os
from functools import wraps
from io import BytesIO
from datetime import datetime, timedelta
import secrets
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash

from database import init_app, get_db_connection
from import_data import import_excel_to_db

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'clave-secreta-para-flask')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
# Configurar duración de la sesión a 30 minutos
app.permanent_session_lifetime = timedelta(minutes=30)
PERIODO_EXCLUIDO = '20261'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión para continuar', 'error')
            return redirect(url_for('login'))
        return view_func(*args, **kwargs)

    return wrapper


def role_required(*allowed_roles):
    """Decorador para limitar acceso a rutas según el rol del usuario."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if 'user_id' not in session:
                flash('Debes iniciar sesión para continuar', 'error')
                return redirect(url_for('login'))
            
            user_role = session.get('rol', 'operador')
            if user_role not in allowed_roles:
                flash('No tienes permisos para acceder a esta página', 'error')
                return redirect(url_for('index'))
            
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def require_login():
    # Permitir acceso a rutas de login y recursos estáticos sin autenticación
    exempt_endpoints = {'login', 'static'}
    endpoint = request.endpoint
    if endpoint in exempt_endpoints or endpoint is None:
        return

    # Verificar si el usuario está autenticado
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    expires = session.get('auth_expires')
    if not expires:
        session.clear()
        return redirect(url_for('login'))

    try:
        expires_ts = float(expires)
    except Exception:
        session.clear()
        return redirect(url_for('login'))

    if datetime.utcnow().timestamp() > expires_ts:
        session.clear()
        flash('Tu sesión ha expirado. Por favor inicia sesión de nuevo.', 'warning')
        return redirect(url_for('login'))

    # Si la sesion es valida y el usuario esta activo, renovar el tiempo de expiracion
    session['auth_expires'] = (datetime.utcnow() + app.permanent_session_lifetime).timestamp()


def log_action(action, detail=''):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'INSERT INTO auditoria (usuario_id, username, accion, detalle, ip_origen) VALUES (%s, %s, %s, %s, %s)',
        (session.get('user_id'), session.get('username'), action, detail, request.remote_addr),
    )
    conn.commit()
    conn.close()


def get_estado_display_sql(alias_estado='em', alias_matricula='m'):
    return f"""CASE
        WHEN LOWER(COALESCE({alias_matricula}.novedad, '')) LIKE '%semestre cancelado%' THEN 'Cancelado'
        ELSE {alias_estado}.nombre
    END"""


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT id, username, password_hash, nombre_completo, rol, activo FROM usuarios WHERE username = %s',
            (username,),
        )
        user = cur.fetchone()
        conn.close()

        if not user or not user[5] or not check_password_hash(user[2], password):
            flash('Credenciales inválidas', 'error')
            return render_template('login.html')

        session.permanent = True
        session['user_id'] = user[0]
        session['username'] = user[1]
        session['nombre_completo'] = user[3]
        session['rol'] = user[4]
        # Generar un token de sesión único para mayor seguridad
        session['auth_token'] = secrets.token_urlsafe(32)
        session['auth_expires'] = (datetime.utcnow() + app.permanent_session_lifetime).timestamp()
        log_action('LOGIN', 'Inicio de sesión')
        return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    if session.get('user_id'):
        log_action('LOGOUT', 'Cierre de sesión')
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            p.codigo_periodo,
            COUNT(m.id) AS total_matriculas,
            COUNT(DISTINCT CASE WHEN LOWER(e.nombre) = 'confirmado' THEN m.estudiante_id END) AS estudiantes_confirmados,
            COUNT(DISTINCT CASE WHEN LOWER(e.nombre) = 'cancelado' THEN m.estudiante_id END) AS estudiantes_cancelados,
            COUNT(DISTINCT CASE WHEN LOWER(e.nombre) = 'por confirmar' THEN m.estudiante_id END) AS estudiantes_por_confirmar
        FROM periodos p
        LEFT JOIN matriculas m ON m.periodo_id = p.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE p.codigo_periodo NOT IN ('20260', '20259', '20268', '20263', '20258', '20262', %s)
        GROUP BY p.codigo_periodo
        ORDER BY p.codigo_periodo DESC
    ''', (PERIODO_EXCLUIDO,))
    periodos = cursor.fetchall()
    conn.close()

    return render_template('index.html', periodos=periodos)


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT codigo_periodo FROM periodos WHERE codigo_periodo <> %s ORDER BY codigo_periodo DESC', (PERIODO_EXCLUIDO,))
    periodos_disponibles = [row[0] for row in cursor.fetchall()]

    periodo = request.args.get('periodo', '').strip()
    if not periodo and periodos_disponibles:
        periodo = periodos_disponibles[0]

    periodo_id = None
    if periodo:
        cursor.execute('SELECT id FROM periodos WHERE codigo_periodo = %s', (periodo,))
        periodo_row = cursor.fetchone()
        if periodo_row:
            periodo_id = periodo_row[0]

    if periodo_id:
        cursor.execute('''
            SELECT COUNT(DISTINCT m.estudiante_id)
            FROM matriculas m
            WHERE m.periodo_id = %s
        ''', (periodo_id,))
    else:
        cursor.execute('''
            SELECT COUNT(DISTINCT m.estudiante_id)
            FROM matriculas m
            JOIN periodos p ON p.id = m.periodo_id
            WHERE p.codigo_periodo <> %s
        ''', (PERIODO_EXCLUIDO,))
    total_estudiantes = cursor.fetchone()[0]

    if periodo_id:
        cursor.execute('SELECT COUNT(*) FROM matriculas WHERE periodo_id = %s', (periodo_id,))
    else:
        cursor.execute('''
            SELECT COUNT(*)
            FROM matriculas m
            JOIN periodos p ON p.id = m.periodo_id
            WHERE p.codigo_periodo <> %s
        ''', (PERIODO_EXCLUIDO,))
    total_matriculas = cursor.fetchone()[0]

    query_programas = '''
        SELECT COUNT(DISTINCT p.id)
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        LEFT JOIN periodos pr ON m.periodo_id = pr.id
        WHERE LOWER(e.nombre) = 'confirmado' AND pr.codigo_periodo <> %s
    '''
    params_programas = [PERIODO_EXCLUIDO]
    if periodo_id:
        query_programas += ' AND m.periodo_id = %s'
        params_programas.append(periodo_id)
    cursor.execute(query_programas, params_programas)
    
    total_programas = cursor.fetchone()[0]

    cursor.execute('SELECT nombre_archivo, fecha_importacion, total_registros FROM archivos_importados ORDER BY fecha_importacion DESC LIMIT 1')
    ultimo_archivo = cursor.fetchone()

    query_categoria = '''
        SELECT c.nombre, COUNT(m.id)
        FROM matriculas m
        JOIN categorias c ON m.categoria_id = c.id
    '''
    params_categoria = [PERIODO_EXCLUIDO]
    query_categoria += ' WHERE EXISTS (SELECT 1 FROM periodos p WHERE p.id = m.periodo_id AND p.codigo_periodo <> %s)'
    if periodo_id:
        query_categoria += ' AND m.periodo_id = %s'
        params_categoria.append(periodo_id)
    query_categoria += ' GROUP BY c.nombre'
    cursor.execute(query_categoria, params_categoria)
    stats_categoria = cursor.fetchall()

    query_top_programas = '''
        SELECT p.nombre_original, COUNT(m.id) AS total
        FROM matriculas m
        JOIN programas p ON m.programa_id = p.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        JOIN periodos pr ON m.periodo_id = pr.id
        WHERE LOWER(e.nombre) = 'confirmado' AND pr.codigo_periodo <> %s
    '''
    params_top_programas = [PERIODO_EXCLUIDO]
    if periodo_id:
        query_top_programas += ' AND m.periodo_id = %s'
        params_top_programas.append(periodo_id)
    query_top_programas += '''
        GROUP BY p.nombre_original
        ORDER BY total DESC
        LIMIT 10
    '''
    cursor.execute(query_top_programas, params_top_programas)
    top_programas = cursor.fetchall()

    cursor.execute('''
        SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) AS total
        FROM matriculas m
        JOIN periodos pr ON m.periodo_id = pr.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado' AND pr.codigo_periodo <> %s
        GROUP BY pr.codigo_periodo
        ORDER BY pr.codigo_periodo DESC
    ''', (PERIODO_EXCLUIDO,))
    stats_periodo = cursor.fetchall()

    conn.close()

    return render_template('dashboard.html', total_estudiantes=total_estudiantes, total_matriculas=total_matriculas,
                           total_programas=total_programas, ultimo_archivo=ultimo_archivo,
                           stats_categoria=stats_categoria, top_programas=top_programas, stats_periodo=stats_periodo,
                           periodo_actual=periodo, periodos_disponibles=periodos_disponibles)


@app.route('/upload', methods=['GET', 'POST'])
@role_required('admin', 'operador')
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No se seleccionó ningún archivo', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo', 'error')
            return redirect(request.url)

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            result = import_excel_to_db(filepath, filename, actor=session.get('username'))
            if 'error' in result:
                flash(result['error'], 'error')
                os.remove(filepath)
            else:
                flash(f'Archivo importado exitosamente: {result["nuevas_matriculas"]} nuevas matrículas agregadas', 'success')
                flash(f'Período: {result["periodo"]}, Total registros: {result["total_registros"]}', 'success')

            return redirect(url_for('index'))

        flash('Tipo de archivo no permitido. Solo se aceptan Excel (.xlsx, .xls)', 'error')
        return redirect(request.url)

    return render_template('upload.html')


@app.route('/api/estadisticas')
@login_required
def get_estadisticas():
    conn = get_db_connection()
    cursor = conn.cursor()
    periodo = request.args.get('periodo', '').strip()
    periodo_filter = ''
    params = [PERIODO_EXCLUIDO]
    estado_display = get_estado_display_sql(alias_estado='e', alias_matricula='m')

    if periodo:
        periodo_filter = ' AND pr.codigo_periodo = %s'
        params.append(periodo)

    cursor.execute(f'''SELECT c.nombre, COUNT(m.id)
                       FROM matriculas m
                       JOIN categorias c ON m.categoria_id = c.id
                       JOIN estados_matricula e ON m.estado_matricula_id = e.id
                       JOIN periodos pr ON m.periodo_id = pr.id
                       WHERE pr.codigo_periodo <> %s AND LOWER({estado_display}) = 'confirmado'{periodo_filter}
                       GROUP BY c.nombre''', params)
    categorias_data = cursor.fetchall()

    cursor.execute(f'''SELECT p.tipo_programa, COUNT(m.id)
                       FROM matriculas m
                       JOIN programas p ON m.programa_id = p.id
                       JOIN estados_matricula e ON m.estado_matricula_id = e.id
                       JOIN periodos pr ON m.periodo_id = pr.id
                       WHERE pr.codigo_periodo <> %s AND LOWER({estado_display}) = 'confirmado'{periodo_filter}
                       GROUP BY p.tipo_programa''', params)
    tipos_programa_data = cursor.fetchall()

    cursor.execute(f'''SELECT e.nombre, COUNT(m.id)
                       FROM estados_matricula e
                       JOIN matriculas m ON m.estado_matricula_id = e.id
                       JOIN periodos pr ON m.periodo_id = pr.id
                       WHERE pr.codigo_periodo <> %s{periodo_filter}
                       GROUP BY e.nombre''', params)
    estados_data = cursor.fetchall()

    cursor.execute(f'''SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id)
                       FROM matriculas m
                       JOIN periodos pr ON m.periodo_id = pr.id
                       JOIN estados_matricula e ON m.estado_matricula_id = e.id
                       WHERE pr.codigo_periodo <> %s AND LOWER({estado_display}) = 'confirmado'{periodo_filter}
                       GROUP BY pr.codigo_periodo
                       ORDER BY pr.codigo_periodo''', params)
    evolucion_data = cursor.fetchall()
    conn.close()

    return jsonify({
        'categorias': {'labels': [r[0] for r in categorias_data], 'data': [r[1] for r in categorias_data]},
        'tipos_programa': {'labels': [r[0] for r in tipos_programa_data], 'data': [r[1] for r in tipos_programa_data]},
        'estados': {'labels': [r[0] for r in estados_data], 'data': [r[1] for r in estados_data]},
        'evolucion': {'labels': [r[0] for r in evolucion_data], 'data': [r[1] for r in evolucion_data]},
    })


@app.route('/programas-detalles')
@login_required
def programas_detalles():
    # Mensaje de log para acceso a la página de detalles de programas
    log_action('VIEW_PROGRAMAS_DETALLES', 'Acceso a página de detalles de programas')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT codigo_periodo FROM periodos WHERE codigo_periodo <> %s ORDER BY codigo_periodo DESC', (PERIODO_EXCLUIDO,))
    periodos_disponibles = [row[0] for row in cursor.fetchall()]
    conn.close()

    periodo = request.args.get('periodo', '').strip()
    if not periodo and periodos_disponibles:
        periodo = periodos_disponibles[0]
    elif periodo and periodo not in periodos_disponibles and periodos_disponibles:
        periodo = periodos_disponibles[0]

    return render_template('programas_detalles.html', periodo_actual=periodo)


@app.route('/api/programas-detalles')
@login_required
def get_programas_detalles():
    conn = get_db_connection()
    cursor = conn.cursor()
    periodo = request.args.get('periodo', '').strip()
    params = [PERIODO_EXCLUIDO]
    periodo_filter = ' AND (pr.codigo_periodo <> %s OR pr.codigo_periodo IS NULL)'

    if periodo:
        periodo_filter += ' AND pr.codigo_periodo = %s'
        params.append(periodo)

    # Obtener todos los programas con detalles (solo confirmados)
    # Nuevos = categoría NUEVO, Antiguos = categoría ANTIGUO + REINTEGRO
    estado_display = get_estado_display_sql(alias_estado='e', alias_matricula='m')
    cursor.execute(f'''
        SELECT p.nombre_original, 
               COUNT(CASE WHEN LOWER({estado_display}) = 'confirmado' THEN 1 END) AS confirmados,
               COUNT(CASE WHEN LOWER({estado_display}) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
               COUNT(CASE WHEN LOWER({estado_display}) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        LEFT JOIN periodos pr ON m.periodo_id = pr.id
        WHERE p.nombre_original IS NOT NULL
        {periodo_filter}
        GROUP BY p.nombre_original
        ORDER BY confirmados DESC, p.nombre_original
    ''', params)
    programas_data = cursor.fetchall()
    conn.close()

    programas = []
    for row in programas_data:
        confirmados = row[1] or 0
        nuevos = row[2] or 0
        antiguos = row[3] or 0
        # Validación para asegurar consistencia entre columnas.
        if nuevos + antiguos != confirmados:
            antiguos = max(0, confirmados - nuevos)
        programas.append(
            {
                'nombre': row[0],
                'confirmados': confirmados,
                'nuevos': nuevos,
                'antiguos': antiguos,
            }
        )

    return jsonify({'programas': programas})


@app.route('/api/programas-por-periodo')
@login_required
def get_programas_por_periodo():
    conn = get_db_connection()
    cursor = conn.cursor()
    periodo = request.args.get('periodo', '').strip()
    params = [PERIODO_EXCLUIDO]
    query = '''
        SELECT DISTINCT pr.nombre_original
        FROM programas pr
        JOIN matriculas m ON m.programa_id = pr.id
        JOIN periodos pe ON pe.id = m.periodo_id
        WHERE pe.codigo_periodo <> %s
    '''
    if periodo:
        query += ' AND pe.codigo_periodo = %s'
        params.append(periodo)

    query += ' ORDER BY pr.nombre_original'
    cursor.execute(query, params)
    programas = [row[0] for row in cursor.fetchall()]
    conn.close()
    return jsonify({'programas': programas})


@app.route('/data')
@login_required
def view_data():
    conn = get_db_connection()
    periodo = request.args.get('periodo', '')
    programa = request.args.get('programa', '')
    categoria = request.args.get('categoria', '')
    # Permitir filtrar por estado de matrícula, predeterminado "confirmado"
    estado_param = request.args.get('estado', None)
    if estado_param is None:
        estado_filter = 'confirmado'
        estado_actual = 'Confirmado'
    else:
        estado_actual = estado_param
        estado_filter = estado_param if estado_param != '' else None
    page = int(request.args.get('page', 1))
    # Limitar el numero de registros por pagina
    per_page_raw = request.args.get('per_page', 10)
    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = 10
    if per_page <= 0:
        flash('Filas por página debe ser mayor que 0. Se ajustó a 1.', 'warning')
    # Maximo 1000 registros por pagina 
    per_page = max(1, min(per_page, 1000))

    estado_display = get_estado_display_sql(alias_estado='em', alias_matricula='m')

    query = '''
        SELECT e.documento, e.nombre_completo, pr.nombre_original, pr.tipo_programa,
               per.codigo_periodo, c.nombre,
               {estado_display} AS estado_mostrado,
               m.fecha_inscripcion,
               m.liquidacion_numero, m.novedad
        FROM matriculas m
        JOIN estudiantes e ON m.estudiante_id = e.id
        JOIN programas pr ON m.programa_id = pr.id
        JOIN periodos per ON m.periodo_id = per.id
        JOIN categorias c ON m.categoria_id = c.id
        JOIN estados_matricula em ON m.estado_matricula_id = em.id
        WHERE 1=1
    '''.format(estado_display=estado_display)
    params = []
    query += ' AND per.codigo_periodo <> %s'
    params.append(PERIODO_EXCLUIDO)
    if periodo:
        query += ' AND per.codigo_periodo = %s'
        params.append(periodo)
    if programa:
        query += ' AND pr.nombre_original = %s'
        params.append(programa)
    if categoria:
        query += ' AND c.nombre = %s'
        params.append(categoria)
    if estado_filter:
        query += f' AND LOWER({estado_display}) = %s'
        params.append(estado_filter.lower())

    query += ' ORDER BY m.fecha_inscripcion DESC'

    cursor = conn.cursor()
    cursor.execute(f'SELECT COUNT(*) FROM ({query}) AS conteo', params)
    total = cursor.fetchone()[0]

    query += ' LIMIT %s OFFSET %s'
    params.extend([per_page, (page - 1) * per_page])
    cursor.execute(query, params)
    datos = cursor.fetchall()

    cursor.execute('''
        SELECT DISTINCT per.codigo_periodo
        FROM periodos per
        INNER JOIN matriculas m ON m.periodo_id = per.id
        WHERE per.codigo_periodo <> %s
        ORDER BY per.codigo_periodo DESC
    ''', (PERIODO_EXCLUIDO,))
    periodos = cursor.fetchall()
    cursor.execute('SELECT DISTINCT nombre FROM categorias ORDER BY nombre')
    categorias_list = cursor.fetchall()
    params_programas = [PERIODO_EXCLUIDO]
    query_programas = '''
        SELECT DISTINCT pr.nombre_original
        FROM programas pr
        JOIN matriculas m ON m.programa_id = pr.id
        JOIN periodos per ON per.id = m.periodo_id
        WHERE per.codigo_periodo <> %s
    '''
    if periodo:
        query_programas += ' AND per.codigo_periodo = %s'
        params_programas.append(periodo)
    query_programas += ' ORDER BY pr.nombre_original'
    cursor.execute(query_programas, params_programas)
    programas_list = cursor.fetchall()
    if programa and programa not in [p[0] for p in programas_list]:
        programa = ''
    cursor.execute('SELECT DISTINCT nombre FROM estados_matricula ORDER BY nombre')
    estados_list = cursor.fetchall()

    query_chart = '''
        SELECT pr.nombre_original, COUNT(*) AS total
        FROM matriculas m
        JOIN programas pr ON m.programa_id = pr.id
        JOIN periodos per ON m.periodo_id = per.id
        JOIN categorias c ON m.categoria_id = c.id
        JOIN estados_matricula em ON m.estado_matricula_id = em.id
        WHERE per.codigo_periodo <> %s
    '''
    chart_params = [PERIODO_EXCLUIDO]
    if periodo:
        query_chart += ' AND per.codigo_periodo = %s'
        chart_params.append(periodo)
    if programa:
        query_chart += ' AND pr.nombre_original = %s'
        chart_params.append(programa)
    if categoria:
        query_chart += ' AND c.nombre = %s'
        chart_params.append(categoria)
    if estado_filter:
        query_chart += f' AND LOWER({estado_display}) = %s'
        chart_params.append(estado_filter.lower())
    query_chart += '''
        GROUP BY pr.nombre_original
        ORDER BY total DESC, pr.nombre_original
        LIMIT 10
    '''
    cursor.execute(query_chart, chart_params)
    chart_data = cursor.fetchall()

    conn.close()
    total_pages = (total + per_page - 1) // per_page

    # Mensaje de log para acceso a la página de datos con filtros aplicados
    return render_template('data.html', datos=datos, periodos=periodos, categorias=categorias_list,
                           programas=programas_list, periodo_actual=periodo, categoria_actual=categoria,
                           programa_actual=programa, page=page, total_pages=total_pages, total=total,
                           estados=estados_list, estado_actual=estado_actual,
                           per_page=per_page, chart_data=chart_data)




@app.route('/logs')
@role_required('admin', 'operador')
def view_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username, accion, detalle, ip_origen, fecha_evento
        FROM auditoria
        ORDER BY fecha_evento DESC
        LIMIT 200
    ''')
    logs = cursor.fetchall()
    conn.close()
    return render_template('logs.html', logs=logs)


if __name__ == '__main__':
    init_app()
    app.run(debug=True, port=5000)
