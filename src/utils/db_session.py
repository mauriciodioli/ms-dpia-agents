# src/utils/db_session.py
from contextlib import contextmanager
from utils.db import db

@contextmanager
def get_db_session():
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        # 1) Intentá cerrar la conexión activa (si existe y no está cerrada)
        try:
            bind = db.session.get_bind()
            if bind and not getattr(bind, "closed", False):
                db.session.close()   # devuelve la conexión al pool
        except Exception:
            # si ya estaba cerrada o no hay bind, lo ignoramos
            pass
        finally:
            # 2) Siempre limpiar el scoped_session (seguro aunque ya se haya cerrado)
            try:
                db.session.remove()
            except Exception:
                pass
