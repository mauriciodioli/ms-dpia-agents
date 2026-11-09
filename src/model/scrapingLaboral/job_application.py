from utils.db import db, ma
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



class JobApplication(db.Model):
    __tablename__ = 'job_application'
    id = db.Column(db.String(36), primary_key=True)
    job_offer_id = db.Column(db.String(36), nullable=False)
    user_id = db.Column(db.String(36), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=True)
    send_to = db.Column(db.String(255), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    def __init__(self, job_offer_id, user_id, status, sent_at=None, send_to=None, notes=None):
        self.job_offer_id = job_offer_id
        self.user_id = user_id
        self.status = status
        self.sent_at = sent_at
        self.send_to = send_to
        self.notes = notes

    def __repr__(self):
        return f"JobApplication(id={self.id}, job_offer_id={self.job_offer_id}, user_id={self.user_id}, status={self.status})"

    @classmethod
    def crear_tabla_job_application(cls):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        if not insp.has_table("job_application"):
            db.create_all()

class JobApplicationSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobApplication
        load_instance = True
        sqla_session = db.session

job_application_schema = JobApplicationSchema()