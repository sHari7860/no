from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_mail import Mail, Message
import os
from functools import wraps
from io import BytesIO
from datetime import datetime, timedelta
import secrets
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv

from config import FRONTEND_TEMPLATES, FRONTEND_STATIC, UPLOAD_FOLDER
from database import init_app, get_db_connection, is_sqlite_database
from scripts.import_data import import_excel_to_db
from security_questions import (
    RESET_TOKEN_MINUTES,
    active_recovery_lock,
    get_active_security_questions,
    get_user_security_questions,
    hash_security_answer,
    record_failed_recovery_attempt,
    record_successful_recovery_attempt,
    user_has_security_questions,
    verify_security_answer,
)

load_dotenv()

# Crear la app indicando explícitamente templates/static del frontend
app = Flask(__name__, template_folder=str(FRONTEND_TEMPLATES), static_folder=str(FRONTEND_STATIC))
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'clave-secreta-para-flask')
# Usar ruta absoluta para uploads
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
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

# garantizar carpeta de uploads
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
    exempt_endpoints = {'login', 'logout', 'forgot_password', 'answer_security_questions', 'reset_password', 'static'}
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

    # Si la sesion es valida, renovar el tiempo de expiracion
    session['auth_expires'] = (datetime.utcnow() + app.permanent_session_lifetime).timestamp()

    # En el primer inicio de sesión se obliga a cambiar la contraseña temporal y
    # después a configurar preguntas de seguridad una única vez.
    if endpoint not in {'change_password', 'setup_security_questions', 'logout'}:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'SELECT requiere_cambio_password, security_questions_configured FROM usuarios WHERE id = %s AND activo = TRUE',
            (user_id,),
        )
        current_user = cur.fetchone()
        conn.close()

        if not current_user:
            session.clear()
            flash('Tu usuario no está activo. Contacta al administrador.', 'error')
            return redirect(url_for('login'))

        if current_user[0]:
            flash('Debes cambiar tu contraseña temporal antes de continuar.', 'warning')
            return redirect(url_for('change_password'))

        if not current_user[1]:
            flash('Configura tus preguntas de seguridad para proteger tu cuenta.', 'warning')
            return redirect(url_for('setup_security_questions'))


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
    """Primer paso de recuperación: solicitar usuario sin revelar si existe."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()

        if not username:
            flash('Ingresa tu usuario', 'error')
            return render_template('forgot_password.html')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, username, nombre_completo
            FROM usuarios
            WHERE username = %s AND activo = TRUE
            ''',
            (username,),
        )
        user = cursor.fetchone()

        generic_message = 'Si la cuenta existe y tiene preguntas configuradas, podrás continuar con la recuperación.'
        if not user:
            conn.close()
            flash(generic_message, 'success')
            return render_template('forgot_password.html')

        user_id = user[0]
        if not user_has_security_questions(cursor, user_id):
            conn.close()
            flash(generic_message, 'success')
            return render_template('forgot_password.html')

        lock = active_recovery_lock(cursor, user_id)
        conn.close()
        if lock:
            flash('La recuperación está bloqueada temporalmente. Intenta nuevamente más tarde.', 'error')
            return render_template('forgot_password.html')

        session['recovery_user_id'] = user_id
        session['recovery_username'] = user[1]
        session['recovery_started_at'] = datetime.utcnow().timestamp()
        return redirect(url_for('answer_security_questions'))

    return render_template('forgot_password.html')


@app.route('/answer_security_questions', methods=['GET', 'POST'])
def answer_security_questions():
    """Valida preguntas de seguridad antes de permitir restablecer contraseña."""
    user_id = session.get('recovery_user_id')
    if not user_id:
        flash('Inicia nuevamente el proceso de recuperación.', 'warning')
        return redirect(url_for('forgot_password'))

    conn = get_db_connection()
    cursor = conn.cursor()
    lock = active_recovery_lock(cursor, user_id)
    if lock:
        conn.close()
        flash('Has superado el máximo de intentos. La recuperación queda bloqueada durante 30 minutos.', 'error')
        return redirect(url_for('forgot_password'))

    questions = get_user_security_questions(cursor, user_id)
    if len(questions) < 3:
        conn.close()
        session.pop('recovery_user_id', None)
        session.pop('recovery_username', None)
        flash('Tu cuenta no tiene preguntas de seguridad configuradas. Contacta al administrador.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        all_correct = True
        for answer_id, _question, answer_hash in questions:
            answer = request.form.get(f'answer_{answer_id}', '')
            if not verify_security_answer(answer, answer_hash):
                all_correct = False
                break

        if not all_correct:
            locked_until, failed_count = record_failed_recovery_attempt(
                cursor,
                user_id,
                request.remote_addr,
                request.headers.get('User-Agent', ''),
            )
            conn.commit()
            conn.close()
            if locked_until:
                flash('Has superado el máximo de intentos. Intenta nuevamente en 30 minutos.', 'error')
                return redirect(url_for('forgot_password'))

            remaining = max(0, 3 - failed_count)
            flash(f'Respuestas incorrectas. Intentos restantes: {remaining}.', 'error')
            return render_template('security_recovery_questions.html', questions=questions)

        record_successful_recovery_attempt(
            cursor,
            user_id,
            request.remote_addr,
            request.headers.get('User-Agent', ''),
        )
        conn.commit()
        conn.close()

        session['password_reset_user_id'] = user_id
        session['password_reset_token'] = secrets.token_urlsafe(32)
        session['password_reset_expires'] = (datetime.utcnow() + timedelta(minutes=RESET_TOKEN_MINUTES)).timestamp()
        flash('Respuestas verificadas. Define tu nueva contraseña.', 'success')
        return redirect(url_for('reset_password'))

    conn.close()
    return render_template('security_recovery_questions.html', questions=questions)


@app.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    """Restablece contraseña usando un token temporal guardado en sesión."""
    user_id = session.get('password_reset_user_id')
    token = session.get('password_reset_token')
    expires = session.get('password_reset_expires')

    try:
        expired = not expires or datetime.utcnow().timestamp() > float(expires)
    except Exception:
        expired = True

    if not user_id or not token or expired:
        session.pop('password_reset_user_id', None)
        session.pop('password_reset_token', None)
        session.pop('password_reset_expires', None)
        flash('La autorización para restablecer contraseña expiró. Inicia nuevamente.', 'warning')
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

        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres', 'error')
            return render_template('reset_password.html')

        conn = get_db_connection()
        cursor = conn.cursor()
        if is_sqlite_database():
            cursor.execute(
                '''
                UPDATE usuarios
                SET password_hash = %s, requiere_cambio_password = FALSE
                WHERE id = %s AND activo = TRUE
                ''',
                (generate_password_hash(password), user_id),
            )
            conn.commit()
            cursor.execute(
                '''
                SELECT username, nombre_completo, rol
                FROM usuarios
                WHERE id = %s AND activo = TRUE
                ''',
                (user_id,),
            )
            user = cursor.fetchone()
        else:
            cursor.execute(
                '''
                UPDATE usuarios
                SET password_hash = %s, requiere_cambio_password = FALSE
                WHERE id = %s AND activo = TRUE
                RETURNING username, nombre_completo, rol
                ''',
                (generate_password_hash(password), user_id),
            )
            user = cursor.fetchone()
        if not user:
            conn.close()
            flash('No fue posible restablecer la contraseña. Contacta al administrador.', 'error')
            return redirect(url_for('login'))

        conn.commit()
        conn.close()

        session.clear()
        session.permanent = True
        session['user_id'] = user_id
        session['username'] = user[0]
        session['nombre_completo'] = user[1]
        session['rol'] = user[2].strip().lower() if user[2] else 'operador'
        session['auth_token'] = secrets.token_urlsafe(32)
        session['auth_expires'] = (datetime.utcnow() + app.permanent_session_lifetime).timestamp()
        log_action('RESET_PASSWORD_SECURITY_QUESTIONS', 'Contraseña restablecida con preguntas de seguridad')
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
        cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password, fecha_creacion FROM usuarios WHERE activo = TRUE ORDER BY fecha_creacion DESC')
    elif status == 'inactivos':
        cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password, fecha_creacion FROM usuarios WHERE activo = FALSE ORDER BY fecha_creacion DESC')
    else:
        cursor.execute('SELECT id, username, email, nombre_completo, rol, activo, requiere_cambio_password, fecha_creacion FROM usuarios ORDER BY fecha_creacion DESC')
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

        if len(password) < 8:
            flash('La contraseña debe tener al menos 8 caracteres', 'error')
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

        if len(new_password) < 8:
            flash('La nueva contraseña debe tener al menos 8 caracteres', 'error')
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

        conn = get_db_connection()
        cursor = conn.cursor()
        has_questions = user_has_security_questions(cursor, session['user_id'])
        cursor.close()
        conn.close()
        if not has_questions:
            flash('Ahora configura tus preguntas de seguridad.', 'warning')
            return redirect(url_for('setup_security_questions'))

        return redirect(url_for('index'))

    return render_template('change_password.html', force_change=force_change)


@app.route('/setup_security_questions', methods=['GET', 'POST'])
@login_required
def setup_security_questions():
    """Permite configurar preguntas de seguridad una sola vez después del cambio de contraseña inicial."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT requiere_cambio_password, security_questions_configured FROM usuarios WHERE id = %s',
        (session['user_id'],),
    )
    user_state = cursor.fetchone()

    if not user_state:
        conn.close()
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('logout'))

    if user_state[0]:
        conn.close()
        flash('Primero debes cambiar tu contraseña temporal.', 'warning')
        return redirect(url_for('change_password'))

    if user_state[1] or user_has_security_questions(cursor, session['user_id']):
        cursor.execute(
            'UPDATE usuarios SET security_questions_configured = TRUE WHERE id = %s',
            (session['user_id'],),
        )
        conn.commit()
        conn.close()
        flash('Tus preguntas de seguridad ya están configuradas.', 'info')
        return redirect(url_for('index'))

    questions = get_active_security_questions(cursor)

    if request.method == 'POST':
        selected_questions = request.form.getlist('question_id')
        answers = request.form.getlist('answer')

        if len(selected_questions) < 3 or len(answers) < 3:
            conn.close()
            flash('Debes responder mínimo 3 preguntas de seguridad.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        question_ids = selected_questions[:3]
        answer_values = answers[:3]

        if len(set(question_ids)) != 3:
            conn.close()
            flash('Selecciona 3 preguntas diferentes.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        if any(len(answer.strip()) < 2 for answer in answer_values):
            conn.close()
            flash('Cada respuesta debe tener al menos 2 caracteres.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        valid_question_ids = {str(row[0]) for row in questions}
        if any(question_id not in valid_question_ids for question_id in question_ids):
            conn.close()
            flash('Una de las preguntas seleccionadas no es válida.', 'error')
            return render_template('setup_security_questions.html', questions=questions)

        try:
            for question_id, answer in zip(question_ids, answer_values):
                cursor.execute(
                    """
                    INSERT INTO user_security_answers (user_id, question_id, answer_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, question_id)
                    DO UPDATE SET answer_hash = EXCLUDED.answer_hash,
                                  activo = TRUE,
                                  fecha_creacion = CURRENT_TIMESTAMP
                    """,
                    (session['user_id'], int(question_id), hash_security_answer(answer)),
                )

            cursor.execute(
                'UPDATE usuarios SET security_questions_configured = TRUE WHERE id = %s',
                (session['user_id'],),
            )
            conn.commit()
            conn.close()
            log_action('SETUP_SECURITY_QUESTIONS', 'Preguntas de seguridad configuradas')
            flash('Preguntas de seguridad configuradas correctamente.', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f'Error configurando preguntas de seguridad: {str(e)}', 'error')
            return render_template('setup_security_questions.html', questions=questions)

    conn.close()
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
            from pathlib import Path
            filepath = str(Path(app.config['UPLOAD_FOLDER']) / filename)
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


def ensure_database_initialized():
    init_app()


if hasattr(app, 'before_first_request'):
    @app.before_first_request
    def _ensure_database_initialized():
        ensure_database_initialized()
elif hasattr(app, 'before_serving'):
    @app.before_serving
    def _ensure_database_initialized():
        ensure_database_initialized()
else:
    # Fallback: init on module import if Flask version lacks both hooks.
    ensure_database_initialized()


if __name__ == '__main__':
    init_app()
    app.run(debug=True, port=5000)
