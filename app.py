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
# Session lifetime (e.g., 30 minutes)
app.permanent_session_lifetime = timedelta(minutes=30)

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
    # Allow access to login and static assets without authentication
    exempt_endpoints = {'login', 'static'}
    endpoint = request.endpoint
    if endpoint in exempt_endpoints or endpoint is None:
        return

    # If user has a session token, validate expiration
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

    # Refresh sliding expiration on activity
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
        # Create a token and expiration timestamp
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

    cursor.execute('SELECT COUNT(*) FROM estudiantes')
    total_estudiantes = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM matriculas')
    total_matriculas = cursor.fetchone()[0]

    cursor.execute('''
        SELECT COUNT(DISTINCT p.id)
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    ''')
    total_programas = cursor.fetchone()[0]

    cursor.execute('SELECT nombre_archivo, fecha_importacion, total_registros FROM archivos_importados ORDER BY fecha_importacion DESC LIMIT 1')
    ultimo_archivo = cursor.fetchone()

    cursor.execute('''
        SELECT c.nombre, COUNT(m.id)
        FROM matriculas m
        JOIN categorias c ON m.categoria_id = c.id
        GROUP BY c.nombre
    ''')
    stats_categoria = cursor.fetchall()

    cursor.execute('''
        SELECT p.nombre_original, COUNT(m.id) AS total
        FROM matriculas m
        JOIN programas p ON m.programa_id = p.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
        GROUP BY p.nombre_original
        ORDER BY total DESC
        LIMIT 10
    ''')
    top_programas = cursor.fetchall()

    cursor.execute('''
        SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) AS total
        FROM matriculas m
        JOIN periodos pr ON m.periodo_id = pr.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
        GROUP BY pr.codigo_periodo
        ORDER BY pr.codigo_periodo DESC
    ''')
    stats_periodo = cursor.fetchall()

    conn.close()

    return render_template('dashboard.html', total_estudiantes=total_estudiantes, total_matriculas=total_matriculas,
                           total_programas=total_programas, ultimo_archivo=ultimo_archivo,
                           stats_categoria=stats_categoria, top_programas=top_programas, stats_periodo=stats_periodo)


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

    cursor.execute('SELECT c.nombre, COUNT(m.id) FROM matriculas m JOIN categorias c ON m.categoria_id = c.id JOIN estados_matricula e ON m.estado_matricula_id = e.id WHERE LOWER(e.nombre) = \'confirmado\' GROUP BY c.nombre')
    categorias_data = cursor.fetchall()

    cursor.execute('SELECT p.tipo_programa, COUNT(m.id) FROM matriculas m JOIN programas p ON m.programa_id = p.id JOIN estados_matricula e ON m.estado_matricula_id = e.id WHERE LOWER(e.nombre) = \'confirmado\' GROUP BY p.tipo_programa')
    tipos_programa_data = cursor.fetchall()

    cursor.execute('SELECT e.nombre, COUNT(m.id) FROM estados_matricula e JOIN matriculas m ON m.estado_matricula_id = e.id GROUP BY e.nombre')
    estados_data = cursor.fetchall()

    cursor.execute('SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) FROM matriculas m JOIN periodos pr ON m.periodo_id = pr.id JOIN estados_matricula e ON m.estado_matricula_id = e.id WHERE LOWER(e.nombre) = \'confirmado\' GROUP BY pr.codigo_periodo ORDER BY pr.codigo_periodo')
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
    log_action('VIEW_PROGRAMAS_DETALLES', 'Acceso a página de detalles de programas')
    return render_template('programas_detalles.html')


@app.route('/api/programas-detalles')
@login_required
def get_programas_detalles():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Obtener todos los programas con detalles (solo confirmados)
    # Nuevos = categoría NUEVO, Antiguos = categoría ANTIGUO + REINTEGRO
    cursor.execute('''
        SELECT p.nombre_original, 
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE p.nombre_original IS NOT NULL
        GROUP BY p.nombre_original
        ORDER BY confirmados DESC, p.nombre_original
    ''')
    programas_data = cursor.fetchall()
    conn.close()

    return jsonify({
        'programas': [
            {
                'nombre': r[0],
                'confirmados': r[1] or 0,
                'nuevos': r[2] or 0,
                'antiguos': r[3] or 0
            }
            for r in programas_data
        ]
    })


