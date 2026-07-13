from datetime import datetime
from app import db


# Association table for many-to-many relationship between components and tags
component_tags = db.Table(
    'component_tags',
    db.Column('component_id', db.Integer, db.ForeignKey('component.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True)
)

# Association table for many-to-many relationship between projects and tags
project_tags = db.Table(
    'project_tags',
    db.Column('project_id', db.Integer, db.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id', ondelete='CASCADE'), primary_key=True)
)


class Tag(db.Model):
    """Tag model for categorizing components and projects"""
    __tablename__ = 'tag'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True, index=True)
    color = db.Column(db.String(7), nullable=False, default='#8ab4f8')  # Hex color code

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Foreign keys
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    # Relationships
    components = db.relationship(
        'Component',
        secondary=component_tags,
        backref=db.backref('tags', lazy='dynamic'),
        lazy='dynamic'
    )
    projects = db.relationship(
        'Project',
        secondary=project_tags,
        backref=db.backref('tags', lazy='dynamic'),
        lazy='dynamic'
    )

    def __repr__(self):
        return f'<Tag {self.name}>'

    @staticmethod
    def get_or_create(name, user_id=None):
        """Fetch a tag by name, creating it if it does not exist (no commit)"""
        name = name.strip()
        tag = Tag.query.filter(db.func.lower(Tag.name) == name.lower()).first()
        if not tag:
            tag = Tag(name=name, user_id=user_id)
            db.session.add(tag)
            db.session.flush()
        return tag

    def to_dict(self):
        """Convert tag to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'user_id': self.user_id,
            'component_count': self.components.count(),
            'project_count': self.projects.count(),
        }
