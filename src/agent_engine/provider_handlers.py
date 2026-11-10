"""Real, explicitly installed handlers for the existing Worker/TaskBox runtime.

One externally billable POST per task. Uncertain submissions are never retried
by this module; TaskBox retains them as BLOCKED_UNCERTAIN for reconciliation.
"""
import json
import re
from urllib.parse import urlsplit, parse_qs
from uuid import UUID, uuid4
from sqlalchemy import select, insert, func
from . import models as m
from .contracts import RESULT, validate, iso
from .errors import EngineError
from .integrations import IntegrationService, require_enabled
from .provider_transport import OPENAI_BASE
from .worker import Handler, HandlerRegistry

COUNTRIES = {'Argentina': 'argentina', 'Italia': 'italia', 'España': 'espana',
             'Polonia': 'polonia', 'México': 'mexico', 'Uruguay': 'uruguay'}


def clean_text(value, secret, limit=2000):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = str(value).replace(secret, '[REDACTADO]')
    text = re.sub(r'(?i)(?:bearer\s+\S+|(?:sk-|dpia_|dpa_)[A-Za-z0-9_.-]{8,})', '[REDACTADO]', text)
    text = re.sub(r'(?i)([?&](?:token|api_key|access_token|password|secret)=)[^&\s]+', r'\1[REDACTADO]', text)
    return text[:limit]


def safe_url(value, secret):
    if not isinstance(value, str) or len(value) > 2000 or secret in value:
        return None
    try:
        u = urlsplit(value)
        if (u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or
                any(k.lower() in ('token', 'api_key', 'access_token', 'password', 'secret') for k in parse_qs(u.query))):
            return None
        return value
    except ValueError:
        return None


def normalize_scraper(data, secret, country, at, max_products):
    if data.get('success') is not True or data.get('marketplace') != 'amazon' or not isinstance(data.get('datos'), list):
        raise EngineError('provider_invalid_response', 502)
    try:
        reference = str(UUID(data['trabajo_id']))
        if reference != data['trabajo_id']:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise EngineError('provider_invalid_response', 502) from None
    findings, sources, partial = [], [], False
    for batch in data['datos']:
        if not isinstance(batch, dict):
            raise EngineError('provider_invalid_response', 502)
        partial = partial or bool(batch.get('error'))
        items = batch.get('items', [])
        if not isinstance(items, list):
            raise EngineError('provider_invalid_response', 502)
        for product in items:
            if not isinstance(product, dict) or not isinstance(product.get('titulo'), str) or not product['titulo'].strip():
                partial = True
                continue
            if len(findings) >= max_products:
                break
            title = clean_text(product['titulo'], secret, 1000)
            url, image = safe_url(product.get('url'), secret), safe_url(product.get('imagen'), secret)
            record = {'marketplace': 'amazon', 'country': country, 'title': title,
                      'provider_job_id': reference, 'retrieved_at': at}
            for key in ('precio', 'moneda', 'asin', 'rating', 'reviews'):
                value = clean_text(product.get(key), secret, 200)
                if value is not None:
                    record[key] = value
            if image:
                record['image_url'] = image
            refs = []
            if url:
                source_id = 'product-' + str(len(sources) + 1)
                sources.append(dict(id=source_id, url=url, title=title, retrieved_at=at))
                record['url'] = url
                refs.append(source_id)
            findings.append({'text': json.dumps(record, ensure_ascii=False, allow_nan=False), 'source_ids': refs})
    warnings = ['Datos recibidos de DPIA Scraper; requieren verificación independiente y aprobación.']
    if partial or data.get('estado') in ('parcial', 'fallido'):
        warnings.append('El proveedor informó errores parciales; no se reintenta el scraping automáticamente.')
    if not findings:
        warnings.append('Sin productos válidos; el éxito HTTP no confirma evidencia comercial.')
    output = dict(schema_version='agents.result.v1', summary=f'Amazon: {len(findings)} productos recibidos. Trabajo externo: {reference}.',
                  findings=findings, sources=sources, warnings=warnings)
    validate(RESULT, output)
    return reference, output