@app.route('/data')
@login_required
def view_data():
    conn = get_db_connection()
    periodo = request.args.get('periodo', '')
    programa = request.args.get('programa', '')
    categoria = request.args.get('categoria', '')
    # Estado filter: if parameter is missing, default to 'confirmado'
    # If parameter is present but empty string, treat as 'Todos' (no filter)
    estado_param = request.args.get('estado', None)
    if estado_param is None:
        estado_filter = 'confirmado'
        estado_actual = 'Confirmado'
    else:
        estado_actual = estado_param
        estado_filter = estado_param if estado_param != '' else None
    page = int(request.args.get('page', 1))
    per_page = 10

    query = '''
        SELECT e.documento, e.nombre_completo, pr.nombre_original, pr.tipo_programa,
               per.codigo_periodo, c.nombre, em.nombre, m.fecha_inscripcion,
               m.liquidacion_numero, m.novedad
        FROM matriculas m
        JOIN estudiantes e ON m.estudiante_id = e.id
        JOIN programas pr ON m.programa_id = pr.id
        JOIN periodos per ON m.periodo_id = per.id
        JOIN categorias c ON m.categoria_id = c.id
        JOIN estados_matricula em ON m.estado_matricula_id = em.id
        WHERE 1=1
    '''
    params = []
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
        query += ' AND LOWER(em.nombre) = %s'
        params.append(estado_filter.lower())

    query += ' ORDER BY m.fecha_inscripcion DESC'

    cursor = conn.cursor()
    cursor.execute(f'SELECT COUNT(*) FROM ({query}) AS conteo', params)
    total = cursor.fetchone()[0]

    query += ' LIMIT %s OFFSET %s'
    params.extend([per_page, (page - 1) * per_page])
    cursor.execute(query, params)
    datos = cursor.fetchall()

    cursor.execute('SELECT DISTINCT codigo_periodo FROM periodos ORDER BY codigo_periodo DESC')
    periodos = cursor.fetchall()
    cursor.execute('SELECT DISTINCT nombre FROM categorias ORDER BY nombre')
    categorias_list = cursor.fetchall()
    cursor.execute('SELECT DISTINCT nombre_original FROM programas ORDER BY nombre_original')
    programas_list = cursor.fetchall()
    cursor.execute('SELECT DISTINCT nombre FROM estados_matricula ORDER BY nombre')
    estados_list = cursor.fetchall()

    conn.close()
    total_pages = (total + per_page - 1) // per_page

    return render_template('data.html', datos=datos, periodos=periodos, categorias=categorias_list,
                           programas=programas_list, periodo_actual=periodo, categoria_actual=categoria,
                           programa_actual=programa, page=page, total_pages=total_pages, total=total,
                           estados=estados_list, estado_actual=estado_actual)


@app.route('/export')
@login_required
def export_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT e.documento, e.nombre_completo, pr.nombre_original, pr.tipo_programa,
               per.codigo_periodo, c.nombre, em.nombre, m.fecha_inscripcion,
               m.liquidacion_numero, e.correo_personal, e.correo_institucional, m.novedad
        FROM matriculas m
        JOIN estudiantes e ON m.estudiante_id = e.id
        JOIN programas pr ON m.programa_id = pr.id
        JOIN periodos per ON m.periodo_id = per.id
        JOIN categorias c ON m.categoria_id = c.id
        JOIN estados_matricula em ON m.estado_matricula_id = em.id
        ORDER BY per.codigo_periodo DESC, e.nombre_completo
    ''')
    datos = cursor.fetchall()
    conn.close()

    output = BytesIO()
    headers = ['Documento', 'Nombre', 'Programa', 'Tipo Programa', 'Período', 'Categoría', 'Estado',
               'Fecha Inscripción', 'Liquidación', 'Correo Personal', 'Correo Institucional', 'Novedad']

    # Build CSV manually to avoid StringIO/send_file encoding issues
    lines = [','.join(headers)]
    for row in datos:
        escaped = []
        for value in row:
            text = str(value).replace('"', '""')
            escaped.append(f'"{text}"')
        lines.append(','.join(escaped))
    output.write(('\n'.join(lines)).encode('utf-8'))
    output.seek(0)

    return send_file(output, mimetype='text/csv', as_attachment=True,
                     download_name=f'matriculas_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')


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
