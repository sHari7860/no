-- Migración segura para reemplazar recuperación por código/correo con preguntas de seguridad.
-- Compatible con PostgreSQL y re-ejecutable en bases existentes.

BEGIN;

ALTER TABLE IF EXISTS usuarios
    ADD COLUMN IF NOT EXISTS security_questions_configured BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS security_questions (
    id SERIAL PRIMARY KEY,
    pregunta TEXT UNIQUE NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    orden INTEGER NOT NULL DEFAULT 0,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_security_answers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES security_questions(id) ON DELETE RESTRICT,
    answer_hash TEXT NOT NULL,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, question_id)
);

CREATE TABLE IF NOT EXISTS password_recovery_attempts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    ip_origen VARCHAR(45),
    user_agent TEXT,
    exitoso BOOLEAN NOT NULL DEFAULT FALSE,
    fecha_intento TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_recovery_locks (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    locked_until TIMESTAMP NOT NULL,
    motivo TEXT,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_security_questions_activo_orden
    ON security_questions(activo, orden, id);

CREATE INDEX IF NOT EXISTS idx_user_security_answers_user
    ON user_security_answers(user_id);

CREATE INDEX IF NOT EXISTS idx_recovery_attempts_user_date
    ON password_recovery_attempts(user_id, fecha_intento DESC);

CREATE INDEX IF NOT EXISTS idx_recovery_attempts_ip_date
    ON password_recovery_attempts(ip_origen, fecha_intento DESC);

CREATE INDEX IF NOT EXISTS idx_recovery_locks_user_until
    ON password_recovery_locks(user_id, locked_until);

INSERT INTO security_questions (pregunta, orden) VALUES
    ('¿Cuál fue el nombre de un profesor que recuerdas especialmente?', 10),
    ('¿Cuál era el apodo de tu mejor amigo o amiga de la infancia?', 20),
    ('¿Cuál fue el nombre de tu primera mascota o de una mascota que recuerdas?', 30),
    ('¿En qué ciudad o barrio viviste cuando tenías 10 años?', 40),
    ('¿Cuál fue el primer concierto, evento o partido al que asististe?', 50),
    ('¿Cuál era el nombre de un libro, película o serie favorita de tu adolescencia?', 60),
    ('¿Cuál fue el primer lugar al que viajaste fuera de tu ciudad?', 70),
    ('¿Cuál era el nombre de tu primer jefe, mentor o entrenador?', 80)
ON CONFLICT (pregunta) DO UPDATE
SET activo = TRUE,
    orden = EXCLUDED.orden;

UPDATE usuarios u
SET security_questions_configured = TRUE
WHERE EXISTS (
    SELECT 1
    FROM user_security_answers usa
    WHERE usa.user_id = u.id
      AND usa.activo = TRUE
);

COMMIT;
