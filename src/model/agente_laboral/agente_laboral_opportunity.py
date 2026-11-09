"""Normalized opportunity payload model for agente_laboral."""

from dataclasses import asdict, dataclass, field


@dataclass
class AgenteLaboralOpportunity:
	id: str
	slug: str
	title: str
	company_name: str
	source_name: str | None
	source_url: str | None
	location_label: str
	country: str
	city: str
	postal_code: str | None
	ambito_id: int | None
	categoria_id: int | None
	language_code: str
	posted_at: str | None
	summary: str
	description: str
	action_label: str = "Execute"
	status: str = "available"
	is_mock: bool = True
	relevance: dict = field(default_factory=dict)

	def to_card(self):
		payload = asdict(self)
		payload.pop("description", None)
		return payload

	def to_detail(self):
		payload = asdict(self)
		payload.pop("relevance", None)
		return payload
