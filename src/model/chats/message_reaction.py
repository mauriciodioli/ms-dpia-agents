# models/chats/message_reaction.py
from utils.db import db
from datetime import datetime


class MessageReaction(db.Model):
    __tablename__ = "message_reaction"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    message_id = db.Column(
        db.BigInteger,
        db.ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    emoji = db.Column(db.String(10), nullable=False)  # emoji unicode
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Restricción única: un usuario solo puede tener una reacción por emoji en cada mensaje
    __table_args__ = (
        db.UniqueConstraint('message_id', 'user_id', 'emoji', name='uq_msg_user_emoji'),
    )

    # Relaciones
    message = db.relationship("Message", backref="reactions")
    user = db.relationship("Usuario", backref="message_reactions")

    def to_dict(self):
        return {
            'id': self.id,
            'message_id': self.message_id,
            'user_id': self.user_id,
            'emoji': self.emoji,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
