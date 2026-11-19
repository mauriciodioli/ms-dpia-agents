"""Rutas de autenticación, delegando la lógica en los controladores."""
from flask import Blueprint

from controllers.auth_controller import (
    get_auth_config,
    get_current_session,
    login_with_google,
    logout,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

from services.email_login import start as email_start, verify as email_verify
auth_bp.add_url_rule('/email/start', view_func=email_start, methods=['POST'])
auth_bp.add_url_rule('/email/verify', view_func=email_verify, methods=['POST'])

auth_bp.add_url_rule("/config", view_func=get_auth_config, methods=["GET"])
auth_bp.add_url_rule("/me", view_func=get_current_session, methods=["GET"])
auth_bp.add_url_rule("/google", view_func=login_with_google, methods=["POST"])
auth_bp.add_url_rule("/logout", view_func=logout, methods=["POST"])
