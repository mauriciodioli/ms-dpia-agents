from utils.db import db

class DecisionLog(db.Model):
    __tablename__ = "decision_log"

    id = db.Column(db.BigInteger, primary_key=True)
    conversation_id = db.Column(db.BigInteger, db.ForeignKey("conversation.id"))
    message_id = db.Column(db.BigInteger, db.ForeignKey("message.id"))

    decision = db.Column(db.String(32))     # ia_auto|copilot|manual|a_ver|to_wa|investigate
    reason = db.Column(db.String(255))
    payload_json = db.Column(db.JSON)       # scores, reglas, etc.

    created_at = db.Column(db.DateTime, server_default=db.func.now())
