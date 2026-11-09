from utils.db import db, ma
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



class CVProfile(db.Model):
    __tablename__ = 'cv_profile'
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.String(36), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    source_type = db.Column(db.String(20), nullable=False)
    cv_text = db.Column(db.Text, nullable=False)
    cv_json = db.Column(db.JSON, nullable=False)

    def __init__(self, user_id, created_at, source_type, cv_text, cv_json, id=None):
        if id:
            self.id = id
        self.user_id = user_id
        self.created_at = created_at
        self.source_type = source_type
        self.cv_text = cv_text
        self.cv_json = cv_json

    def __repr__(self):
        return f"CVProfile(id={self.id}, user_id={self.user_id}, created_at={self.created_at}, source_type={self.source_type})"

    @classmethod
    def crear_tabla_cv_profile(cls):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        if not insp.has_table("cv_profile"):
            db.create_all()

class CVProfileSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = CVProfile
        load_instance = True
        sqla_session = db.session

cv_profile_schema = CVProfileSchema()