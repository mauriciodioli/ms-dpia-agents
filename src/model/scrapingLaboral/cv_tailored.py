from utils.db import db, ma
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



class CVTailored(db.Model):
    __tablename__ = 'cv_tailored'
    id = db.Column(db.String(36), primary_key=True)
    job_offer_id = db.Column(db.String(36), nullable=False)
    cv_profile_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    tailored_text = db.Column(db.Text, nullable=False)
    tailored_pdf_url = db.Column(db.String(255), nullable=True)
    diff_json = db.Column(db.JSON, nullable=False)

    def __init__(self, job_offer_id, cv_profile_id, created_at, tailored_text, diff_json, tailored_pdf_url=None):
        self.job_offer_id = job_offer_id
        self.cv_profile_id = cv_profile_id
        self.created_at = created_at
        self.tailored_text = tailored_text
        self.tailored_pdf_url = tailored_pdf_url
        self.diff_json = diff_json

    def __repr__(self):
        return f"CVTailored(id={self.id}, job_offer_id={self.job_offer_id}, cv_profile_id={self.cv_profile_id}, created_at={self.created_at})"

    @classmethod
    def crear_tabla_cv_tailored(cls):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        if not insp.has_table("cv_tailored"):
            db.create_all()

class CVTailoredSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = CVTailored
        load_instance = True
        sqla_session = db.session

cv_tailored_schema = CVTailoredSchema()