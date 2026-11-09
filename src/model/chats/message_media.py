from utils.db import db


class MessageMedia(db.Model):
    __tablename__ = "message_media"  # snake_case para la tabla

    id = db.Column(db.BigInteger, primary_key=True)

    message_id = db.Column(
        db.BigInteger,
        db.ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    media_type = db.Column(db.String(20), nullable=False)   # image|audio|video|file
    url        = db.Column(db.String(500), nullable=False)  # dónde quedó guardado
    mime_type  = db.Column(db.String(100), nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)      # audio/video
    metadata_json = db.Column(db.Text, nullable=True)       # dimensiones, etc.

    created_at = db.Column(db.DateTime, server_default=db.func.now())
