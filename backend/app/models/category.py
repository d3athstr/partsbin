from app import db


class Category(db.Model):
    """Fixed component category list, seeded via `flask seed`"""
    __tablename__ = 'category'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f'<Category {self.name}>'

    def to_dict(self):
        """Convert category to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'position': self.position,
        }
