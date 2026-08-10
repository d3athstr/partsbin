from datetime import datetime
from sqlalchemy.orm import joinedload
from app import db

PROJECT_STATUSES = ('planning', 'active', 'built', 'on_hold', 'retired')
PROJECT_FILE_KINDS = ('image', 'pdf', 'schematic', 'firmware', 'model3d', 'other')


class Project(db.Model):
    """Electronics project with markdown docs, files and a BOM"""
    __tablename__ = 'project'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='planning')
    description = db.Column(db.Text, nullable=True)
    readme_md = db.Column(db.Text, nullable=True)  # rendered as markdown in the UI
    repo_url = db.Column(db.String(500), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign keys
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Relationships
    bom = db.relationship('ProjectComponent', backref='project', lazy='dynamic',
                          cascade='all, delete-orphan')
    files = db.relationship('ProjectFile', backref='project', lazy='dynamic',
                            cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Project {self.name}>'

    def to_summary(self):
        """Compact representation for embedding in other payloads"""
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
        }

    def to_dict(self, include_detail=False):
        """Convert project to dictionary (always costed)"""
        from app.services.cost_service import project_cost_summary

        # Eager-load components: every BOM line reads its component's price,
        # so the list view would otherwise fire a query per line per project.
        lines = self.bom.options(joinedload(ProjectComponent.component)).all()
        line_dicts = [line.to_dict() for line in lines]

        data = {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'description': self.description,
            'repo_url': self.repo_url,
            'tags': [t.to_dict() for t in self.tags],
            'bom_count': len(lines),
            'file_count': self.files.count(),
            'cost': project_cost_summary(line_dicts),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_detail:
            data['readme_md'] = self.readme_md
            data['bom'] = line_dicts
            data['files'] = [f.to_dict() for f in self.files]
        return data


class ProjectComponent(db.Model):
    """BOM line: a component used by a project"""
    __tablename__ = 'project_component'
    __table_args__ = (
        db.UniqueConstraint('project_id', 'component_id', name='uq_project_component'),
    )

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    component_id = db.Column(db.Integer, db.ForeignKey('component.id'), nullable=False, index=True)
    qty_planned = db.Column(db.Integer, nullable=False, default=1)
    qty_used = db.Column(db.Integer, nullable=False, default=0)
    note = db.Column(db.String(300), nullable=True)
    # Per-project estimate override: bulk pricing for one build should not
    # rewrite the catalog estimate every other project reads.
    est_unit_cost = db.Column(db.Numeric(10, 4), nullable=True)

    # Relationships
    component = db.relationship('Component', backref=db.backref('project_links', lazy='dynamic'))

    def __repr__(self):
        return f'<ProjectComponent project {self.project_id} component {self.component_id}>'

    def to_dict(self):
        """Convert BOM line to dictionary with availability and cost info"""
        from app.services.cost_service import line_costs

        available = self.component.qty_on_hand if self.component else 0
        remaining = max((self.qty_planned or 0) - (self.qty_used or 0), 0)
        return {
            'id': self.id,
            'project_id': self.project_id,
            'component': self.component.to_summary() if self.component else None,
            'qty_planned': self.qty_planned,
            'qty_used': self.qty_used,
            'note': self.note,
            'available': available,
            'short': available < remaining,
            **line_costs(self),
        }


class ProjectFile(db.Model):
    """File attached to a project (image / pdf / schematic / firmware / model3d / other)"""
    __tablename__ = 'project_file'

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False, default='other')  # one of PROJECT_FILE_KINDS
    filename = db.Column(db.String(255), nullable=False)  # original filename
    file_path = db.Column(db.String(500), nullable=False)  # relative path under uploads/
    mime_type = db.Column(db.String(100), nullable=True)
    size = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<ProjectFile {self.filename} ({self.kind})>'

    def to_dict(self):
        """Convert project file to dictionary"""
        return {
            'id': self.id,
            'project_id': self.project_id,
            'kind': self.kind,
            'filename': self.filename,
            'file_path': self.file_path,
            'url': f'/uploads/{self.file_path}',
            'mime_type': self.mime_type,
            'size': self.size,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
