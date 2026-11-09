"""Paquete de rutas (blueprints) de la aplicación."""
from routes.auth_routes import auth_bp
from routes.main_routes import main_bp

__all__ = ["auth_bp", "main_bp"]
