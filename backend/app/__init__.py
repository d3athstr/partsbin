import os
import logging
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
from .config import config

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()


def create_app(config_name=None):
    """Application factory pattern"""
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Trust proxy headers from nginx (X-Forwarded-For, X-Forwarded-Proto, etc.)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Configure logging for production (gunicorn)
    if not app.debug:
        gunicorn_logger = logging.getLogger('gunicorn.error')
        app.logger.handlers = gunicorn_logger.handlers
        app.logger.setLevel(gunicorn_logger.level)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    CORS(app, origins=app.config['CORS_ORIGINS'], supports_credentials=True)

    # Configure login manager
    login_manager.session_protection = 'basic'

    @login_manager.unauthorized_handler
    def unauthorized():
        """Return JSON 401 for API requests instead of redirecting"""
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Authentication required'}), 401
        return jsonify({'error': 'Authentication required'}), 401

    # Import models
    from .models import (  # noqa: F401
        user, passkey, invitation, tag, category, component, project, order,
        processed_message,
    )

    # User loader for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from .models.user import User
        return User.query.get(int(user_id))

    # Register blueprints
    from .routes import (
        auth, admin, components, tags, projects, orders, ingest, dashboard,
        uploads,
    )

    app.register_blueprint(auth.auth_bp, url_prefix='/api/auth')
    app.register_blueprint(admin.admin_bp, url_prefix='/api/admin')
    app.register_blueprint(components.components_bp, url_prefix='/api/components')
    app.register_blueprint(components.catalog_bp, url_prefix='/api')
    app.register_blueprint(tags.tags_bp, url_prefix='/api/tags')
    app.register_blueprint(projects.projects_bp, url_prefix='/api/projects')
    app.register_blueprint(orders.orders_bp, url_prefix='/api/orders')
    app.register_blueprint(orders.review_bp, url_prefix='/api/review')
    app.register_blueprint(ingest.ingest_bp, url_prefix='/api')
    app.register_blueprint(dashboard.dashboard_bp, url_prefix='/api')
    app.register_blueprint(uploads.uploads_bp, url_prefix='/uploads')

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return {'error': 'Resource not found'}, 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        return {'error': 'Internal server error'}, 500

    @app.route('/api/health')
    def health():
        return {'status': 'healthy'}, 200

    # Register CLI commands
    from . import cli
    cli.init_app(app)

    return app
