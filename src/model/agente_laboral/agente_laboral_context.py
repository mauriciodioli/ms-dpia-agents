"""Canonical normalized context payload for agente_laboral."""

from dataclasses import asdict, dataclass, field


@dataclass
class AgenteLaboralContext:
	user_id: int
	conversation_id: int
	scope_id: int
	ambito_id: int | None = None
	categoria_id: int | None = None
	publicacion_id: int | None = None
	postal_code: str | None = None
	country: str | None = None
	city: str | None = None
	locale: str = "es"
	source_summary: dict = field(default_factory=dict)

	def to_dict(self):
		return asdict(self)
