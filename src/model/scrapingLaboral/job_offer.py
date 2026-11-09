from utils.db import db, ma
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



class JobOffer(db.Model):
    __tablename__ = 'job_offer'
    id = db.Column(db.String(36), primary_key=True)
    source = db.Column(db.String(20), nullable=False)
    external_id = db.Column(db.String(100), nullable=True)
    url = db.Column(db.String(500), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    company = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(255), nullable=False)
    remote_type = db.Column(db.String(50), nullable=False)
    posted_at = db.Column(db.DateTime, nullable=True)
    description_text = db.Column(db.Text, nullable=True)
    salary_text = db.Column(db.String(100), nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    contact_name = db.Column(db.String(255), nullable=True)
    raw_json = db.Column(db.JSON, nullable=False)
    hash_dedupe = db.Column(db.String(255), unique=True, nullable=False)

    def __init__(self, source, url, title, company, location, remote_type, raw_json, hash_dedupe, external_id=None, posted_at=None, description_text=None, salary_text=None, contact_email=None, contact_name=None):
        self.source = source
        self.external_id = external_id
        self.url = url
        self.title = title
        self.company = company
        self.location = location
        self.remote_type = remote_type
        self.posted_at = posted_at
        self.description_text = description_text
        self.salary_text = salary_text
        self.contact_email = contact_email
        self.contact_name = contact_name
        self.raw_json = raw_json
        self.hash_dedupe = hash_dedupe

    def __repr__(self):
        return f"JobOffer(id={self.id}, source={self.source}, title={self.title}, company={self.company}, location={self.location})"

    @classmethod
    def crear_tabla_job_offer(cls):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        if not insp.has_table("job_offer"):
            db.create_all()

class JobOfferSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobOffer
        load_instance = True
        sqla_session = db.session

job_offer_schema = JobOfferSchema()