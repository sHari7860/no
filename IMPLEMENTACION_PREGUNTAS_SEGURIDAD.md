# Implementación profesional: recuperación con preguntas de seguridad

## Arquitectura recomendada

- **Administrador**: único actor autorizado para crear usuarios y asignar contraseña temporal.
- **Usuario autenticado**: si `requiere_cambio_password = TRUE`, solo puede acceder a cambio de contraseña; después debe configurar preguntas.
- **Preguntas de seguridad**: catálogo administrado en `security_questions`; cada usuario guarda 3 respuestas hasheadas en `user_security_answers`.
- **Recuperación**: flujo no autenticado con verificación de usuario, preguntas configuradas, límite de intentos, bloqueo temporal y token corto para cambio de contraseña.
- **Auditoría**: eventos sensibles se registran en `auditoria` y los fallos de recuperación en `password_recovery_attempts`.

## Flujo completo paso a paso

### Creación de usuario

1. El administrador crea el usuario desde `/create_user`.
2. El sistema guarda la contraseña temporal con `generate_password_hash`.
3. El usuario queda con `requiere_cambio_password = TRUE` y `security_questions_configured = FALSE`.
4. En el primer inicio de sesión, el sistema redirige obligatoriamente a `/change_password`.
5. Después de cambiar la contraseña, si aún no hay preguntas configuradas, redirige a `/setup_security_questions`.
6. El usuario selecciona y responde exactamente 3 preguntas distintas.
7. Las respuestas se normalizan y se almacenan hasheadas; las preguntas no vuelven a mostrarse para configuración.
8. Al finalizar, el usuario entra al dashboard principal.

### Recuperación de contraseña

1. El usuario entra a `/forgot_password` y escribe su usuario.
2. Si existe, está activo y ya configuró preguntas, se redirige a `/security_recovery`.
3. El sistema muestra sus 3 preguntas configuradas.
4. Las respuestas ingresadas se normalizan ignorando mayúsculas, acentos y espacios repetidos.
5. Si las respuestas son correctas, se genera un token temporal de 10 minutos en `password_reset_tokens`.
6. El usuario crea una nueva contraseña en `/reset_password`.
7. El sistema invalida el token, actualiza la contraseña, inicia sesión automáticamente y redirige al dashboard.

## Preguntas de seguridad propuestas

Se sembraron preguntas orientadas a recuerdos privados y menos públicos:

- ¿Cuál fue el nombre de tu primer proyecto personal importante?
- ¿Cuál era el apodo de una persona que te inspiró en tu infancia?
- ¿En qué ciudad viviste durante una etapa que recuerdas bien, pero que no publicas normalmente?
- ¿Cuál fue el nombre de tu primera mascota o animal cercano que recuerdas?
- ¿Cuál es una frase corta que usabas con tu mejor amigo de infancia?
- ¿Cuál fue el primer plato que aprendiste a preparar sin ayuda?
- ¿Cuál era el nombre del lugar donde tomaste una clase extracurricular memorable?
- ¿Cuál fue el primer usuario o alias que usaste en un sistema no público?

Evitar preguntas como fecha de nacimiento, nombre de madre/padre, colegio, ciudad natal o equipo favorito porque suelen ser públicas o deducibles.

## Estructura SQL propuesta

```sql
ALTER TABLE usuarios
  ADD COLUMN IF NOT EXISTS requiere_cambio_password BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS security_questions_configured BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS security_questions (
  id SERIAL PRIMARY KEY,
  pregunta TEXT UNIQUE NOT NULL,
  activa BOOLEAN NOT NULL DEFAULT TRUE,
  fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_security_answers (
  id SERIAL PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  question_id INTEGER NOT NULL REFERENCES security_questions(id),
  answer_hash TEXT NOT NULL,
  fecha_configuracion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (usuario_id, question_id)
);

CREATE TABLE IF NOT EXISTS password_recovery_attempts (
  id SERIAL PRIMARY KEY,
  usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
  username VARCHAR(60),
  ip_origen VARCHAR(45),
  exitoso BOOLEAN NOT NULL DEFAULT FALSE,
  motivo TEXT,
  user_agent TEXT,
  fecha_intento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_recovery_lockouts (
  id SERIAL PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  bloqueado_hasta TIMESTAMP NOT NULL,
  motivo TEXT,
  fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id SERIAL PRIMARY KEY,
  usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL,
  fecha_expiracion TIMESTAMP NOT NULL,
  utilizado BOOLEAN NOT NULL DEFAULT FALSE,
  fecha_uso TIMESTAMP,
  fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Ejemplos de consultas SQL

```sql
-- Crear usuario con contraseña temporal
INSERT INTO usuarios (username, email, password_hash, nombre_completo, rol, activo, requiere_cambio_password)
VALUES (%s, %s, %s, %s, %s, TRUE, TRUE);

