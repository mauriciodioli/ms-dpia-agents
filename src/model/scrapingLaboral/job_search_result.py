from utils.db import db, ma
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



class JobSearchResult(db.Model):
    __tablename__ = 'job_search_result'
    id = db.Column(db.String(36), primary_key=True)
    job_search_id = db.Column(db.String(36), nullable=False)
    job_offer_id = db.Column(db.String(36), nullable=False)
    match_score = db.Column(db.Integer, nullable=False)
    match_reasons_json = db.Column(db.JSON, nullable=False)
    rank = db.Column(db.Integer, nullable=False)

    def __init__(self, job_search_id, job_offer_id, match_score, match_reasons_json, rank):
        self.job_search_id = job_search_id
        self.job_offer_id = job_offer_id
        self.match_score = match_score
        self.match_reasons_json = match_reasons_json
        self.rank = rank

    def __repr__(self):
        return f"JobSearchResult(id={self.id}, job_search_id={self.job_search_id}, job_offer_id={self.job_offer_id}, match_score={self.match_score}, rank={self.rank})"

    @classmethod
    def crear_tabla_job_search_result(cls):
        from sqlalchemy import inspect
        insp = inspect(db.engine)
        if not insp.has_table("job_search_result"):
            db.create_all()

class JobSearchResultSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = JobSearchResult
        load_instance = True
        sqla_session = db.session

job_search_result_schema = JobSearchResultSchema()