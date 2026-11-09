from utils.db import db

class RankingUser(db.Model):
    __tablename__ = "ranking_user"

    id = db.Column(db.BigInteger, primary_key=True)
    scope_id = db.Column(db.BigInteger, db.ForeignKey("chat_scope.id"), nullable=False)
    user_id = db.Column(db.BigInteger)   # cliente logueado, o null
    client_hash = db.Column(db.String(64))  # para anónimos (opcional)

    question_score = db.Column(db.Float, default=0.0)
    answer_score = db.Column(db.Float, default=0.0)
    behavior_score = db.Column(db.Float, default=0.0)
    emotional_tone = db.Column(db.String(24))

    breakdown_json = db.Column(db.JSON)  # contadores por etiqueta
    last_decay_at = db.Column(db.DateTime)
    updated_at = db.Column(
        db.DateTime, server_default=db.func.now(), onupdate=db.func.now()
    )