class ProviderHandlers:
    def __init__(self, service):
        self.service = service

    def prepare(self, context, provider):
        context.heartbeat()
        with context.box.engine.begin() as conn:
            job, task = context.box._owned(conn, context.lease)
            spec = context.box.authorized(conn, job, task)
            require_enabled(conn, spec.provider)
            row = self.service.row(conn, provider, lock=True)
            self.service.valid_config(provider, row['config'])
            seconds = (job['deadline_at'] - context.box.now()).total_seconds() if job['deadline_at'] else 0
            if seconds < row['config']['timeout_seconds'] + 5:
                raise EngineError('provider_deadline_insufficient', 409)
            used = conn.execute(select(func.coalesce(func.sum(m.usage.c.output_tokens), 0)).where(
                m.usage.c.owner_id == job['owner_id'], m.usage.c.job_id == job['id'],
                m.usage.c.verified.is_(True))).scalar_one()
            remaining = job['request_snapshot']['limits']['max_output_tokens'] - used
            return row, self.service.decrypt(row), remaining, {
                'agent_instructions': job['configuration_snapshot'].get('instructions', ''),
                'request_instructions': job['request_snapshot'].get('instructions', '')}

    def record_usage(self, context, provider, reference, *, input_tokens=None, output_tokens=None):
        with context.box.engine.begin() as conn:
            context.box._owned(conn, context.lease)
            conn.execute(insert(m.usage).values(id=str(uuid4()), owner_id=context.lease.owner_id,
                job_id=context.lease.job_id, provider_id=provider, provider_record_id=reference,
                verified=True, evidence_source='PROVIDER_RESPONSE', calls=1,
                input_tokens=input_tokens, output_tokens=output_tokens, created_at=context.box.now()))

    def scraper(self, context, parameters):
        row, secret, _, _ = self.prepare(context, 'dpia-scraper')
        country = COUNTRIES[parameters['country']]
        if country not in row['diagnostic'].get('marketplaces', {}).get('amazon', []):
            raise EngineError('marketplace_country_unavailable', 409)
        # The external endpoint documents a maximum of 10 Amazon products, but
        # no monetary budget field. Never fabricate a cost limit in its payload.
        payload = {'marketplace': 'amazon', 'pais_defecto': country, 'batch_size': 1,
                   'registros': [{'Producto': parameters['query'], 'País': country}],
                   'idempotency_key': 'agents:' + context.lease.task_id}
        context.mark_submitting(row['revision'])
        data = self.service.http.request('POST', row['config']['base_url'] + '/base44/scraping', secret,
            timeout=row['config']['timeout_seconds'], body=payload)
        try:
            reference = str(UUID(data['trabajo_id']))
            if reference != data['trabajo_id']:
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise EngineError('provider_invalid_response', 502) from None
        context.mark_submitted(reference)  # Preserve the external ID even if normalization fails.
        reference, output = normalize_scraper(data, secret, country, iso(self.service.clock()), parameters.get('max_products', 10))
        self.record_usage(context, 'dpia.scraper', reference)
        return output

    def analysis(self, context, parameters):
        row, secret, remaining, instructions = self.prepare(context, 'openai')
        budget = min(row['config']['max_output_tokens'], remaining)
        if budget < 16:
            raise EngineError('output_token_budget_exceeded', 409)
        inputs = json.dumps({'request': instructions['request_instructions'], 'previous_results': context.previous_outputs}, ensure_ascii=False)
        if len(inputs.encode('utf-8')) > 24000:
            raise EngineError('analysis_input_limit', 409)
        body = {'model': row['config']['model'], 'store': False,
                'instructions': 'Analizá solo los datos suministrados. No inventes fuentes, precios ni verificaciones. ' +
                    instructions['agent_instructions'] + '\n' + parameters.get('instructions', ''),
                'input': inputs, 'max_output_tokens': budget}
        context.mark_submitting(row['revision'])
        data = self.service.http.request('POST', OPENAI_BASE + '/responses', secret,
            timeout=row['config']['timeout_seconds'], body=body)
        reference = data.get('id')
        if not isinstance(reference, str) or not re.fullmatch(r'resp_[A-Za-z0-9_-]{1,150}', reference) or secret in reference:
            raise EngineError('provider_invalid_response', 502)
        context.mark_submitted(reference)
        usage = data.get('usage')
        if not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('input_tokens', 'output_tokens')):
            raise EngineError('provider_invalid_response', 502)
        self.record_usage(context, 'openai.responses', reference, input_tokens=usage['input_tokens'], output_tokens=usage['output_tokens'])
        if data.get('status') != 'completed' or not isinstance(data.get('output'), list):
            raise EngineError('provider_incomplete_response', 502)
        texts = []
        for item in data['output']:
            if isinstance(item, dict) and item.get('type') == 'message' and isinstance(item.get('content'), list):
                for content in item['content']:
                    if isinstance(content, dict) and content.get('type') == 'output_text' and isinstance(content.get('text'), str):
                        texts.append(content['text'])
        if not texts:
            raise EngineError('provider_invalid_response', 502)
        sources, seen = [], set()
        for previous in context.previous_outputs:
            for source in previous.get('sources', []):
                if source['id'] not in seen and len(sources) < 100:
                    sources.append(source)
                    seen.add(source['id'])
        output = dict(schema_version='agents.result.v1', summary=clean_text('\n'.join(texts), secret, 20000),
            findings=[], sources=sources,
            warnings=['Análisis generado por IA; no implica verificación ni aprobación de los datos.'])
        validate(RESULT, output)
        return output


def provider_handlers(engine, config, *, http=None):
    implementations = ProviderHandlers(IntegrationService(engine, config, http=http))
    registry = HandlerRegistry()
    registry.register('dpia.amazon.search', Handler(implementations.scraper, RESULT))
    registry.register('openai.analysis', Handler(implementations.analysis, RESULT))
    return registry
