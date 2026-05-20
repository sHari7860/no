import re
import unicodedata
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

MAX_SECURITY_QUESTION_ATTEMPTS = 3
RECOVERY_LOCK_MINUTES = 30
RESET_TOKEN_MINUTES = 15


def normalize_security_answer(answer: str) -> str:
    """Normaliza respuestas para comparar ignorando mayúsculas y espacios innecesarios."""
    if answer is None:
        return ''

    normalized = unicodedata.normalize('NFKC', str(answer))
    normalized = normalized.strip().lower()
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized


def hash_security_answer(answer: str) -> str:
    return generate_password_hash(normalize_security_answer(answer))


def verify_security_answer(answer: str, answer_hash: str) -> bool:
    if not answer_hash:
        return False
    return check_password_hash(answer_hash, normalize_security_answer(answer))


def user_has_security_questions(cursor, user_id: int) -> bool:
    cursor.execute(
        '''
        SELECT COUNT(*)
        FROM user_security_answers
        WHERE user_id = %s AND activo = TRUE
        ''',
        (user_id,),
    )
    return cursor.fetchone()[0] >= 3


def get_active_security_questions(cursor):
    cursor.execute(
        '''
        SELECT id, pregunta
        FROM security_questions
        WHERE activo = TRUE
        ORDER BY orden ASC, id ASC
        ''',
    )
    return cursor.fetchall()


def get_user_security_questions(cursor, user_id: int):
    cursor.execute(
        '''
        SELECT usa.id, sq.pregunta, usa.answer_hash
        FROM user_security_answers usa
        JOIN security_questions sq ON sq.id = usa.question_id
        WHERE usa.user_id = %s AND usa.activo = TRUE
        ORDER BY usa.id ASC
        ''',
        (user_id,),
    )
    return cursor.fetchall()


def active_recovery_lock(cursor, user_id: int):
    cursor.execute(
        '''
        SELECT locked_until
        FROM password_recovery_locks
        WHERE user_id = %s AND locked_until > %s
        ORDER BY locked_until DESC
        LIMIT 1
        ''',
        (user_id, datetime.utcnow()),
    )
    return cursor.fetchone()


def record_failed_recovery_attempt(cursor, user_id: int, ip_address: str, user_agent: str = ''):
    now = datetime.utcnow()
    cursor.execute(
        '''
        INSERT INTO password_recovery_attempts (user_id, ip_origen, user_agent, exitoso, fecha_intento)
        VALUES (%s, %s, %s, FALSE, %s)
        ''',
        (user_id, ip_address, user_agent[:255] if user_agent else '', now),
    )
    cursor.execute(
        '''
        SELECT COUNT(*)
        FROM password_recovery_attempts
        WHERE user_id = %s
          AND exitoso = FALSE
          AND fecha_intento >= %s
        ''',
        (user_id, now - timedelta(minutes=RECOVERY_LOCK_MINUTES)),
    )
    failed_count = cursor.fetchone()[0]

    if failed_count >= MAX_SECURITY_QUESTION_ATTEMPTS:
        locked_until = now + timedelta(minutes=RECOVERY_LOCK_MINUTES)
        cursor.execute(
            '''
            INSERT INTO password_recovery_locks (user_id, locked_until, motivo, fecha_creacion)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET locked_until = EXCLUDED.locked_until,
                          motivo = EXCLUDED.motivo,
                          fecha_creacion = EXCLUDED.fecha_creacion
            ''',
            (user_id, locked_until, 'Demasiados intentos fallidos de preguntas de seguridad', now),
        )
        return locked_until, failed_count

    return None, failed_count


def record_successful_recovery_attempt(cursor, user_id: int, ip_address: str, user_agent: str = ''):
    cursor.execute(
        '''
        INSERT INTO password_recovery_attempts (user_id, ip_origen, user_agent, exitoso, fecha_intento)
        VALUES (%s, %s, %s, TRUE, %s)
        ''',
        (user_id, ip_address, user_agent[:255] if user_agent else '', datetime.utcnow()),
    )
    cursor.execute('DELETE FROM password_recovery_locks WHERE user_id = %s', (user_id,))
