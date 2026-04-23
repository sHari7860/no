import os
import smtplib
from email.message import EmailMessage


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


def send_password_reset_code(recipient_email: str, username: str, code: str) -> tuple[bool, str]:
    """Envía un código de recuperación por correo usando configuración SMTP por variables de entorno."""
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER')
    smtp_password = os.getenv('SMTP_PASSWORD')
    smtp_from = os.getenv('SMTP_FROM', smtp_user or 'no-reply@example.com')
    use_tls = _env_flag('SMTP_USE_TLS', True)

    if not smtp_host:
        return False, 'SMTP_HOST no configurado'

    message = EmailMessage()
    message['Subject'] = 'Código de recuperación de contraseña'
    message['From'] = smtp_from
    message['To'] = recipient_email
    message.set_content(
        f'Hola {username},\n\n'
        f'Tu código de recuperación es: {code}\n\n'
        'Este código vence en 15 minutos y solo puede usarse una vez.\n'
        'Si no solicitaste este cambio, ignora este correo.'
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        return False, str(exc)

    return True, ''
