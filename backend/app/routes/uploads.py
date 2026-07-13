from flask import Blueprint, current_app, send_from_directory
from flask_login import login_required

uploads_bp = Blueprint('uploads', __name__)


@uploads_bp.route('/<path:filename>', methods=['GET'])
@login_required
def serve_upload(filename):
    """Serve uploaded files (dev; behind nginx proxy in prod, still auth-gated)"""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)
