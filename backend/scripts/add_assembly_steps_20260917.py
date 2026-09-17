"""Add per-project assembly steps and component access hazards (2026-09-17).

PartsBin's schema is created by db.create_all(), which never ALTERs an
existing table - new columns land here instead. Idempotent: every statement is
IF NOT EXISTS, so re-running is a no-op.

Adds:
  component.access_tags       list[str] - contacts this part hides once mounted
  component.assembly_notes    the human sentence about that hazard
  project_assembly_step       the ordered solder/assembly steps of a project

The point of the pair is that a hazard is recorded ONCE on the part (a XIAO's
BAT+/BAT- pads are on its underside on every carrier it is ever soldered to)
and every project whose BOM includes it inherits the warning, while the steps
record the order for one particular build and get checked against it.

    cd /opt/partsbin/backend && venv/bin/python scripts/add_assembly_steps_20260917.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from app import create_app, db  # noqa: E402

STATEMENTS = [
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS access_tags JSONB",
    "ALTER TABLE component ADD COLUMN IF NOT EXISTS assembly_notes TEXT",
    """
    CREATE TABLE IF NOT EXISTS project_assembly_step (
        id            SERIAL PRIMARY KEY,
        project_id    INTEGER NOT NULL REFERENCES project(id),
        seq           INTEGER NOT NULL DEFAULT 1,
        title         VARCHAR(200) NOT NULL,
        body_md       TEXT,
        component_id  INTEGER REFERENCES component(id),
        obstructs     JSONB,
        needs_access  JSONB,
        done          BOOLEAN NOT NULL DEFAULT FALSE,
        done_at       TIMESTAMP,
        created_at    TIMESTAMP,
        updated_at    TIMESTAMP
    )
    """,
    # Every read is "the steps of one project, in order", so the index carries
    # the sort as well as the filter.
    "CREATE INDEX IF NOT EXISTS ix_project_assembly_step_project_id "
    "ON project_assembly_step (project_id, seq)",
    "CREATE INDEX IF NOT EXISTS ix_project_assembly_step_component_id "
    "ON project_assembly_step (component_id)",
]


def main():
    app = create_app(os.getenv('FLASK_ENV', 'production'))
    with app.app_context():
        for statement in STATEMENTS:
            db.session.execute(text(statement))
        db.session.commit()
        print(f'{len(STATEMENTS)} schema statement(s) applied')


if __name__ == '__main__':
    main()
