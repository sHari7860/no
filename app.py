from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_mail import Mail, Message
import os
import string
import random
from functools import wraps
from io import BytesIO
from datetime import datetime, timedelta
import secrets
import re
import unicodedata
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

from database import init_app, get_db_connection
from import_data import import_excel_to_db

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'clave-secreta-para-flask')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
# Configurar duración de la sesión a 30 minutos
app.permanent_session_lifetime = timedelta(minutes=30)

# Configuración de correo
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', '')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', '')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER') or app.config['MAIL_USERNAME'] or 'noreply@unitec.edu.co'
app.config['MAIL_SUPPRESS_SEND'] = not (app.config['MAIL_USERNAME'] and app.config['MAIL_PASSWORD'])

mail = Mail(app)

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
            
            user_role = session.get('rol', '').strip().lower()
            if user_role not in [role.strip().lower() for role in allowed_roles]:
                flash('No tienes permisos para acceder a esta página', 'error')
                return redirect(url_for('index'))
            
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


@app.before_request
def require_login():
    # Permitir acceso a rutas de login y recursos estáticos sin autenticación
    exempt_endpoints = {'login', 'logout', 'forgot_password', 'security_recovery', 'reset_password', 'static'}
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

    if endpoint in {'change_password', 'setup_security_questions', 'logout'}:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        'SELECT requiere_cambio_password, security_questions_configured FROM usuarios WHERE id = %s AND activo = TRUE',
        (user_id,),
    )
    auth_state = cur.fetchone()
    conn.close()

    if not auth_state:
        session.clear()
        flash('Tu usuario ya no está activo. Contacta al administrador.', 'warning')
        return redirect(url_for('login'))

    if auth_state[0]:
        flash('Debes cambiar tu contraseña antes de continuar.', 'warning')
        return redirect(url_for('change_password'))

    if not auth_state[1]:
        flash('Configura tus preguntas de seguridad para proteger tu cuenta.', 'warning')
        return redirect(url_for('setup_security_questions'))


def normalize_security_answer(answer):
    """Normaliza respuestas para comparar ignorando mayúsculas, acentos y espacios extra."""
    normalized = unicodedata.normalize('NFKD', answer or '')
    normalized = ''.join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r'\s+', ' ', normalized.strip().lower())
    return normalized


def password_is_strong(password):
    return (
        len(password or '') >= 8
        and re.search(r'[A-Za-z]', password or '')
        and re.search(r'\d', password or '')
    )


def get_security_questions():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id, pregunta FROM security_questions WHERE activa = TRUE ORDER BY id')
    questions = cur.fetchall()
    conn.close()
    return questions


