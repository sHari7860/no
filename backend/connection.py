"""Shim de compatibilidad. Exporta funciones de `database.py` para evitar romper imports antiguos.

Este módulo permanece para soportar scripts que importen `backend.connection`.
"""

from backend.database import get_db_connection, init_app  # re-export

__all__ = ['get_db_connection', 'init_app']

