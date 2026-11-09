"""Append-only event model for agente_laboral."""

from marshmallow_sqlalchemy import SQLAlchemyAutoSchema

from utils.db import db, ma





class AgenteLaboralEvent(db.Model):
	__tablename__ = "agente_laboral_event"

	id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
	event_type = db.Column(db.String(64), nullable=False, index=True)
	user_id = db.Column(db.BigInteger, nullable=False, index=True)
	conversation_id = db.Column(db.BigInteger, nullable=False, index=True)
	scope_id = db.Column(db.BigInteger, nullable=False, index=True)
	opportunity_id = db.Column(db.String(120), nullable=True, index=True)
	publicacion_id = db.Column(db.BigInteger, nullable=True, index=True)
	ambito_id = db.Column(db.BigInteger, nullable=True, index=True)
	categoria_id = db.Column(db.BigInteger, nullable=True, index=True)
	event_value = db.Column(db.Float, nullable=False, default=1)
	metadata_json = db.Column(db.JSON, nullable=False, default=dict)
	created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), index=True)

	__table_args__ = (
		db.Index("ix_agente_laboral_event_user_created", "user_id", "created_at"),
		db.Index("ix_agente_laboral_event_scope_created", "scope_id", "created_at"),
		db.Index("ix_agente_laboral_event_type_created", "event_type", "created_at"),
	)

	def __repr__(self):
		return (
			"AgenteLaboralEvent("
			f"id={self.id}, event_type={self.event_type}, user_id={self.user_id}, "
			f"conversation_id={self.conversation_id}, scope_id={self.scope_id}, "
			f"opportunity_id={self.opportunity_id}, publicacion_id={self.publicacion_id})"
		)


class AgenteLaboralEventSchema(SQLAlchemyAutoSchema):
	class Meta:
		model = AgenteLaboralEvent
		load_instance = True
		sqla_session = db.session


agente_laboral_event_schema = AgenteLaboralEventSchema()
agente_laboral_events_schema = AgenteLaboralEventSchema(many=True)
