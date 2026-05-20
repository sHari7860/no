"""Compatibilidad: proxy para ejecutar la app con `python app.py`.

Importa la aplicación desde `backend.app` y la arranca con las mismas opciones
que el runner del paquete. Esto evita tener que actualizar atajos y servicios.
"""

from __future__ import annotations

import os

try:
    from backend.app import app
    from backend.database import init_app
except Exception as exc:
    raise RuntimeError('No se pudo importar backend.app. Ejecuta desde la raíz del proyecto.') from exc


if __name__ == '__main__':
    current_dir = os.getcwd()
    print(f'Iniciando la aplicación desde: {current_dir}')

    if not os.path.isdir(os.path.join(current_dir, 'backend')):
        raise RuntimeError(
            'No se detectó la carpeta backend en el directorio actual. ' \
            'Ejecuta este script desde la raíz del proyecto.'
        )

    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_RUN_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', 'False').lower() in ('1', 'true')
    print(f'Usando host={host}, port={port}, debug={debug}')
    init_app()
    app.run(host=host, port=port, debug=debug)
