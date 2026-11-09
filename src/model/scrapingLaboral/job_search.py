from utils.db import db, ma
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



class JobSearch(db.Model):
    __tablename__ = 'job_search'
    id = db.Column(db.String(36), primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.String(36), nullable=False)
    ambito_id = db.Column(db.String(36), nullable=False)
    publicacion_id = db.Column(db.String(36), nullable=True)
    conversacion_id = db.Column(db.String(36), nullable=False)
    mensaje_id = db.Column(db.String(36), nullable=False)
    zipcode = db.Column(db.String(20), nullable=False)
    location_text = db.Column(db.String(255), nullable=False)
    keywords = db.Column(db.Text, nullable=False)
    remote_pref = db.Column(db.String(50), nullable=False)
    sources_json = db.Column(db.JSON, nullable=False)
    apify_run_id = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False)
    error_msg = db.Column(db.Text, nullable=True)

    def __init__(self, created_at, user_id, ambito_id, conversacion_id, mensaje_id, zipcode, location_text, keywords, remote_pref, sources_json, status, publicacion_id=None, apify_run_id=None, error_msg=None, id=None):
        if id:
            self.id = id
        self.created_at = created_at
        self.user_id = user_id
        self.ambito_id = ambito_id
        self.publicacion_id = publicacion_id
        self.conversacion_id = conversacion_id
        self.mensaje_id = mensaje_id
        self.zipcode = zipcode
        self.location_text = location_text
        self.keywords = keywords
        self.remote_pref = remote_pref
        self.sources_json = sources_json
        self.apify_run_id = apify_run_id
        self.status = status
        self.error_msg = error_msg

    def __repr__(self):
        return f"JobSearch(id={self.id}, user_id={self.user_id}, created_at={self.created_at}, status={self.status})"

    @classmethod
    def crear_tabla_job_search(cls):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        if not insp.has_table("job_search"):
            db.create_all()

class JobSearchSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobSearch
        load_instance = True
        sqla_session = db.session

job_search_schema = JobSearchSchema()