"""Lógica de negocio para la autenticación con Google."""
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google.auth.exceptions import GoogleAuthError
from functools import partial
import requests
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from model.usuario import Usuario
from utils.db import db


class AuthError(Exception):
    """Error de autenticación con un mensaje y código HTTP asociados."""

    def __init__(self, message, status_code=401):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def verify_google_credential(credential, client_id):
    """Verifica un credential de Google Sign-In y devuelve la información del usuario."""
    if not client_id:
        raise AuthError("Google OAuth no está configurado", 503)
    if not isinstance(credential, str) or not credential.strip() or len(credential) > 16384:
        raise AuthError("Credencial Google inválida", 400)
    try:
        transport = partial(google_requests.Request(), timeout=10)
        info = id_token.verify_oauth2_token(credential, transport, client_id)
    except ValueError:
        raise AuthError("Credencial Google inválida", 401) from None
    except (GoogleAuthError, requests.RequestException):
        raise AuthError("No se pudo verificar la identidad con Google. Reintentá.", 503) from None
    if info.get("email_verified") is not True:
        raise AuthError("Email sin verificar", 401)
    email, subject = info.get("email"), info.get("sub")
    if (not isinstance(email, str) or len(email) > 120 or '@' not in email
            or not isinstance(subject, str) or not subject.strip() or len(subject) > 255):
        raise AuthError("Perfil Google inválido", 401)
    return info


def _google_user(info):
    """Find by Google's stable subject; link email only when Google owns it."""
    email, subject = info['email'].strip().lower(), info['sub']
    user = Usuario.query.filter_by(google_id=subject).one_or_none()
    if user is None:
        user = Usuario.query.filter_by(correo_electronico=email).one_or_none()
        if user is not None:
            # Legacy email registrations stored the literal text '(NULL)'.
            # It is not a Google binding; never replace a genuine different ID.
            legacy_unlinked = user.google_id == '(NULL)' and user.auth_provider == 'email'
            has_google_binding = bool(user.google_id) and not legacy_unlinked
            if has_google_binding and user.google_id != subject:
                raise AuthError("La cuenta ya está vinculada a otra identidad Google.", 409)
            if not has_google_binding and not (email.endswith('@gmail.com') or info.get('hd')):
                raise AuthError("Esta cuenta requiere verificar el acceso antes de vincular Google.", 409)
        else:
            user = Usuario(correo_electronico=email, auth_provider='google', google_id=subject)
            db.session.add(user)
    if not user.activo:
        raise AuthError("La cuenta está deshabilitada.", 403)
    user.google_id = subject
    user.google_email = email
    picture = info.get('picture')
    user.google_picture = picture if isinstance(picture, str) and picture.startswith('https://') and len(picture) <= 500 else None
    user.auth_provider = 'google'
    return user


def persist_google_user(info):
    """Persist in the existing usuarios table before opening a login session."""
    for attempt in range(2):
        try:
            user = _google_user(info)
            db.session.commit()
            db.session.refresh(user)
            return user
        except IntegrityError:
            db.session.rollback()
            if attempt:
                raise AuthError("No se pudo guardar el usuario. Reintentá.", 503) from None
        except SQLAlchemyError:
            db.session.rollback()
            raise AuthError("No se pudo guardar el usuario. Reintentá.", 503) from None
        except AuthError:
            db.session.rollback()
            raise
