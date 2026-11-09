(() => {
  'use strict';
  const root = document.querySelector('#content'),
    base = '/api/agents/v1';
  let context, abort, version = 0,
    toastTimer;
  const titles = {
    '/': 'Inicio',
    '/agents': 'Mis agentes',
    '/schedules': 'Programaciones',
    '/executions': 'Ejecuciones',
    '/integrations': 'Integraciones',
    '/administration': 'Administración'
  };
  const states = {
    ENABLED: 'Habilitado',
    DISABLED: 'Deshabilitado',
    IDLE: 'Sin actividad',
    WAITING: 'En espera',
    WORKING: 'Trabajando',
    CREATED: 'Creada',
    SCHEDULED: 'Programada',
    QUEUED: 'En cola',
    RUNNING: 'En ejecución',
    REVIEWING: 'En revisión',
    CORRECTION_REQUIRED: 'Requiere corrección',
    APPROVED: 'Aprobada',
    READY_FOR_DELIVERY: 'Lista para entrega',
    DELIVERED: 'Entregada',
    FAILED: 'Fallida',
    CANCELLED: 'Cancelada',
    AVAILABLE: 'Disponible',
    BUSY: 'Ocupado',
    DISCONNECTED: 'Desconectado'
  };
  const names = {
    'openai.analysis': 'Análisis con OpenAI',
    'dpia.amazon.search': 'Búsqueda de productos',
    'dpia.test.echo': 'Prueba interna (sin APIs)'
  };
  const errors = {
    revision_conflict: 'La configuración cambió en otra sesión. Recargá el agente antes de guardar.',
    invalid_contract: 'Revisá los campos y los límites de la configuración.',
    invalid_timezone: 'Ingresá una zona horaria IANA válida.',
    agent_not_found: 'El agente no existe o no tenés acceso.',
    engine_storage_unavailable: 'El almacenamiento no está disponible. Reintentá en unos momentos.',
    result_not_delivered: 'El resultado todavía no está aprobado y entregado.'
  };
  const node = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  };

  function btn(text, fn, cls = 'secondary') {
    const b = node('button', text, cls);
    b.type = 'button';
    b.onclick = fn;
    return b;
  }

  function link(text, path, cls = 'primary') {
    const a = node('a', text, cls);
    a.href = path;
    a.dataset.nav = '';
    return a;
  }

  function badge(value) {
    return node('span', states[value] || value, 'badge' + (['ENABLED', 'DELIVERED'].includes(value) ?
      ' active' : ''));
  }

  function pending() {
    return node('span', 'Pendiente', 'badge pending');
  }

  function icon(kind = 'agent', className = '') {
    const wrap = node('span', undefined, className),
      svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none');
    svg.setAttribute('stroke', 'currentColor');
    svg.setAttribute('stroke-width', '1.6');
    svg.setAttribute('aria-hidden', 'true');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', kind === 'integration' ? 'M8 3v4m8-4v4M6 7h12v4a6 6 0 0 1-12 0V7Zm6 10v4' :
      'M8 3h8l5 9-5 9H8l-5-9 5-9Zm0 0 4 9 4-9M3 12h18M8 21l4-9 4 9');
    svg.append(path);
    wrap.append(svg);
    return wrap;
  }

  function notify(text) {
    const n = document.querySelector('#notice');
    n.textContent = text;
    n.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => n.hidden = true, 6000);
  }
  async function request(path, options = {}) {
    const r = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body ? {
          'Content-Type': 'application/json',
          'X-DPIA-Action': 'manage-agents'
        } : {}),
        ...options.headers
      }
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const e = new Error(errors[data.error] || (r.status === 403 ?
        'No tenés permisos para esta acción.' : 'No se pudo completar la solicitud. Reintentá.'));
      e.status = r.status;
      throw e;
    }
    return data;
  }
  const api = (path, options = {}) => request(base + path, {
    signal: abort.signal,
    ...options
  });

  function heading(title, subtitle, action) {
    const row = node('div', undefined, 'section-head'),
      copy = node('div');
    copy.append(node('p', 'DPIA AGENTS', 'eyebrow'), node('h1', title), node('p', subtitle, 'subheading'));
    row.append(copy);
    if (action) row.append(action);
    root.append(row);
  }

  function empty(host, title, description, action) {
    const box = node('div', undefined, 'empty');
    box.append(icon('agent', 'empty-icon'), node('h3', title), node('p', description));
    if (action) box.append(action);
    host.append(box);
  }
  const banner = text => node('p', text, 'banner');

  function table(host, headers, rows) {
    const wrap = node('div', undefined, 'table-wrap'),
      t = node('table'),
      head = node('thead'),
      hr = node('tr');
    headers.forEach(h => {
      const th = node('th', h);
      th.scope = 'col';
      hr.append(th);
    });
    head.append(hr);
    t.append(head);
    const body = node('tbody');
    rows.forEach(row => {
      const tr = node('tr');
      row.forEach(v => {
        const td = node('td');
        td.append(v instanceof Node ? v : document.createTextNode(String(v ?? 'No disponible')));
        tr.append(td);
      });
      body.append(tr);
    });
    t.append(body);
    wrap.append(t);
    host.append(wrap);
  }
  const date = v => v ? new Intl.DateTimeFormat('es', {
    dateStyle: 'medium',
    timeStyle: 'short'
  }).format(new Date(v)) : 'Sin fecha';

  function pages(host, prev, next) {
    const row = node('div', undefined, 'pagination');
    if (prev) row.append(btn('Anterior', prev));
    if (next) row.append(btn('Siguiente', next));
    host.append(row);
  }

  async function toggleAgent(a, button) {
    const enabling = a.configuration_state !== 'ENABLED';
    button.disabled = true;
    try {
      const result = await api('/agents/' + encodeURIComponent(a.id) +
        (enabling ? '/activate' : '/deactivate'), {
          method: 'POST',
          body: JSON.stringify({expected_revision: a.revision})
        });
      notify(result.agent.configuration_state === 'ENABLED' ?
        'Agente habilitado. Ya puede recibir solicitudes.' :
        'Agente deshabilitado. No se admitirán nuevas solicitudes.');
      await render();
    } catch (e) {
      button.disabled = false;
      if (e.name === 'AbortError') return;
      if (e.status === 401) { await render(); return; }
      notify(e.message || 'No se pudo cambiar el estado del agente.');
      if (e.status === 409) await render();
    }
  }

  function card(a) {
    const c = node('article', undefined, 'agent-card'),
      top = node('div', undefined, 'card-top');
    top.append(icon('agent', 'agent-icon'), badge(a.configuration_state));
    const meta = node('div', undefined, 'meta');
    meta.append(badge(a.activity_state), node('span', a.timezone));
    const bottom = node('div', undefined, 'card-bottom');
    const actions = node('div', undefined, 'agent-actions');
    const enabled = a.configuration_state === 'ENABLED';
    actions.append(btn(enabled ? 'Deshabilitar' : 'Habilitar',
      function () { return toggleAgent(a, this); },
      enabled ? 'secondary' : 'primary'));
    actions.append(link('Configurar →', '/agents/' + a.id + '/edit', 'quiet'));
    bottom.append(node('span', 'Revisión ' + a.revision, 'muted'), actions);
    c.append(top, node('h3', a.name), node('p', a.description || 'Sin descripción'), meta, bottom);
    return c;
  }

  function showError(e, host = root) {
    if (e.name === 'AbortError') return;
    if (e.status === 401) {
      render();
      return;
    }
    host.replaceChildren(node('p', e.message || 'No se pudo consultar la información.', 'error'), btn(
      'Reintentar', render));
  }
  async function dashboard() {
    const [agents, metrics] = await Promise.all([api('/agents?limit=4'), api('/metrics')]);
    heading('Tu espacio de agentes', 'Configurá tus agentes. Seguí cada paso desde acá.', link(
      '+ Crear agente', '/agents/new'));
    const hero = node('section', undefined, 'hero'),
      copy = node('div');
    copy.append(node('p', 'DE LA IDEA A LA CONFIGURACIÓN', 'eyebrow'), node('h2',
      'Un propósito para cada agente.'), node('p',
      'Definí qué necesitás, elegí sus herramientas y establecé los límites. Empezá con una configuración a tu medida.'
      ), link('Configurar un agente →', '/agents/new', 'secondary'));
    const orbit = node('div', undefined, 'hero-orbit');
    orbit.setAttribute('aria-hidden', 'true');
    orbit.append(icon());
    hero.append(copy, orbit);
    root.append(hero);
    const stats = node('dl', undefined, 'stats'),
      counts = metrics.jobs_by_state;
    [
      ['Ejecuciones registradas', Object.values(counts).reduce((a, b) => a + b, 0),
        'Historial de tu cuenta'
      ],
      ['En ejecución', counts.RUNNING || 0, 'Estado informado por el motor'],
      ['Resultados entregados', counts.DELIVERED || 0, 'Aprobados y disponibles']
    ].forEach(([t, v, h]) => {
      const d = node('div', undefined, 'stat');
      d.append(node('dt', t), node('dd', String(v)), node('small', h));
      stats.append(d);
    });
    root.append(stats);
    const panel = node('section', undefined, 'panel'),
      head = node('div', undefined, 'section-head');
    head.append(node('h2', 'Mis agentes'), link('Ver todos →', '/agents', 'quiet'));
    panel.append(head);
    if (!agents.items.length) empty(panel, 'Tu primer agente empieza acá',
      'Todavía no creaste agentes. Se guardarán deshabilitados.', link('Crear mi primer agente',
        '/agents/new'));
    else {
      const cards = node('div', undefined, 'cards');
      agents.items.forEach(a => cards.append(card(a)));
      panel.append(cards);
    }
    root.append(panel);
    const usage = node('section', undefined, 'panel');
    usage.append(node('h2', 'Consumo verificado'));
    if (metrics.usage_status === 'UNAVAILABLE') usage.append(node('p',
      'No disponible. Todavía no hay mediciones verificadas de proveedores.', 'muted'));
    else table(usage, ['Proveedor', 'Llamadas', 'Tokens de entrada', 'Tokens de salida', 'Costo'], metrics
      .provider_usage.map(u => [u.provider_id, u.calls, u.input_tokens, u.output_tokens, u.cost ===
        null ? 'No disponible' : u.cost + ' ' + u.currency
      ]));
    root.append(usage, banner(
      'La ejecución de herramientas está pendiente de integración. Podés guardar configuraciones; esta interfaz no inicia trabajos.'
      ));
  }
  async function agentsPage() {
    heading('Mis agentes', 'Configuraciones propias, con estados informados por el motor.', link(
      '+ Crear agente', '/agents/new'));
    const host = node('section');
    root.append(host);
    const cursors = [null];
    async function load() {
      host.replaceChildren(node('p', 'Cargando agentes…', 'muted'));
      try {
        const cursor = cursors.at(-1),
          data = await api('/agents?limit=12' + (cursor ? '&after=' + encodeURIComponent(cursor) : ''));
        host.replaceChildren();
        if (!data.items.length) empty(host, 'Todavía no tenés agentes',
          'Creá una configuración para empezar.', link('Crear agente', '/agents/new'));
        else {
          const cards = node('div', undefined, 'cards');
          data.items.forEach(a => cards.append(card(a)));
          host.append(cards);
        }
        pages(host, cursors.length > 1 ? () => {
          cursors.pop();
          load();
        } : null, data.next_cursor ? () => {
          cursors.push(data.next_cursor);
          load();
        } : null);
      } catch (e) {
        showError(e, host);
      }
    }
    await load();
  }

  function field(host, label, name, type, value, props = {}) {
    const wrap = node('div', undefined, 'field'), caption = node('label', label),
      input = node(type === 'textarea' ? 'textarea' : type === 'select' ? 'select' : 'input');
    if (input.tagName === 'INPUT') input.type = type;
    input.name = name;
    input.id = 'field-' + name.replace(/[^a-zA-Z0-9_-]/g, '-');
    caption.htmlFor = input.id;
    const {
      values,
      ...attributes
    } = props;
    Object.assign(input, attributes);
    (values || []).forEach(v => {
      const o = node('option', v);
      o.value = v;
      input.append(o);
    });
    input.value = value ?? '';
    wrap.append(caption, input);
    host.append(wrap);
    return input;
  }
  async function editor(id) {
    const a = id ? (await api('/agents/' + encodeURIComponent(id))).agent : null;
    heading(a ? 'Configurar agente' : 'Crear un agente', a ? 'Guardá cambios sobre la revisión ' + a
      .revision + '.' : 'Dale un propósito y ajustá sus límites.', link('Volver a mis agentes',
        '/agents', 'secondary'));
    const form = node('form');
    form.id = 'agent-form';
    const general = node('section', undefined, 'panel'),
      grid = node('div', undefined, 'form-grid');
    general.append(node('h2', '01 · Identidad y propósito'), node('p',
      'Definí el objetivo, el contexto y cómo debería responder.', 'help'));
    field(grid, 'Nombre', 'name', 'text', a?.name, {
      required: true,
      maxLength: 120
    });
    field(grid, 'Zona horaria IANA', 'timezone', 'text', a?.timezone || Intl.DateTimeFormat()
      .resolvedOptions().timeZone || 'UTC', {
        required: true,
        maxLength: 64
      });
    field(grid, 'Descripción', 'description', 'textarea', a?.description, {
      maxLength: 1000
    }).parentElement.className = 'full';
    field(grid, 'Instrucciones del agente', 'instructions', 'textarea', a?.instructions, {
      required: true,
      maxLength: 8000
    }).parentElement.className = 'full';
    general.append(grid);
    form.append(general);
    const toolPanel = node('fieldset', undefined, 'panel');
    toolPanel.append(node('legend', '02 · Herramientas y parámetros'), node('p',
      'Podés configurar una prueba local gratuita. Los adaptadores de OpenAI y scraping siguen pendientes.', 'help'));
    const selected = [];
    context.tools.forEach(t => {
      const label = node('label', undefined, 'tool-choice'),
        check = node('input');
      check.type = 'checkbox';
      check.name = 'capability';
      check.value = t.id;
      check.checked = a ? a.capabilities.includes(t.id) : t.id === 'openai.analysis';
      label.append(check, node('span', names[t.id] || t.id),
        t.id === 'dpia.test.echo' ? node('span', 'Local', 'badge active') : pending());
      toolPanel.append(label);
      const host = node('div', undefined, 'tool-fields');
      host.hidden = !check.checked;
      toolPanel.append(host);
      const params = a?.search_parameters?.[t.id] || {},
        controls = [];
      const labels = {
        instructions: 'Instrucciones adicionales',
        query: 'Búsqueda',
        country: 'País',
        city: 'Ciudad',
        postal_id: 'ID de código postal',
        scope_id: 'ID de ámbito',
        category_id: 'ID de categoría',
        language: 'Idioma'
      };
      if (t.id === 'dpia.amazon.search') {
        const schema = t.input_schema.properties;
        const initial = params;
        const inputs = {};
        const add = (key, label, type = 'select') => {
          inputs[key] = field(host, label, t.id + ':' + key, type, initial[key] ?? '', {
            required: check.checked, disabled: !check.checked
          });
          controls.push({key, input: inputs[key], required: true, schema: schema[key]});
          return inputs[key];
        };
        const options = (input, items, placeholder, saved) => {
          input.replaceChildren();
          const blank = node('option', placeholder);
          blank.value = '';
          input.append(blank);
          items.forEach(([value, label]) => {
            const opt = node('option', label);
            opt.value = String(value);
            input.append(opt);
          });
          input.value = items.some(([v]) => String(v) === String(saved)) ? String(saved) : '';
        };
        add('country', 'País');
        add('city', 'Ciudad');
        add('scope_id', 'Ámbito');
        add('category_id', 'Categoría');
        add('postal_id', 'Código postal');
        add('language', 'Idioma');
        add('query', 'Búsqueda', 'text');
        inputs.query.maxLength = 500;
        inputs.country.required = true;
        let cities = [], catalog = null, serial = 0;
        const setBusy = (busy) => {
          ['city', 'scope_id', 'category_id', 'postal_id'].forEach(k => {
            inputs[k].disabled = !check.checked || busy;
          });
        };
        const loadCity = async (savedScope = '', savedCategory = '', savedPostal = '') => {
          const token = ++serial;
          catalog = null;
          options(inputs.scope_id, [], 'Elegí un ámbito');
          options(inputs.category_id, [], 'Elegí una categoría');
          options(inputs.postal_id, [], 'Elegí un código postal');
          if (!inputs.city.value) return;
          setBusy(true);
          try {
            const q = new URLSearchParams({
              pais: inputs.country.value, ciudad: inputs.city.value,
              idioma: inputs.language.value
            });
            const data = await request('/api/catalogos/ubicacion?' + q);
            if (token !== serial) return;
            if (!data.success) throw new Error('No se pudo cargar el catálogo.');
            catalog = data;
            options(inputs.scope_id, data.ambitos.map(x => [x.ambito_id, x.nombre]),
              'Elegí un ámbito', savedScope);
            const postal = data.codigos_postales.map(x => [x.id, x.codigoPostal]);
            options(inputs.postal_id, postal, 'Elegí un código postal', savedPostal);
            if (postal.length === 1) inputs.postal_id.value = String(postal[0][0]);
            updateCategories(savedCategory);
          } catch (e) {
            if (token === serial) notify('No se pudo cargar la ubicación: ' + e.message);
          } finally {
            if (token === serial) setBusy(false);
          }
        };
        const updateCategories = (saved = '') => {
          const scope = Number(inputs.scope_id.value);
          const matches = catalog && scope ? catalog.categorias.filter(x =>
            (x.ambito_ids || []).map(Number).includes(scope)) : [];
          options(inputs.category_id, matches.map(x => [x.categoria_id, x.nombre]),
            'Elegí una categoría', saved);
        };
        const loadCountry = async (savedCity = '', savedScope = '',
          savedCategory = '', savedPostal = '') => {
          const token = ++serial;
          cities = [];
          options(inputs.city, [], 'Cargando ciudades…');
          options(inputs.scope_id, [], 'Elegí un ámbito');
          options(inputs.category_id, [], 'Elegí una categoría');
          options(inputs.postal_id, [], 'Elegí un código postal');
          if (!inputs.country.value) return;
          setBusy(true);
          try {
            const data = await request('/api/catalogos/ciudades?pais=' +
              encodeURIComponent(inputs.country.value));
            if (token !== serial) return;
            if (!data.success) throw new Error('No se pudieron cargar las ciudades.');
            cities = data.ciudades;
            options(inputs.city, cities.map(x => [x.nombre, x.nombre]),
              'Elegí una ciudad', savedCity);
            if (inputs.city.value) await loadCity(savedScope, savedCategory, savedPostal);
          } catch (e) {
            if (token === serial) notify('No se pudieron cargar las ciudades: ' + e.message);
          } finally {
            if (token === serial) setBusy(false);
          }
        };
        options(inputs.country, schema.country.enum.map(x => [x, x]),
          'Elegí un país', initial.country || 'Argentina');
        options(inputs.language, schema.language.enum.map(x => [x, x]),
          'Elegí un idioma', initial.language || 'es');
        inputs.country.onchange = () => loadCountry();
        inputs.city.onchange = () => loadCity();
        inputs.scope_id.onchange = () => updateCategories();
        inputs.language.onchange = () => loadCity();
        loadCountry(initial.city, initial.scope_id, initial.category_id, initial.postal_id);
      } else Object.entries(t.input_schema.properties).forEach(([key, schema]) => {
        const required = (t.input_schema.required || []).includes(key),
          input = field(host, labels[key] || key, t.id + ':' + key, schema.enum ? 'select' :
            schema.type === 'integer' ? 'number' : key === 'instructions' ? 'textarea' : 'text',
            params[key] ?? schema.enum?.[0], {
              required: check.checked && required,
              disabled: !check.checked,
              ...(schema.enum ? {
                values: schema.enum
              } : {}),
              ...(schema.minimum !== undefined ? {
                min: schema.minimum
              } : {}),
              ...(schema.maxLength ? {
                maxLength: schema.maxLength
              } : {}),
              ...(schema.type === 'integer' ? {
                step: 1
              } : {})
            });
        controls.push({
          key,
          input,
          required,
          schema
        });
      });
      check.onchange = () => {
        host.hidden = !check.checked;
        controls.forEach(c => {
          c.input.disabled = !check.checked;
          c.input.required = check.checked && c.required;
        });
      };
      selected.push({
        check,
        controls
      });
    });
    form.append(toolPanel);
    const panel = node('section', undefined, 'panel'),
      limitsGrid = node('div', undefined, 'form-grid');
    panel.append(node('h2', '03 · Límites por ejecución'), node('p',
      'Configuración de límites; no representa consumo.', 'help'));
    const limits = {
      max_tool_calls: ['Máximo de llamadas', 3, 20],
      max_output_tokens: ['Máximo de tokens de salida', 2000, 16000],
      max_duration_seconds: ['Duración máxima (segundos)', 300, 3600],
      max_corrections: ['Máximo de correcciones', 1, 2]
    };
    Object.entries(limits).forEach(([key, [title, initial, max]]) => field(limitsGrid, title, key,
      'number', a?.limits?.[key] ?? initial, {
        required: true,
        min: key === 'max_corrections' ? 0 : 1,
        max,
        step: 1
      }));
    panel.append(limitsGrid);
    form.append(panel);
    const message = node('p', undefined, 'error');
    message.hidden = true;
    message.setAttribute('role', 'alert');
    message.tabIndex = -1;
    form.append(message, banner(a ?
      'Guardar conserva el estado actual del agente. La ejecución sigue pendiente.' :
      'El agente se creará deshabilitado. Guardar no ejecuta herramientas ni programa tareas.'));
    const actions = node('div', undefined, 'form-actions'),
      save = node('button', a ? 'Guardar cambios' : 'Crear agente', 'primary');
    save.type = 'submit';
    actions.append(link('Cancelar', '/agents', 'secondary'), save);
    form.append(actions);
    form.onsubmit = async event => {
      event.preventDefault();
      if (save.disabled) return;
      message.hidden = true;
      const chosen = selected.filter(t => t.check.checked);
      if (!chosen.length) {
        message.textContent = 'Elegí al menos una herramienta.';
        message.hidden = false;
        message.focus();
        return;
      }
      const values = new FormData(form),
        body = {
          name: values.get('name').trim(),
          description: values.get('description'),
          instructions: values.get('instructions'),
          timezone: values.get('timezone').trim(),
          capabilities: chosen.map(t => t.check.value),
          limits: {},
          tool_parameters: {}
        };
      Object.keys(limits).forEach(k => body.limits[k] = Number(values.get(k)));
      chosen.forEach(t => {
        const params = {};
        t.controls.forEach(({
          key,
          input,
          schema
        }) => {
          if (input.value !== '') params[key] = schema.type === 'integer' ? Number(input
            .value) : input.value;
        });
        body.tool_parameters[t.check.value] = params;
      });
      if (a) body.expected_revision = a.revision;
      save.disabled = true;
      try {
        await api(a ? '/agents/' + a.id : '/agents', {
          method: a ? 'PATCH' : 'POST',
          body: JSON.stringify(body)
        });
        notify(a ? 'Configuración guardada.' : 'Agente creado y deshabilitado.');
        navigate('/agents');
      } catch (e) {
        if (e.status === 401) {
          render();
          return;
        }
        if (e.name !== 'AbortError') {
          message.textContent = e.message;
          message.hidden = false;
          message.focus();
        }
        save.disabled = false;
      }
    };
    root.append(form);
  }
  async function schedulesPage() {
    heading('Programaciones', 'Consultá las programaciones de cada agente.');
    root.append(banner(
      'La creación y ejecución de nuevas programaciones está pendiente en esta interfaz hasta completar los adaptadores.'
      ));
    const panel = node('section', undefined, 'panel'),
      select = field(panel, 'Agente', 'agent', 'select', ''),
      out = node('div');
    const first = node('option', 'Elegí un agente');
    first.value = '';
    select.append(first);
    panel.append(out);
    root.append(panel);
    let cursor = null,
      sequence = 0;
    const more = btn('Cargar más agentes', loadAgents);
    panel.append(more);
    async function loadAgents() {
      more.disabled = true;
      try {
        const data = await api('/agents?limit=100' + (cursor ? '&after=' + encodeURIComponent(cursor) :
          ''));
        data.items.forEach(a => {
          const o = node('option', a.name);
          o.value = a.id;
          select.append(o);
        });
        cursor = data.next_cursor;
        more.hidden = !cursor;
        if (select.options.length === 1) empty(out, 'No hay agentes para programar',
          'Primero creá la configuración de un agente.', link('Crear agente', '/agents/new'));
      } catch (e) {
        showError(e, out);
      } finally {
        more.disabled = false;
      }
    }
    select.onchange = async () => {
      const run = ++sequence;
      out.replaceChildren();
      if (!select.value) return;
      out.append(node('p', 'Consultando programaciones…', 'muted'));
      try {
        const data = await api('/agents/' + select.value + '/schedules');
        if (run !== sequence) return;
        out.replaceChildren();
        if (!data.items.length) empty(out, 'Sin programaciones',
          'Este agente no tiene programaciones registradas.');
        else {
          table(out, ['Frecuencia', 'Zona horaria', 'Próxima ejecución', 'Estado'], data.items.map(
            s => [({
                DAILY: 'Diaria',
                WEEKLY: 'Semanal'
              } [s.configuration?.frequency] || s.configuration?.frequency || 'No disponible'), s
              .timezone, date(s.next_run_at), s.enabled ? 'Habilitada' : 'Deshabilitada'
            ]));
          out.append(node('p', 'Se muestran hasta ' + data.list_limit + ' programaciones.', 'help'));
        }
      } catch (e) {
        if (run === sequence) showError(e, out);
      }
    };
    await loadAgents();
  }
  async function executionsPage() {
    heading('Ejecuciones', 'Historial real de los trabajos de tu cuenta.');
    const launch = node('section', undefined, 'panel');
    launch.append(node('h2', 'Ejecutar prueba interna'),
      node('p', 'Solo usa el adaptador local. No llama a OpenAI ni a Apify. El resultado queda sin verificar.', 'help'));
    const launchForm = node('form');
    const agentSelect = field(launchForm, 'Agente habilitado con prueba interna',
      'manual-agent', 'select', '');
    const initial = node('option', 'Elegí un agente');
    initial.value = '';
    agentSelect.append(initial);
    const message = field(launchForm, 'Mensaje de prueba', 'manual-message',
      'text', 'Verificar circuito de DPIA Agents', {maxLength: 500});
    const launchButton = btn('Ejecutar ahora', async () => {
      if (!agentSelect.value) { notify('Elegí un agente con la herramienta de prueba interna.'); return; }
      launchButton.disabled = true;
      try {
        const selected = (await api('/agents/' + encodeURIComponent(agentSelect.value))).agent;
        if (selected.configuration_state !== 'ENABLED' ||
            !Array.isArray(selected.capabilities) ||
            !selected.capabilities.includes('dpia.test.echo')) {
          throw new Error('El agente debe estar habilitado y tener la herramienta Prueba interna.');
        }
        const limits = {
          max_tool_calls: 1,
          max_output_tokens: Math.min(2000, selected.limits.max_output_tokens),
          max_duration_seconds: Math.min(300, selected.limits.max_duration_seconds),
          max_corrections: 0
        };
        const key = 'local-test-' + crypto.randomUUID();
        const data = await api('/agents/' + encodeURIComponent(selected.id) + '/requests', {
          method: 'POST',
          headers: {'Idempotency-Key': key},
          body: JSON.stringify({
            instructions: 'Prueba técnica local sin proveedores externos',
            pipeline: [{tool: 'dpia.test.echo', parameters: {message: message.value}}],
            limits
          })
        });
        notify('Trabajo creado: ' + data.job.id + '. Para procesarlo, iniciá el outbox y worker local.');
        await load();
      } catch (e) {
        notify(e.message || 'No se pudo crear el trabajo de prueba.');
      } finally { launchButton.disabled = false; }
    }, 'primary');
    launchForm.append(launchButton);
    launch.append(launchForm);
    root.append(launch);
    (async () => {
      try {
        let cursor = null;
        do {
          const data = await api('/agents?limit=100' +
            (cursor ? '&after=' + encodeURIComponent(cursor) : ''));
          const enabled = data.items.filter(a => a.configuration_state === 'ENABLED');
          const details = await Promise.all(enabled.map(async a => {
            const response = await api('/agents/' + encodeURIComponent(a.id));
            return response.agent;
          }));
          details.filter(a => Array.isArray(a.capabilities) &&
            a.capabilities.includes('dpia.test.echo')).forEach(a => {
            const option = node('option', a.name);
            option.value = a.id;
            agentSelect.append(option);
          });
          cursor = data.next_cursor;
        } while (cursor);
        if (agentSelect.options.length === 1)
          launch.append(banner('Primero agregá Prueba interna al agente desde Configurar y guardá los cambios.'));
      } catch (e) { showError(e, launch); }
    })();
    const filters = node('div', undefined, 'filters'),
      state = field(filters, 'Estado', 'state', 'select', ''),
      all = node('option', 'Todos los estados');
    all.value = '';
    state.append(all);
    ['CREATED', 'SCHEDULED', 'QUEUED', 'RUNNING', 'REVIEWING', 'CORRECTION_REQUIRED', 'APPROVED',
      'READY_FOR_DELIVERY', 'DELIVERED', 'FAILED', 'CANCELLED'
    ].forEach(s => {
      const o = node('option', states[s]);
      o.value = s;
      state.append(o);
    });
    root.append(filters);
    const host = node('section', undefined, 'panel');
    root.append(host);
    let cursors = [null],
      sequence = 0;
    async function load() {
      const run = ++sequence;
      host.replaceChildren(node('p', 'Cargando ejecuciones…', 'muted'));
      try {
        const params = new URLSearchParams({
          limit: '25'
        });
        if (state.value) params.set('state', state.value);
        if (cursors.at(-1)) params.set('after', cursors.at(-1));
        const data = await api('/jobs?' + params);
        if (run !== sequence) return;
        host.replaceChildren();
        if (!data.items.length) empty(host, 'Sin ejecuciones',
          'No hay trabajos registrados para esta selección.');
        else table(host, ['Trabajo', 'Estado', 'Creación', 'Progreso', 'Resultado'], data.items.map(
          j => [j.id, badge(j.state), date(j.created_at), j.progress === null ? 'No disponible' : j
            .progress + '%', j.state === 'DELIVERED' ? btn('Ver resultado', () => result(j.id),
              'quiet') : 'Todavía no disponible'
          ]));
        pages(host, cursors.length > 1 ? () => {
          cursors.pop();
          load();
        } : null, data.next_cursor ? () => {
          cursors.push(data.next_cursor);
          load();
        } : null);
      } catch (e) {
        if (run === sequence) showError(e, host);
      }
    }
    state.onchange = () => {
      cursors = [null];
      load();
    };
    await load();
  }
  async function result(id, admin = false) {
    const dialog = document.querySelector('#result-dialog'),
      host = document.querySelector('#result-content');
    host.replaceChildren(node('p', 'Cargando resultado…'));
    dialog.showModal();
    try {
      const data = await api((admin ? '/admin' : '') + '/jobs/' + id + '/result');
      host.replaceChildren(node('p', data.result.summary));
      const list = node('ul');
      data.result.findings.forEach(f => list.append(node('li', f.text)));
      host.append(list, node('h3', 'Fuentes'));
      data.result.sources.forEach(s => {
        try {
          const url = new URL(s.url);
          if (!['https:', 'http:'].includes(url.protocol)) return;
          const a = node('a', s.title);
          a.href = url.href;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          const p = node('p');
          p.append(a);
          host.append(p);
        } catch {}
      });
      data.result.warnings.forEach(w => host.append(banner(w)));
    } catch (e) {
      showError(e, host);
    }
  }

  function integrationsPage() {
    heading('Integraciones', 'Herramientas declaradas para tus agentes.');
    root.append(banner(
      'La conexión de proveedores y la ejecución de herramientas están pendientes. No se solicitan ni guardan claves API en esta interfaz.'
      ));
    const cards = node('div', undefined, 'cards');
    context.tools.forEach(t => {
      const c = node('article', undefined, 'agent-card'),
        top = node('div', undefined, 'card-top');
      top.append(icon('integration', 'agent-icon'), pending());
      const b = btn('Conectar · pendiente', () => {});
      b.disabled = true;
      c.append(top, node('h3', names[t.id] || t.id), node('p', t.provider), node('p',
        'Prepará los parámetros desde la configuración de un agente. El adaptador aún no está disponible.'
        ), b);
      cards.append(c);
    });
    root.append(cards);
  }
  async function administrationPage() {
    if (!context.session.admin) {
      heading('Acceso restringido', 'Esta sección requiere una sesión de administrador.');
      return;
    }
    const data = await api('/admin/overview');
    heading('Administración', 'Supervisión global de agentes, trabajos y workers.');
    root.append(banner(
      'La gestión de usuarios y roles está pendiente: todavía no existe una API de administración de usuarios.'
      ));
    for (const [title, headers, items, rows] of [
        ['Agentes', ['Agente', 'Propietario', 'Configuración', 'Actividad'], data.agents, data.agents.map(
            a => [a.name, 'Usuario ' + a.owner_id, badge(a.configuration_state), badge(a.activity_state)]
            )],
        ['Trabajos', ['Trabajo', 'Propietario', 'Estado', 'Resultado'], data.jobs, data.jobs.map(j => [j
          .id, 'Usuario ' + j.owner_id, badge(j.state), j.state === 'DELIVERED' ? btn('Ver resultado',
            () => result(j.id, true), 'quiet') : 'No disponible'
        ])],
        ['Workers', ['Worker', 'Disponibilidad', 'Última señal'], data.workers, data.workers.map(w => [w
          .id, badge(w.availability), date(w.heartbeat_at)
        ])]
      ]) {
      const p = node('section', undefined, 'panel');
      p.append(node('h2', title));
      if (!items.length) empty(p, 'Sin registros', 'Todavía no hay registros para esta sección.');
      else table(p, headers, rows);
      root.append(p);
    }
    root.append(node('p', 'Cada listado muestra hasta ' + data.list_limit + ' registros.', 'help'));
  }
  let googleScript;
  async function loginPage() {
    document.querySelector('#logout').hidden = true;
    document.querySelector('#account-label').textContent = 'Acceso seguro';
    document.querySelector('#admin-nav').hidden = true;
    const section = node('section', undefined, 'login'),
      hero = node('div', undefined, 'hero'),
      copy = node('div');
    copy.append(node('p', 'BIENVENIDO A DPIA AGENTS', 'eyebrow'), node('h1',
      'Tus agentes. Tu forma de trabajar.'), node('p',
      'Un espacio propio para configurar, organizar y supervisar tus agentes.'));
    hero.append(copy);
    section.append(hero);
    const panel = node('div', undefined, 'panel'),
      mount = node('div'),
      status = node('p', 'Preparando acceso…', 'help');
    mount.id = 'google-login';
    status.setAttribute('role', 'status');
    panel.append(node('h2', 'Ingresá a tu espacio'), node('p',
      'Usá tu cuenta de Google para continuar de forma segura.', 'muted'), mount, status);
    section.append(panel);
    root.replaceChildren(section);
    const run = version;
    try {
      const config = await request('/api/auth/config', {
        signal: abort.signal
      });
      if (!config.client_id) {
        status.textContent = 'El acceso con Google no está configurado. Contactá al administrador.';
        return;
      }
      if (!window.google?.accounts?.id) {
        if (!googleScript) googleScript = new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = 'https://accounts.google.com/gsi/client';
          s.async = true;
          const timeout = setTimeout(() => {
            s.remove();
            googleScript = null;
            reject(new Error('No se pudo cargar Google. Recargá para reintentar.'));
          }, 12000);
          s.onload = () => {
            clearTimeout(timeout);
            resolve();
          };
          s.onerror = () => {
            clearTimeout(timeout);
            s.remove();
            googleScript = null;
            reject(new Error('No se pudo cargar Google. Recargá para reintentar.'));
          };
          document.head.append(s);
        });
        await googleScript;
      }
      if (run !== version) return;
      window.google.accounts.id.initialize({
        client_id: config.client_id,
        callback: async response => {
          status.textContent = 'Verificando tu cuenta…';
          try {
            await request('/api/auth/google', {
              method: 'POST',
              body: JSON.stringify({
                credential: response.credential
              })
            });
            await render();
          } catch (e) {
            status.textContent = e.message;
          }
        }
      });
      window.google.accounts.id.renderButton(mount, {
        theme: 'outline',
        size: 'large',
        text: 'continue_with',
        locale: 'es',
        width: 260
      });
      status.textContent = 'Tu acceso y tus permisos se validan en el servidor.';
    } catch (e) {
      if (e.name !== 'AbortError' && run === version) status.textContent = e.message;
    }
  }
  async function render() {
    const run = ++version;
    abort?.abort();
    abort = new AbortController();
    context = null;
    document.querySelector('#result-dialog').close();
    document.querySelector('#result-content').replaceChildren();
    root.replaceChildren(node('p', 'Cargando tu espacio…', 'loading'));
    root.setAttribute('aria-busy', 'true');
    document.querySelector('#admin-nav').hidden = true;
    const path = location.pathname,
      active = path.startsWith('/agents') ? '/agents' : path === '/admin/agents' ? '/administration' :
      path;
    document.querySelectorAll('nav [data-nav]').forEach(a => {
      if (a.pathname === active) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    document.querySelector('#section-label').textContent = titles[active] || 'Mis agentes';
    document.title = (titles[active] || 'Configurar agente') + ' · DPIA Agents';
    try {
      context = await api('/session');
      if (run !== version) return;
      document.querySelector('#admin-nav').hidden = !context.session.admin;
      document.querySelector('#logout').hidden = false;
      document.querySelector('#account-label').textContent = context.session.admin ?
        'Sesión de administrador' : 'Mi espacio personal';
      root.replaceChildren();
      if (path === '/') await dashboard();
      else if (path === '/agents') await agentsPage();
      else if (path === '/agents/new') await editor();
      else if (/^\/agents\/[a-f0-9-]+\/edit$/.test(path)) await editor(path.split('/')[2]);
      else if (path === '/schedules') await schedulesPage();
      else if (path === '/executions') await executionsPage();
      else if (path === '/integrations') integrationsPage();
      else if (['/administration', '/admin/agents'].includes(path)) await administrationPage();
      else heading('Página no encontrada', 'Volvé a Mis agentes para continuar.', link('Mis agentes',
        '/agents'));
    } catch (e) {
      if (run !== version || e.name === 'AbortError') return;
      if (e.status === 401) await loginPage();
      else showError(e);
    } finally {
      if (run === version) root.setAttribute('aria-busy', 'false');
    }
  }

  function closeMenu() {
    document.querySelector('#navigation').classList.remove('open');
    document.querySelector('#menu-toggle').setAttribute('aria-expanded', 'false');
  }

  function navigate(path) {
    history.pushState({}, '', path);
    closeMenu();
    render();
    root.focus();
    window.scrollTo(0, 0);
  }
  document.addEventListener('click', event => {
    const a = event.target.closest('a[data-nav]');
    if (a && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button ===
      0) {
      event.preventDefault();
      navigate(a.getAttribute('href'));
    }
  });
  document.querySelector('#menu-toggle').onclick = () => {
    const open = document.querySelector('#navigation').classList.toggle('open');
    document.querySelector('#menu-toggle').setAttribute('aria-expanded', String(open));
  };
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeMenu();
  });
  document.querySelector('#close-result').onclick = () => document.querySelector('#result-dialog').close();
  document.querySelector('#logout').onclick = async () => {
    abort?.abort();
    ++version;
    root.replaceChildren(node('p', 'Cerrando sesión…', 'loading'));
    document.querySelector('#result-dialog').close();
    document.querySelector('#result-content').replaceChildren();
    try {
      await request('/api/auth/logout', {
        method: 'POST'
      });
      window.google?.accounts?.id.disableAutoSelect();
      navigate('/');
    } catch (e) {
      showError(e);
    }
  };
  window.addEventListener('popstate', () => {
    closeMenu();
    render();
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) render();
  });
  render();
})();
