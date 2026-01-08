from app.extensions import db
from .utils import TimestampMixin

# Association Table for Many-to-Many relationship between User and Group
group_members = db.Table('group_members',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('groups.id'), primary_key=True),
    db.Column('joined_at', db.DateTime, default=db.func.now())
)

class Group(TimestampMixin, db.Model):
    __tablename__ = 'groups'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    description = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships
    # 'members' relationship will be defined in User model as 'groups' backref or similar, 
    # but usually we define the backref here or there. 
    # Let's define it here for clarity if possible, but SQLAlchemy often handles m2m easier from one side.
    # We will define the relationship in User to keep User as the central point or here.
    # Let's add 'members' here.
    members = db.relationship('User', 
                              secondary=group_members, 
                              backref=db.backref('groups', lazy='dynamic'),
                              lazy='dynamic')

    def __repr__(self):
        return f'<Group {self.name}>'
