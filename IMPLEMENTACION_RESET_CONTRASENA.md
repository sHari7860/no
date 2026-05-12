# Sistema de Restablecimiento de Contraseña por SMS

## Resumen

El sistema de recuperación de contraseña usa el teléfono registrado del usuario y envía un código de 6 dígitos por SMS. La recuperación ya no depende del correo electrónico.

## Componentes

### Base de datos
- `usuarios.telefono`: número telefónico registrado para recibir códigos.
- `password_recovery_codes.telefono`: teléfono asociado al código de recuperación.
- `password_recovery_codes.codigo`: código de 6 dígitos.
- `password_recovery_codes.fecha_expiracion`: expiración del código.
- `password_recovery_codes.utilizado` y `fecha_uso`: control de códigos usados.

### Configuración SMS

El envío se realiza mediante un gateway HTTP configurado por variables de entorno:

- `SMS_API_URL`: URL del proveedor/gateway SMS.
- `SMS_API_TOKEN`: token Bearer opcional.
- `SMS_API_PHONE_FIELD`: nombre del campo JSON para el teléfono. Por defecto: `to`.
- `SMS_API_MESSAGE_FIELD`: nombre del campo JSON para el mensaje. Por defecto: `message`.
- `SMS_SENDER_ID`: identificador del remitente opcional.

El sistema no imprime el código ni el teléfono completo en pantalla, porque los números registrados son reales.

## Flujo

1. El usuario solicita recuperación con su nombre de usuario.
2. El sistema busca el usuario activo y su teléfono registrado.
3. Se genera un código aleatorio de 6 dígitos válido por 30 minutos.
4. El código se guarda en `password_recovery_codes` y se envía por SMS.
5. El usuario ingresa el código recibido.
6. El sistema valida que el teléfono, el código, el estado no usado y la expiración coincidan.
7. Si el código es válido, el usuario puede registrar una nueva contraseña.
8. La contraseña se guarda con `generate_password_hash`.

## Seguridad

- Mensajes genéricos para evitar enumeración de usuarios.
- Código de un solo uso.
- Expiración de 30 minutos.
- Teléfono enmascarado en las pantallas de verificación y restablecimiento.
- No se envía ni expone el código por correo electrónico.