def security_questions_configured(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM user_security_answers WHERE usuario_id = %s', (user_id,))
    configured = cur.fetchone()[0] >= 3
    if configured:
        cur.execute('UPDATE usuarios SET security_questions_configured = TRUE WHERE id = %s', (user_id,))
        conn.commit()
    conn.close()
    return configured


def get_active_recovery_lock(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT bloqueado_hasta FROM password_recovery_lockouts
           WHERE usuario_id = %s AND bloqueado_hasta > %s
           ORDER BY bloqueado_hasta DESC LIMIT 1""",
        (user_id, datetime.utcnow()),
    )
    lock = cur.fetchone()
    conn.close()
    return lock[0] if lock else None


def register_recovery_failure(user_id, username, reason):
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.utcnow()
    cur.execute(
        """INSERT INTO password_recovery_attempts
           (usuario_id, username, ip_origen, exitoso, motivo, user_agent)
           VALUES (%s, %s, %s, FALSE, %s, %s)""",
        (user_id, username, request.remote_addr, reason, request.headers.get('User-Agent', '')[:255]),
    )
    cur.execute(
        """SELECT COUNT(*) FROM password_recovery_attempts
           WHERE usuario_id = %s AND exitoso = FALSE AND fecha_intento > %s""",
        (user_id, now - timedelta(minutes=30)),
    )
    failures = cur.fetchone()[0]
    locked_until = None
    if failures >= 3:
        locked_until = now + timedelta(minutes=30)
        cur.execute(
            """INSERT INTO password_recovery_lockouts (usuario_id, bloqueado_hasta, motivo)
               VALUES (%s, %s, %s)""",
            (user_id, locked_until, 'Tres intentos fallidos en recuperación'),
        )
    conn.commit()
    conn.close()
    return locked_until


def register_recovery_success(user_id, username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO password_recovery_attempts
           (usuario_id, username, ip_origen, exitoso, motivo, user_agent)
           VALUES (%s, %s, %s, TRUE, %s, %s)""",
        (user_id, username, request.remote_addr, 'Respuestas correctas', request.headers.get('User-Agent', '')[:255]),
    )
    conn.commit()
    conn.close()


def register_recovery_lookup_attempt(username, reason):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO password_recovery_attempts
           (usuario_id, username, ip_origen, exitoso, motivo, user_agent)
           VALUES (NULL, %s, %s, FALSE, %s, %s)""",
        (username, request.remote_addr, reason, request.headers.get('User-Agent', '')[:255]),
    )
    conn.commit()
    conn.close()


def create_password_reset_token(user_id):
    plain_token = secrets.token_urlsafe(32)
    token_hash = generate_password_hash(plain_token)
    expires_at = datetime.utcnow() + timedelta(minutes=10)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE password_reset_tokens SET utilizado = TRUE WHERE usuario_id = %s AND utilizado = FALSE', (user_id,))
    cur.execute(
        'INSERT INTO password_reset_tokens (usuario_id, token_hash, fecha_expiracion) VALUES (%s, %s, %s) RETURNING id',
        (user_id, token_hash, expires_at),
    )
    token_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return token_id, plain_token


def validate_password_reset_token(token_id, plain_token):
    if not token_id or not plain_token:
        return None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT prt.id, prt.usuario_id, prt.token_hash, u.username, u.nombre_completo, u.rol
           FROM password_reset_tokens prt
           JOIN usuarios u ON u.id = prt.usuario_id
           WHERE prt.id = %s AND prt.utilizado = FALSE AND prt.fecha_expiracion > %s AND u.activo = TRUE""",
        (token_id, datetime.utcnow()),
    )
    token = cur.fetchone()
    conn.close()
    if token and check_password_hash(token[2], plain_token):
        return token
    return None


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
            'SELECT id, username, password_hash, nombre_completo, rol, activo, requiere_cambio_password, security_questions_configured FROM usuarios WHERE username = %s',
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
        session['rol'] = user[4].strip().lower() if user[4] else 'operador'
        # Generar un token de sesión único para mayor seguridad
        session['auth_token'] = secrets.token_urlsafe(32)
        session['auth_expires'] = (datetime.utcnow() + app.permanent_session_lifetime).timestamp()
        log_action('LOGIN', 'Inicio de sesión')
        
        # Si el usuario requiere cambio de contraseña, redirigir a change_password
        if user[6]:
            flash('Debes cambiar tu contraseña antes de continuar', 'warning')
            return redirect(url_for('change_password'))

        if not user[7]:
            flash('Configura tus preguntas de seguridad antes de continuar', 'warning')
            return redirect(url_for('setup_security_questions'))

        return redirect(url_for('index'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    if session.get('user_id'):
        log_action('LOGOUT', 'Cierre de sesión')
    session.clear()
    return redirect(url_for('login'))


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()

        if not username:
            flash('Ingresa tu usuario', 'error')
            return render_template('forgot_password.html')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id, username, security_questions_configured FROM usuarios WHERE username = %s AND activo = TRUE',
            (username,),
        )
        user = cursor.fetchone()
        conn.close()

        if not user or not user[2]:
            register_recovery_lookup_attempt(username, 'Usuario inexistente, inactivo o sin preguntas configuradas')
            flash('Si la cuenta existe y tiene preguntas configuradas, podrás continuar con la recuperación.', 'success')
            return render_template('forgot_password.html')

        locked_until = get_active_recovery_lock(user[0])
        if locked_until:
            flash(f'Recuperación bloqueada temporalmente hasta {locked_until.strftime("%d/%m/%Y %H:%M UTC")}.', 'error')
            return render_template('forgot_password.html')

        session['recovery_user_id'] = user[0]
        session['recovery_username'] = user[1]
        return redirect(url_for('security_recovery'))

    return render_template('forgot_password.html')


@app.route('/security_recovery', methods=['GET', 'POST'])
def security_recovery():
    user_id = session.get('recovery_user_id')
    username = session.get('recovery_username')
    if not user_id or not username:
        flash('Inicia la recuperación ingresando tu usuario.', 'warning')
        return redirect(url_for('forgot_password'))

    locked_until = get_active_recovery_lock(user_id)
    if locked_until:
        flash(f'Recuperación bloqueada temporalmente hasta {locked_until.strftime("%d/%m/%Y %H:%M UTC")}.', 'error')
        return redirect(url_for('forgot_password'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT usa.id, sq.pregunta, usa.answer_hash
           FROM user_security_answers usa
           JOIN security_questions sq ON sq.id = usa.question_id
           WHERE usa.usuario_id = %s
           ORDER BY usa.id""",
        (user_id,),
    )
    answers = cursor.fetchall()
    conn.close()

    if len(answers) < 3:
        session.pop('recovery_user_id', None)
        session.pop('recovery_username', None)
        flash('La cuenta no tiene preguntas de seguridad configuradas. Contacta al administrador.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        all_valid = True
        for answer_id, _question, answer_hash in answers:
            submitted = normalize_security_answer(request.form.get(f'answer_{answer_id}', ''))
            if not submitted or not check_password_hash(answer_hash, submitted):
                all_valid = False
                break

        if not all_valid:
            locked_until = register_recovery_failure(user_id, username, 'Respuestas de seguridad incorrectas')
            if locked_until:
                session.pop('recovery_user_id', None)
                session.pop('recovery_username', None)
                flash('Superaste los 3 intentos. La recuperación queda bloqueada por 30 minutos.', 'error')
                return redirect(url_for('forgot_password'))
            flash('Las respuestas no son correctas. Revisa e inténtalo de nuevo.', 'error')
            return render_template('recover_security_questions.html', questions=answers, username=username)

        register_recovery_success(user_id, username)
        token_id, plain_token = create_password_reset_token(user_id)
        session.pop('recovery_user_id', None)
        session.pop('recovery_username', None)
        session['password_reset_token_id'] = token_id
        session['password_reset_token'] = plain_token
        flash('Respuestas verificadas. Crea una nueva contraseña.', 'success')
        return redirect(url_for('reset_password'))

    return render_template('recover_security_questions.html', questions=answers, username=username)


@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    token_id = session.get('password_reset_token_id')
    plain_token = session.get('password_reset_token')
    token = validate_password_reset_token(token_id, plain_token)

    if not token:
        session.pop('password_reset_token_id', None)
        session.pop('password_reset_token', None)
        flash('El enlace temporal de recuperación expiró. Inicia el proceso nuevamente.', 'error')
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        if not password or not password_confirm:
            flash('Completa todos los campos', 'error')
            return render_template('reset_password.html')

        if password != password_confirm:
            flash('Las contraseñas no coinciden', 'error')
            return render_template('reset_password.html')

        if not password_is_strong(password):
            flash('La contraseña debe tener al menos 8 caracteres e incluir letras y números.', 'error')
            return render_template('reset_password.html')

        user_id = token[1]
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE usuarios SET password_hash = %s, requiere_cambio_password = FALSE WHERE id = %s',
            (generate_password_hash(password), user_id),
        )
        cursor.execute('UPDATE password_reset_tokens SET utilizado = TRUE, fecha_uso = %s WHERE id = %s', (datetime.utcnow(), token[0]))
        conn.commit()
        conn.close()

        session.clear()
        session.permanent = True
        session['user_id'] = user_id
        session['username'] = token[3]
        session['nombre_completo'] = token[4]
        session['rol'] = token[5].strip().lower() if token[5] else 'operador'
        session['auth_token'] = secrets.token_urlsafe(32)
        session['auth_expires'] = (datetime.utcnow() + app.permanent_session_lifetime).timestamp()
        log_action('RESET_PASSWORD', 'Contraseña restablecida mediante preguntas de seguridad')
        flash('Contraseña actualizada. Has ingresado automáticamente al sistema.', 'success')
        return redirect(url_for('index'))

    return render_template('reset_password.html')


@app.route('/users')
@role_required('admin')
def users():
    status = request.args.get('status', 'todos').strip().lower()
    if status not in ['todos', 'activos', 'inactivos']:
        status = 'todos'

    conn = get_db_connection()
    cursor = conn.cursor()
    if status == 'activos':
        cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password, security_questions_configured, fecha_creacion FROM usuarios WHERE activo = TRUE ORDER BY fecha_creacion DESC')
    elif status == 'inactivos':
        cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password, security_questions_configured, fecha_creacion FROM usuarios WHERE activo = FALSE ORDER BY fecha_creacion DESC')
    else:
        cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password, security_questions_configured, fecha_creacion FROM usuarios ORDER BY fecha_creacion DESC')
    users_list = cursor.fetchall()

    cursor.execute('SELECT COUNT(*) FROM usuarios')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM usuarios WHERE activo = TRUE')
    count_activos = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM usuarios WHERE activo = FALSE')
    count_inactivos = cursor.fetchone()[0]
    conn.close()

    return render_template('users.html', users=users_list, status=status,
                           total_users=total_users, count_activos=count_activos,
                           count_inactivos=count_inactivos)


@app.route('/toggle_user_status/<int:user_id>', methods=['POST'])
@role_required('admin')
def toggle_user_status(user_id):
    if user_id == session.get('user_id'):
        flash('No puedes cambiar el estado de tu propio usuario', 'error')
        return redirect(url_for('users'))

    status = request.form.get('status', 'todos').strip().lower()
    if status not in ['todos', 'activos', 'inactivos']:
        status = 'todos'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT username, activo FROM usuarios WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    if not user:
        conn.close()
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('users', status=status))

    new_status = not user[1]
    cursor.execute('UPDATE usuarios SET activo = %s WHERE id = %s', (new_status, user_id))
    conn.commit()
    conn.close()

    if new_status:
        log_action('ACTIVATE_USER', f'Usuario activado: {user[0]}')
        flash('Usuario activado exitosamente', 'success')
    else:
        log_action('INACTIVATE_USER', f'Usuario inactivado: {user[0]}')
        flash('Usuario inactivado exitosamente', 'success')

    return redirect(url_for('users', status=status))


@app.route('/create_user', methods=['GET', 'POST'])
@role_required('admin')
def create_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        nombre_completo = request.form.get('nombre_completo', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('confirm_password', '')
        rol = request.form.get('rol', 'operador').strip().lower()
        activo = request.form.get('activo', 'on') != 'off'

        if not username or not email or not nombre_completo or not password or not password_confirm:
            flash('Completa todos los campos obligatorios', 'error')
            return render_template('create_user.html')

        if password != password_confirm:
            flash('Las contraseñas no coinciden', 'error')
            return render_template('create_user.html')

        if not password_is_strong(password):
            flash('La contraseña debe tener al menos 8 caracteres e incluir letras y números', 'error')
            return render_template('create_user.html')

        if rol not in ['admin', 'operador']:
            flash('Rol inválido', 'error')
            return render_template('create_user.html')

        # Validar formato de email básico
        if '@' not in email or '.' not in email:
            flash('El correo electrónico no es válido', 'error')
            return render_template('create_user.html')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Verificar si el username ya existe
        cursor.execute('SELECT id FROM usuarios WHERE username = %s', (username,))
        if cursor.fetchone():
            conn.close()
            flash('El nombre de usuario ya existe', 'error')
            return render_template('create_user.html')

        # Verificar si el email ya existe
        cursor.execute('SELECT id FROM usuarios WHERE email = %s', (email,))
        if cursor.fetchone():
            conn.close()
            flash('El correo electrónico ya está registrado', 'error')
            return render_template('create_user.html')

        try:
            cursor.execute(
                'INSERT INTO usuarios (username, email, password_hash, nombre_completo, rol, activo, requiere_cambio_password) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (username, email, generate_password_hash(password), nombre_completo, rol, activo, True)
            )
            conn.commit()
            log_action('CREATE_USER', f'Usuario creado: {username} ({rol}) - {email}')
            flash('Usuario creado exitosamente. Debe cambiar su contraseña en el próximo inicio de sesión', 'success')
            conn.close()
            return redirect(url_for('users'))
        except Exception as e:
            conn.close()
            flash(f'Error al crear usuario: {str(e)}', 'error')
            return render_template('create_user.html')

    return render_template('create_user.html')


@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@role_required('admin')
def edit_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        nombre_completo = request.form.get('nombre_completo', '').strip()
        rol = request.form.get('rol', 'operador').strip().lower()
        activo = request.form.get('activo') == 'on'
        require_password_change = request.form.get('require_password_change') == 'on'

        if not username or not email or not nombre_completo:
            flash('Completa todos los campos obligatorios', 'error')
            cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password FROM usuarios WHERE id = %s', (user_id,))
            user = cursor.fetchone()
            conn.close()
            return render_template('edit_user.html', user=user)

        if '@' not in email or '.' not in email:
            flash('El correo electrónico no es válido', 'error')
            cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password FROM usuarios WHERE id = %s', (user_id,))
            user = cursor.fetchone()
            conn.close()
            return render_template('edit_user.html', user=user)

        if rol not in ['admin', 'operador']:
            flash('Rol inválido', 'error')
            cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password FROM usuarios WHERE id = %s', (user_id,))
            user = cursor.fetchone()
            conn.close()
            return render_template('edit_user.html', user=user)

        # Verificar que email no esté en uso por otro usuario
        cursor.execute('SELECT id FROM usuarios WHERE email = %s AND id != %s', (email, user_id))
        if cursor.fetchone():
            flash('El correo electrónico ya está registrado por otro usuario', 'error')
            cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password FROM usuarios WHERE id = %s', (user_id,))
            user = cursor.fetchone()
            conn.close()
            return render_template('edit_user.html', user=user)

        try:
            cursor.execute(
                'UPDATE usuarios SET username = %s, email = %s, nombre_completo = %s, rol = %s, activo = %s, requiere_cambio_password = %s WHERE id = %s',
                (username, email, nombre_completo, rol, activo, require_password_change, user_id)
            )
            log_action('UPDATE_USER', f'Usuario actualizado: {username}')
            if require_password_change:
                flash('Usuario actualizado. Se requerirá cambio de contraseña en el próximo inicio de sesión.', 'success')
            else:
                flash('Usuario actualizado exitosamente', 'success')

            conn.commit()
            conn.close()
            return redirect(url_for('users'))
        except Exception as e:
            conn.close()
            flash(f'Error al actualizar usuario: {str(e)}', 'error')
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password FROM usuarios WHERE id = %s', (user_id,))
            user = cursor.fetchone()
            conn.close()
            return render_template('edit_user.html', user=user)

    cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password FROM usuarios WHERE id = %s', (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('users'))

    return render_template('edit_user.html', user=user)


def send_verification_email(email, username, verification_code, subject):
    """Envía un correo de verificación con código al usuario."""
    if not app.config['MAIL_USERNAME'] or not app.config['MAIL_PASSWORD']:
        return False, 'La configuración del correo no está completa. Contacta al administrador.'

    try:
        msg = Message(
            subject=subject,
            recipients=[email],
            html=f'''
            <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>Verificación de cambio de contraseña</h2>
                    <p>Hola {username},</p>
                    <p>Tu código de verificación es:</p>
                    <h1 style="color: #007bff; letter-spacing: 5px;">{verification_code}</h1>
                    <p>Este código es válido por 30 minutos.</p>
                    <p>Si no solicitaste este cambio, ignora este mensaje.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">UNITEC - Sistema de Gestión</p>
                </body>
            </html>
            '''
        )
        mail.send(msg)
        return True, None
    except Exception as e:
        print(f'Error enviando correo: {e}')
        return False, 'Error al enviar el correo. Por favor intenta de nuevo.'


@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT requiere_cambio_password FROM usuarios WHERE id = %s', (session['user_id'],))
    user_data = cursor.fetchone()
    cursor.close()
    conn.close()

    if not user_data:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('index'))

    force_change = user_data[0]

    if request.method == 'POST':
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not force_change and not current_password:
            flash('Completa todos los campos', 'error')
            return render_template('change_password.html', force_change=force_change)

        if not new_password or not confirm_password:
            flash('Completa todos los campos', 'error')
            return render_template('change_password.html', force_change=force_change)

        if new_password != confirm_password:
            flash('Las nuevas contraseñas no coinciden', 'error')
            return render_template('change_password.html', force_change=force_change)

        if not password_is_strong(new_password):
            flash('La nueva contraseña debe tener al menos 8 caracteres e incluir letras y números', 'error')
            return render_template('change_password.html', force_change=force_change)

        if not force_change:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT password_hash FROM usuarios WHERE id = %s', (session['user_id'],))
            current_user_data = cursor.fetchone()
            cursor.close()
            conn.close()

            if not current_user_data or not check_password_hash(current_user_data[0], current_password):
                flash('Contraseña actual incorrecta', 'error')
                return render_template('change_password.html', force_change=force_change)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            'UPDATE usuarios SET password_hash = %s, requiere_cambio_password = %s WHERE id = %s',
            (generate_password_hash(new_password), False, session['user_id'])
        )
        conn.commit()
        cursor.close()
        conn.close()

        log_action('CHANGE_PASSWORD', 'Contraseña cambiada por el usuario')
        flash('Contraseña cambiada exitosamente', 'success')
        if not security_questions_configured(session['user_id']):
            return redirect(url_for('setup_security_questions'))
        return redirect(url_for('index'))

    return render_template('change_password.html', force_change=force_change)


@app.route('/setup_security_questions', methods=['GET', 'POST'])
@login_required
def setup_security_questions():
    if security_questions_configured(session['user_id']):
        flash('Tus preguntas de seguridad ya están configuradas.', 'info')
        return redirect(url_for('index'))

    questions = get_security_questions()
    if len(questions) < 3:
        flash('No hay suficientes preguntas de seguridad disponibles. Contacta al administrador.', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        selected_question_ids = request.form.getlist('question_id')
        answers = request.form.getlist('answer')

        if len(selected_question_ids) < 3 or len(answers) < 3:
            flash('Debes seleccionar y responder mínimo 3 preguntas.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        selected_question_ids = selected_question_ids[:3]
        answers = answers[:3]
        normalized_answers = [normalize_security_answer(answer) for answer in answers]

        if len(set(selected_question_ids)) != 3:
            flash('Selecciona 3 preguntas diferentes.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        if any(len(answer) < 3 for answer in normalized_answers):
            flash('Cada respuesta debe tener al menos 3 caracteres útiles.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        valid_ids = {str(question[0]) for question in questions}
        if any(question_id not in valid_ids for question_id in selected_question_ids):
            flash('Una de las preguntas seleccionadas no es válida.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            for question_id, normalized_answer in zip(selected_question_ids, normalized_answers):
                cursor.execute(
                    'INSERT INTO user_security_answers (usuario_id, question_id, answer_hash) VALUES (%s, %s, %s)',
                    (session['user_id'], int(question_id), generate_password_hash(normalized_answer)),
                )
            cursor.execute('UPDATE usuarios SET security_questions_configured = TRUE WHERE id = %s', (session['user_id'],))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            conn.close()
            flash(f'No fue posible guardar las preguntas: {str(exc)}', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        conn.close()
        log_action('SETUP_SECURITY_QUESTIONS', 'Preguntas de seguridad configuradas')
        flash('Preguntas configuradas correctamente. Bienvenido al dashboard.', 'success')
        return redirect(url_for('index'))

    return render_template('setup_security_questions.html', questions=questions)


@app.route('/delete_user/<int:user_id>', methods=['POST'])
@role_required('admin')
def delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('No puedes eliminar tu propio usuario', 'error')
        return redirect(url_for('users'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT username FROM usuarios WHERE id = %s', (user_id,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('users'))

    try:
        cursor.execute('DELETE FROM usuarios WHERE id = %s', (user_id,))
        conn.commit()
        log_action('DELETE_USER', f'Usuario eliminado: {user[0]}')
        flash('Usuario eliminado exitosamente', 'success')
    except Exception as e:
        flash(f'Error al eliminar usuario: {str(e)}', 'error')

    conn.close()
    return redirect(url_for('users'))


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
        WHERE p.codigo_periodo NOT IN ('20260', '20259', '20268', '20263', '20258')
        GROUP BY p.codigo_periodo
        ORDER BY p.codigo_periodo DESC
    ''')
    periodos = cursor.fetchall()
    conn.close()

    return render_template('index.html', periodos=periodos)


@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT codigo_periodo FROM periodos ORDER BY codigo_periodo DESC')
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
        cursor.execute('SELECT COUNT(*) FROM estudiantes')
    total_estudiantes = cursor.fetchone()[0]

    if periodo_id:
        cursor.execute('SELECT COUNT(*) FROM matriculas WHERE periodo_id = %s', (periodo_id,))
    else:
        cursor.execute('SELECT COUNT(*) FROM matriculas')
    total_matriculas = cursor.fetchone()[0]

    query_programas = '''
        SELECT COUNT(DISTINCT p.id)
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    '''
    params_programas = []
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
    params_categoria = []
    if periodo_id:
        query_categoria += ' WHERE m.periodo_id = %s'
        params_categoria.append(periodo_id)
    query_categoria += ' GROUP BY c.nombre'
    cursor.execute(query_categoria, params_categoria)
    stats_categoria = cursor.fetchall()

    query_top_programas = '''
        SELECT p.nombre_original, COUNT(m.id) AS total
        FROM matriculas m
        JOIN programas p ON m.programa_id = p.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    '''
    params_top_programas = []
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
        WHERE LOWER(e.nombre) = 'confirmado'
        GROUP BY pr.codigo_periodo
        ORDER BY pr.codigo_periodo DESC
    ''')
    stats_periodo = cursor.fetchall()


    conn.close()

    return render_template('dashboard.html', total_estudiantes=total_estudiantes, total_matriculas=total_matriculas,
                           total_programas=total_programas, ultimo_archivo=ultimo_archivo,
                           stats_categoria=stats_categoria, top_programas=top_programas, stats_periodo=stats_periodo,
                           periodo_actual=periodo, periodos_disponibles=periodos_disponibles)


@app.route('/upload', methods=['GET', 'POST'])
@role_required('admin')
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
                for warning in result.get('warnings', []):
                    flash(warning, 'warning')

            return redirect(url_for('index'))

        flash('Tipo de archivo no permitido. Solo se aceptan Excel (.xlsx, .xls)', 'error')
        return redirect(request.url)

    return render_template('upload.html')


@app.route('/delete_period', methods=['POST'])
@role_required('admin')
def delete_period():
    periodo = request.form.get('periodo', '').strip()
    if not periodo:
        flash('Período inválido', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id FROM periodos WHERE codigo_periodo = %s', (periodo,))
    periodo_row = cursor.fetchone()
    if not periodo_row:
        conn.close()
        flash('Período no encontrado', 'error')
        return redirect(url_for('index'))

    periodo_id = periodo_row[0]
    cursor.execute('DELETE FROM matriculas WHERE periodo_id = %s', (periodo_id,))
    deleted_matriculas = cursor.rowcount
    cursor.execute('DELETE FROM archivos_importados WHERE periodo_id = %s', (periodo_id,))
    deleted_archivos = cursor.rowcount
    conn.commit()
    conn.close()

    log_action('DELETE_PERIOD', f'Período {periodo} eliminado por admin. Matrículas borradas: {deleted_matriculas}, archivos importados borrados: {deleted_archivos}')
    flash(f'Período {periodo} eliminado y reabierto para nueva importación.', 'success')
    return redirect(url_for('index'))


@app.route('/api/estadisticas')
@login_required
def get_estadisticas():
    conn = get_db_connection()
    cursor = conn.cursor()
    periodo = request.args.get('periodo', '').strip()
    periodo_filter = ''
    params = []

    if periodo:
        periodo_filter = ' AND pr.codigo_periodo = %s'
        params.append(periodo)

    cursor.execute(f'''SELECT c.nombre, COUNT(m.id)
                       FROM matriculas m
                       JOIN categorias c ON m.categoria_id = c.id
                       JOIN estados_matricula e ON m.estado_matricula_id = e.id
                       JOIN periodos pr ON m.periodo_id = pr.id
                       WHERE LOWER(e.nombre) = 'confirmado'{periodo_filter}
                       GROUP BY c.nombre''', params)
    categorias_data = cursor.fetchall()

    cursor.execute(f'''SELECT p.tipo_programa, COUNT(m.id)
                       FROM matriculas m
                       JOIN programas p ON m.programa_id = p.id
                       JOIN estados_matricula e ON m.estado_matricula_id = e.id
                       JOIN periodos pr ON m.periodo_id = pr.id
                       WHERE LOWER(e.nombre) = 'confirmado'{periodo_filter}
                       GROUP BY p.tipo_programa''', params)
    tipos_programa_data = cursor.fetchall()

    cursor.execute(f'''SELECT e.nombre, COUNT(m.id)
                       FROM estados_matricula e
                       JOIN matriculas m ON m.estado_matricula_id = e.id
                       JOIN periodos pr ON m.periodo_id = pr.id
                       WHERE 1=1{periodo_filter}
                       GROUP BY e.nombre''', params)
    estados_data = cursor.fetchall()

    cursor.execute(f'''SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id)
                       FROM matriculas m
                       JOIN periodos pr ON m.periodo_id = pr.id
                       JOIN estados_matricula e ON m.estado_matricula_id = e.id
                       WHERE LOWER(e.nombre) = 'confirmado'{periodo_filter}
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
    cursor.execute('SELECT codigo_periodo FROM periodos ORDER BY codigo_periodo DESC')
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
    params = []
    periodo_filter = ''

    if periodo:
        periodo_filter = ' AND pr.codigo_periodo = %s'
        params.append(periodo)

    # Obtener todos los programas con detalles (solo confirmados)
    # Nuevos = categoría NUEVO, Antiguos = categoría ANTIGUO + REINTEGRO
    cursor.execute(f'''
        SELECT p.nombre_original, 
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos
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
    periodo = request.args.get('periodo', '').strip()
    programa = request.args.get('programa', '').strip()
    categoria = request.args.get('categoria', '').strip()
    # Permitir filtrar por estado de matrícula, predeterminado "confirmado"
    estado_param = request.args.get('estado', None)
    if estado_param is None:
        estado_filter = 'confirmado'
        estado_actual = 'Confirmado'
    else:
        estado_param = estado_param.strip()
        estado_actual = estado_param
        estado_filter = estado_param if estado_param != '' else None
    page = int(request.args.get('page', 1))
    # Limitar el numero de registros por pagina
    try:
        per_page = int(request.args.get('per_page', 10))
    except ValueError:
        per_page = 10
    # Maximo 1000 registros por pagina 
    per_page = max(1, min(per_page, 1000))

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
        query += ' AND TRIM(per.codigo_periodo) = TRIM(%s)'
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

    cursor.execute('''
        SELECT DISTINCT per.codigo_periodo
        FROM periodos per
        INNER JOIN matriculas m ON m.periodo_id = per.id
        ORDER BY per.codigo_periodo DESC
    ''')
    periodos = cursor.fetchall()
    cursor.execute('SELECT DISTINCT nombre FROM categorias ORDER BY nombre')
    categorias_list = cursor.fetchall()

    # Obtener programas según el período seleccionado (para mantener la dependencia entre filtros)
    if periodo:
        cursor.execute('''
            SELECT DISTINCT pr.nombre_original
            FROM programas pr
            INNER JOIN matriculas m ON m.programa_id = pr.id
            INNER JOIN periodos per ON m.periodo_id = per.id
            WHERE TRIM(per.codigo_periodo) = TRIM(%s)
            ORDER BY pr.nombre_original
        ''', (periodo,))
    else:
        cursor.execute('SELECT DISTINCT nombre_original FROM programas ORDER BY nombre_original')
    programas_list = cursor.fetchall()

    # Si un programa está seleccionado pero no pertenece a ese período, reiniciarlo a vacío
    if programa and (programa,) not in programas_list:
        programa = ''

        # Recalcular conteo y datos con programa vacio si era inválido para el período
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
            query += ' AND TRIM(per.codigo_periodo) = TRIM(%s)'
            params.append(periodo)
        if categoria:
            query += ' AND c.nombre = %s'
            params.append(categoria)
        if estado_filter:
            query += ' AND LOWER(em.nombre) = %s'
            params.append(estado_filter.lower())

        query += ' ORDER BY m.fecha_inscripcion DESC'

        cursor.execute(f'SELECT COUNT(*) FROM ({query}) AS conteo', params)
        total = cursor.fetchone()[0]

        query += ' LIMIT %s OFFSET %s'
        params.extend([per_page, (page - 1) * per_page])
        cursor.execute(query, params)
        datos = cursor.fetchall()

    cursor.execute('SELECT DISTINCT nombre FROM estados_matricula ORDER BY nombre')
    estados_list = cursor.fetchall()

    # Calcular conteos GLOBALES para la gráfica según los filtros activos
    estado_counts_global = {}
    chart_data = None  # Solo mostrar gráfica si hay filtro
    
    if periodo or programa:  # Solo mostrar gráfica si hay período o programa filtrado
        query_chart = '''
            SELECT em.nombre, COUNT(*) as cantidad
            FROM matriculas m
            JOIN estados_matricula em ON m.estado_matricula_id = em.id
            JOIN periodos per ON m.periodo_id = per.id
            JOIN programas pr ON m.programa_id = pr.id
            WHERE 1=1
        '''
        params_chart = []
        
        if periodo:
            query_chart += ' AND TRIM(per.codigo_periodo) = TRIM(%s)'
            params_chart.append(periodo)
        if programa:
            query_chart += ' AND pr.nombre_original = %s'
            params_chart.append(programa)
        
        query_chart += ' GROUP BY em.nombre ORDER BY em.nombre'
        
        cursor.execute(query_chart, params_chart)
        for row in cursor.fetchall():
            estado_counts_global[row[0] or 'Desconocido'] = row[1]
        
        chart_data = True  # Flag para mostrar la gráfica

    conn.close()
    total_pages = (total + per_page - 1) // per_page

    # Mensaje de log para acceso a la página de datos con filtros aplicados
    return render_template('data.html', datos=datos, periodos=periodos, categorias=categorias_list,
                           programas=programas_list, periodo_actual=periodo, categoria_actual=categoria,
                           programa_actual=programa, page=page, total_pages=total_pages, total=total,
                           estados=estados_list, estado_actual=estado_actual,
                           per_page=per_page, estado_counts=estado_counts_global, chart_data=chart_data)




@app.route('/logs')
@role_required('admin')
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
