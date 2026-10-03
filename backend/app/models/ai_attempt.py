from datetime import datetime
from app import db


class AiAttempt(db.Model):
    """One row per (component, kind) once a paid Claude web lookup has run.

    kind: 'enrich' (image/datasheet/metadata), 'price' (street-price estimate),
    'lookup' (candidate identification). The first attempt per component and
    kind may be automatic; every later one must be a person's explicit action
    (manual=true from the UI, or a CLI command naming --component-id). See
    app/services/ai_gate.py. Web-search calls cost ~$0.2-1 each, and the
    nightly sweep re-trying the same parts ran ~$18/night (2026-10-02/03).
    """
    __tablename__ = 'ai_attempt'

    component_id = db.Column(db.Integer, db.ForeignKey('component.id', ondelete='CASCADE'),
                             primary_key=True)
    kind = db.Column(db.String(20), primary_key=True)
    first_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    count = db.Column(db.Integer, nullable=False, default=1)
    last_source = db.Column(db.String(20), nullable=True)  # auto | manual | seed

    def to_dict(self):
        return {
            'kind': self.kind,
            'first_at': self.first_at.isoformat() if self.first_at else None,
            'last_at': self.last_at.isoformat() if self.last_at else None,
            'count': self.count,
            'last_source': self.last_source,
        }
