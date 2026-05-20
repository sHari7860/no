"""Paquete `backend`.
Exports comunes y facilita ejecución como paquete.
"""

from .config import BASE_DIR, FRONTEND_TEMPLATES, FRONTEND_STATIC, UPLOAD_FOLDER, DATA_DIR

__all__ = [
    'BASE_DIR', 'FRONTEND_TEMPLATES', 'FRONTEND_STATIC', 'UPLOAD_FOLDER', 'DATA_DIR'
]