-- Consultar preguntas activas
SELECT id, pregunta FROM security_questions WHERE activa = TRUE ORDER BY id;

-- Guardar respuesta hasheada
INSERT INTO user_security_answers (usuario_id, question_id, answer_hash)
VALUES (%s, %s, %s);

-- Registrar intento fallido
INSERT INTO password_recovery_attempts (usuario_id, username, ip_origen, exitoso, motivo, user_agent)
VALUES (%s, %s, %s, FALSE, %s, %s);

-- Bloquear por 30 minutos
INSERT INTO password_recovery_lockouts (usuario_id, bloqueado_hasta, motivo)
VALUES (%s, CURRENT_TIMESTAMP + INTERVAL '30 minutes', 'Tres intentos fallidos');
```

## Endpoints Flask implementados

- `GET/POST /create_user`: crea usuarios con contraseña temporal y cambio obligatorio.
- `GET/POST /change_password`: cambia contraseña; después fuerza configuración de preguntas si faltan.
- `GET/POST /setup_security_questions`: configura 3 preguntas una sola vez.
- `GET/POST /forgot_password`: solicita usuario para iniciar recuperación.
- `GET/POST /security_recovery`: valida respuestas, limita intentos y genera token temporal.
- `GET/POST /reset_password`: permite cambiar contraseña con token temporal válido e inicia sesión automáticamente.

## Seguridad aplicada

- Respuestas hasheadas con `generate_password_hash`; no se guardan en texto plano.
- Comparación usando `check_password_hash` sobre la respuesta normalizada.
- Normalización: minúsculas, eliminación de acentos y colapso de espacios múltiples.
- Máximo 3 intentos fallidos en una ventana de 30 minutos.
- Bloqueo temporal durante 30 minutos en `password_recovery_lockouts`.
- Registro de IP, user-agent, usuario y resultado en `password_recovery_attempts`.
- Token temporal de restablecimiento: aleatorio, hasheado, válido por 10 minutos y de un solo uso.
- Sesión autenticada con expiración deslizante de 30 minutos.

## Manejo de sesiones y tokens temporales

- La sesión normal debe contener solo datos mínimos: `user_id`, `username`, `rol`, `auth_expires` y un identificador aleatorio.
- El token de recuperación nunca debe persistirse en texto plano en base de datos; solo se guarda su hash.
- El token debe expirar rápido, invalidarse al usarse y revocar tokens anteriores del mismo usuario.
- En producción se recomienda `SESSION_COOKIE_SECURE=True`, `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'` y HTTPS obligatorio.

## UX/UI recomendado

- Mostrar el flujo como pasos: usuario → preguntas → nueva contraseña → dashboard.
- No revelar si un usuario existe cuando no tiene preguntas configuradas; usar mensajes genéricos.
- En formularios, marcar campos obligatorios, usar textos de ayuda y validar contraseñas en cliente y servidor.
- En primer inicio, explicar que la contraseña temporal debe reemplazarse y que las preguntas se configuran una sola vez.
- En errores de recuperación, indicar intentos restantes si se desea, pero sin revelar cuál respuesta falló.
- Evitar mostrar respuestas, permitir autocompletado deshabilitado en respuestas y usar mensajes claros.

## Método más seguro: preguntas, PIN temporal o correo

1. **Correo electrónico con enlace/token de un solo uso** suele ser más seguro que preguntas si el correo está protegido con MFA y el enlace expira rápido.
2. **PIN temporal** puede ser seguro si se entrega por un canal confiable, expira en pocos minutos, se hashea y tiene límites de intentos; por SMS es más débil por SIM swapping e interceptación.
3. **Preguntas de seguridad** son el método menos robusto porque dependen de secretos humanos, que pueden ser adivinables, compartidos o investigables.

Para este sistema, preguntas de seguridad es aceptable como reemplazo operativo, pero conviene planear una migración futura a correo con token, autenticador TOTP, passkeys o MFA.

## Riesgos y limitaciones de preguntas de seguridad

- Respuestas fáciles de investigar en redes sociales.
- Respuestas olvidadas, cambiantes o ambiguas.
- Posible reutilización de respuestas en otros sistemas.
- Menor entropía que una contraseña o token aleatorio.
- Exposición si alguien observa el formulario durante la recuperación.

## Mejoras futuras

- MFA con TOTP usando aplicaciones autenticadoras.
- Passkeys/WebAuthn para reducir dependencia de contraseñas.
- Enlaces de recuperación por correo con token de un solo uso y notificaciones de seguridad.
- Rate limiting global por IP con Redis o Flask-Limiter.
- Historial de contraseñas para impedir reutilización.
- Políticas de contraseña basadas en listas de contraseñas filtradas.
- Panel de auditoría para revisar recuperaciones, bloqueos e inicios sospechosos.
