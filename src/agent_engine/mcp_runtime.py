"""Trusted generic MCP handler. Tool discovery never installs executable code."""
import json
import time
from uuid import uuid4
from .mcp_catalog import require_tool
from .mcp_repository import MCPRepository
from .mcp_service import MCPService
from .mcp_transport import MCPClient
from .auth import now_utc
from .contracts import RESULT, validate, iso
from .errors import EngineError
from . import mcp_models as mm
from . import models as m


class MCPHandler:
    def __init__(self,engine,config,*,client_factory=MCPClient):
        self.service=MCPService(engine,config,client_factory=client_factory)
        self.engine,self.config,self.client_factory=engine,config,client_factory

    def __call__(self,context,parameters):
        lease=context.lease
        with self.engine.begin() as conn:
            job,task=context.box._owned(conn,lease)
            expected=job['configuration_snapshot'].get('mcp_tools',{}).get(lease.tool_id)
            if not expected:raise EngineError('mcp_catalog_changed',409)
            server,tool,_=require_tool(conn,lease.owner_id,job['agent_id'],lease.tool_id,expected)
            server,tool=dict(server),dict(tool)
            remaining=(job['deadline_at']-context.box.now()).total_seconds() if job['deadline_at'] else server['timeout_seconds']
            if remaining<server['timeout_seconds']:raise EngineError('provider_deadline_insufficient',409)
        secret=self.service.credential(server)
        started=time.monotonic();execution_id=str(uuid4());submitted=False
        def before_call():
            nonlocal submitted
            # Linearization point shared with revocation; initialization cannot invoke tools.
            context.mark_submitting()
            with self.engine.begin() as conn:
                context.box._owned(conn,lease)
                require_tool(conn,lease.owner_id,job['agent_id'],lease.tool_id,expected)
                MCPRepository(conn).insert(mm.executions,dict(id=execution_id,owner_id=lease.owner_id,
                    agent_id=job['agent_id'],job_id=lease.job_id,tool_id=tool['id'],server_revision=server['revision'],
                    status='STARTED',started_at=now_utc()))
            submitted=True
        try:
            result=self.client_factory(server,secret).initialize().call(tool['tool_name'],parameters,before_call=before_call)
            texts=[entry.get('text','') for entry in result['content'] if isinstance(entry,dict) and entry.get('type')=='text' and isinstance(entry.get('text'),str)]
            if 'structuredContent' in result:texts.append(json.dumps(result['structuredContent'],ensure_ascii=False))
            from .provider_handlers import clean_text
            value=secret['value'] if isinstance(secret,dict) else secret or '\x00'
            summary=clean_text('\n'.join(texts),value,20000) or 'La herramienta MCP devolvió contenido sin representación textual.'
            output=dict(schema_version='agents.result.v1',summary=summary,findings=[],sources=[],
                        warnings=['Respuesta de una herramienta MCP autorizada; costos no informados por el proveedor.'])
            from .result_presentation import present_result, text_records
            structured=None
            if 'structuredContent' in result:
                try:structured=json.loads(clean_text(json.dumps(result['structuredContent'],ensure_ascii=False),value,200000))
                except (ValueError,TypeError):pass
            if not structured:structured=text_records(clean_text('\n'.join(texts),value,200000) or '')
            output=present_result(output,structured,retrieved_at=iso(now_utc()))
            validate(RESULT,output)
            context.mark_submitted(execution_id)
            with self.engine.begin() as conn:
                context.box._owned(conn,lease);repo=MCPRepository(conn)
                repo.execution(execution_id,status='SUCCEEDED',duration_ms=int((time.monotonic()-started)*1000),finished_at=now_utc())
                repo.insert(m.usage,dict(id=str(uuid4()),owner_id=lease.owner_id,job_id=lease.job_id,provider_id='mcp',
                    provider_record_id=execution_id,verified=True,evidence_source='PROVIDER_RESPONSE',calls=1,created_at=now_utc()))
            return output
        except Exception as exc:
            if submitted:
                with self.engine.begin() as conn:
                    repo=MCPRepository(conn)
                    repo.execution(execution_id,status='TIMED_OUT' if isinstance(exc,EngineError) and exc.code=='mcp_timeout' else 'FAILED',
                        duration_ms=int((time.monotonic()-started)*1000),error_code=exc.code if isinstance(exc,EngineError) else 'mcp_execution_failed',finished_at=now_utc())
                    repo.insert(m.usage,dict(id=str(uuid4()),owner_id=lease.owner_id,job_id=lease.job_id,provider_id='mcp',
                        provider_record_id=execution_id,verified=False,evidence_source='SUBMISSION_UNCERTAIN',calls=1,created_at=now_utc()))
            if isinstance(exc,EngineError):raise
            raise EngineError('mcp_execution_failed',502) from None
