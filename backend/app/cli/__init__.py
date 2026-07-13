"""CLI commands for the application"""

from .seed import init_app as init_seed
from .ingest_cli import init_app as init_ingest
from .enrich_cli import init_app as init_enrich


def init_app(app):
    """Register all CLI commands with the app"""
    init_seed(app)
    init_ingest(app)
    init_enrich(app)
