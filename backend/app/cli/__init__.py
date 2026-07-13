"""CLI commands for the application"""

from .seed import init_app as init_seed
from .ingest_cli import init_app as init_ingest


def init_app(app):
    """Register all CLI commands with the app"""
    init_seed(app)
    init_ingest(app)
