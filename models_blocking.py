# Additional models for blocking functionality
from models import db
from datetime import datetime

class BlockedUser(db.Model):
    __tablename__ = 'blocked_users'
    
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    blocker = db.relationship('Users', foreign_keys=[blocker_id], backref='blocked_users')
    blocked = db.relationship('Users', foreign_keys=[blocked_id], backref='blocked_by')
    
    # Ensure unique blocking relationships
    __table_args__ = (
        db.UniqueConstraint('blocker_id', 'blocked_id', name='unique_block'),
        db.CheckConstraint('blocker_id != blocked_id', name='no_self_block'),
    )
    
    def __repr__(self):
        return f"<BlockedUser {self.blocker_id} blocked {self.blocked_id}>"


class UserActivity(db.Model):
    __tablename__ = 'user_activity'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    current_status = db.Column(db.String(50), default='available')  # 'available', 'away', 'busy', 'offline'
    status_message = db.Column(db.String(255), nullable=True)
    
    # Relationship
    user = db.relationship('Users', backref=db.backref('activity', uselist=False))
    
    def __repr__(self):
        return f"<UserActivity {self.user_id}: {self.current_status}>"
