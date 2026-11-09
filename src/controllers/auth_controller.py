"""Controladores: traducen requests/responses HTTP y delegan en los servicios."""
from flask import current_app, jsonify, request, session

from services.auth_service import AuthError, persist_google_user, verify_google_credential


def get_auth_config():
    return jsonify({"client_id": current_app.config.get("GOOGLE_CLIENT_ID", "")})


def get_current_session():
    response = jsonify({"email": session.get("email"), "authenticated": bool(session.get("email"))})
    response.headers['Cache-Control'] = 'no-store'
    return response


def login_with_google():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify(error="Solicitud de acceso inválida."), 400
    credential = body.get("credential", "")
    client_id = current_app.config.get("GOOGLE_CLIENT_ID", "")
    try:
        info = verify_google_credential(credential, client_id)
        user = persist_google_user(info)
    except AuthError as exc:
        return jsonify({"error": exc.message}), exc.status_code
    session.clear()
    session["email"] = user.correo_electronico
    session["user_id"] = user.id
    return jsonify({"email": user.correo_electronico, "authenticated": True})


def logout():
    session.clear()
    return jsonify({"authenticated": False})
