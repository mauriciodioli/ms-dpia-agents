"""Punto de entrada de la aplicación Flask DPIA."""
from flask import Flask

import config
from model import ma
from routes import auth_bp, main_bp
from routes.catalog_routes import catalog_bp
from routes.query_routes import query_bp
from utils.db import db


def create_app():
    app = Flask(__name__)
    app.config.from_object(config)

    from services.scraping_quota import MySQLScrapingQuota
    app.extensions["scraping_quota"] = MySQLScrapingQuota()

    db.init_app(app)
    ma.init_app(app)

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(query_bp)
    from routes.agent_routes import agent_bp
    app.register_blueprint(agent_bp)
    from controllers.publicaciones import publicaciones
    app.register_blueprint(publicaciones)

    from model.logs import logs, init_request_logging
    app.register_blueprint(logs)
    init_request_logging(app)

    from agent_engine import init_app as init_agent_engine
    init_agent_engine(app)

    return app


app = create_app()

if __name__ == "__main__":
    from services.base44_images import start_image_worker
    start_image_worker(app)
    app.run(debug=app.config["DEBUG"], host=app.config["HOST"], port=app.config["PORT"])
