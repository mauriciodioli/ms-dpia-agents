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
    mcp_server_not_found:'El servidor MCP no existe o no tenés acceso.',
    mcp_not_ready:'Probá la conexión y descubrí herramientas antes de activar el MCP.',
    mcp_approval_required:'La herramienta requiere aprobación explícita de un administrador.',
    mcp_role_required:'Esta operación MCP requiere un rol autorizado.',
    mcp_catalog_changed:'Cambió la versión del catálogo MCP. Creá una nueva ejecución.',
    mcp_ssrf_blocked:'La URL MCP resuelve a una dirección privada o reservada.',
    mcp_invalid_url:'Ingresá una URL HTTPS pública válida, sin credenciales ni parámetros.',
    revision_conflict: 'La configuración cambió en otra sesión. Recargá el agente antes de guardar.',
    invalid_contract: 'Revisá los campos y los límites de la configuración.',
    invalid_timezone: 'Ingresá una zona horaria IANA válida.',
    agent_not_found: 'El agente no existe o no tenés acceso.',
    task_not_found: 'La tarea no existe o fue eliminada.',
    task_agent_mismatch: 'Los vínculos de la tarea requieren revisión.',
    task_schedule_conflict:'La tarea tiene varias programaciones vinculadas. Requiere revisión.',
    task_paused:'Activá la tarea antes de habilitar su programación.',
    no_sources_available: 'Ninguna fuente está disponible',
    planner_no_available_tools: 'No hay conexiones disponibles para preparar la tarea.',
    planner_openai_not_configured: 'El servicio de planificación no está disponible. Reintentá más tarde.',
    connections_skipped: 'Se omitieron conexiones no disponibles; continúa con las restantes',
    tool_call_budget_exceeded:'El plan anterior excedió el límite de ejecución. El manager prepara automáticamente los nuevos intentos.',
    agent_budget_exceeded:'Los límites de esta tarea superan los límites del agente.',
    execution_time_in_past:'La próxima ejecución debe estar en el futuro.',
    ambiguous_or_nonexistent_local_time:'La hora elegida es ambigua o inexistente por el cambio de horario. Elegí otra hora.',
    administrator_session_required: 'Se requiere una sesión de administrador.',
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
      e.data = data;
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

  function scheduleText(s){
    const c=s.configuration||{},days=(c.weekdays||[]).map(d=>['','lunes','martes','miércoles','jueves','viernes','sábado','domingo'][d]).join(', ');
    return (c.frequency==='ONCE'?'Una vez · '+c.execution_date:c.frequency==='DAILY'?'Diaria':'Semanal · '+days)+' · '+(c.execution_time||'')+' · '+s.timezone;
  }
  function scheduleDate(value,zone){
    if(!value)return 'Sin fecha';
    return new Intl.DateTimeFormat('es',{dateStyle:'medium',timeStyle:'short',timeZone:zone}).format(new Date(value));
  }
  function taskScheduleCell(task){
    const cell=node('div');
    if(!task.schedules?.length){cell.append(node('p','Sin programación'));return cell;}
    for(const schedule of task.schedules){
      cell.append(node('p',schedule.enabled?'Programación habilitada':'Programación deshabilitada'),node('p',scheduleText(schedule),'help'),
        node('p','Próxima ejecución: '+scheduleDate(schedule.next_run_at,schedule.timezone),'help'),
        node('p','Última ejecución: '+scheduleDate(schedule.last_run_at,schedule.timezone),'help'));
      if(schedule.last_failure){const failure=schedule.last_failure;cell.append(node('p',
        'Último intento fallido: '+scheduleDate(failure.at,schedule.timezone)+' · '+(errors[failure.reason_code]||failure.reason_code||'Motivo no disponible')+' · El trabajo no llegó a crearse en ese intento.','error'));}
    }
    return cell;
  }
  function taskScheduleTable(host,tasks,agentId,administrative=false,editable=true){
    if(!tasks.length){host.append(node('p','Sin tareas configuradas.'));return;}
    table(host,['Tarea','Programación'],tasks.map(task=>[
      editable?link(task.name,(administrative?'/administration':'')+'/agents/'+agentId+'/tasks/'+task.id+'/edit','quiet'):node('span',task.name),taskScheduleCell(task)]));
  }

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

 function pauseOperationId(){
  if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
  const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=[...bytes].map(b=>b.toString(16).padStart(2,'0')).join('');
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
 }
  const pauseOperations = new Map();
  function pauseButton(a, administrative = false) {
    const flags=a.pause||{user_paused:false,admin_paused:false};
    const paused=administrative?flags.admin_paused:flags.user_paused;
    const button=btn(paused?'Reanudar agente':'Pausar agente',async function(){
      this.disabled=true;
      const key=(administrative?'admin:':'owner:')+a.id;
      const body=pauseOperations.get(key)||{paused:!paused,expected_revision:a.revision,operation_id:pauseOperationId()};
      pauseOperations.set(key,body);
      try{
        await api((administrative?'/admin':'')+'/agents/'+encodeURIComponent(a.id)+'/pause',{method:'POST',body:JSON.stringify(body)});
        pauseOperations.delete(key);await render();
      }catch(e){
        this.disabled=false;
        if([401,403,409].includes(e.status)){pauseOperations.delete(key);await render();}
        notify(e.message||'No se confirmó la pausa. Reintentá.');
      }
    },'secondary');
    if(!administrative&&flags.admin_paused&&flags.user_paused)button.disabled=true;
    return button;
  }

  const deleteOperations=new Map();
  function deleteButton(a,administrative=false){
    return btn('Eliminar agente',()=>{
      const dialog=document.createElement('dialog'),message=node('p'),actions=node('div',undefined,'agent-actions');
      dialog.append(node('h2','Eliminar agente'),node('p','¿Eliminar «'+a.name+'»? Se conservará el historial y se cancelarán los trabajos no iniciados.'),message,actions);
      let busy=false;
      const cancel=btn('Cancelar',()=>dialog.close(),'secondary');
      const confirm=btn('Eliminar agente',async()=>{
        busy=true;confirm.disabled=true;cancel.disabled=true;message.textContent='Eliminando…';
        const body=deleteOperations.get(a.id)||{confirm:true,expected_revision:a.revision,operation_id:pauseOperationId()};deleteOperations.set(a.id,body);
        try{
          await api((administrative?'/admin':'')+'/agents/'+encodeURIComponent(a.id),{method:'DELETE',body:JSON.stringify(body)});
          deleteOperations.delete(a.id);dialog.close();await render();notify('Agente eliminado.');
        }catch(e){
          if([400,401,403,404,409].includes(e.status))deleteOperations.delete(a.id);
          message.textContent=e.data?.error==='agent_has_active_jobs'?'No se puede eliminar mientras haya trabajos iniciados.':e.message||'No se confirmó la eliminación. Reintentá.';
          busy=false;confirm.disabled=false;cancel.disabled=false;
        }
      },'agent-delete');
      actions.append(cancel,confirm);dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
      dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
    },'agent-delete');
  }

  function adminPauseCell(a) {
    const cell=node('div'),flags=a.pause||{};
    const states=[];
    if(flags.user_paused)states.push('Pausa del usuario');
    if(flags.admin_paused)states.push('Pausa administrativa');
    cell.append(node('small',states.join(' · ')||'Sin pausa'),pauseButton(a,true),deleteButton(a,true));
    return cell;
  }

  function card(a) {
    const c = node('article', undefined, 'agent-card'),
      top = node('div', undefined, 'card-top');
    top.append(icon('agent', 'agent-icon'), badge(a.configuration_state));
    const meta = node('div', undefined, 'meta');
    meta.append(badge(a.activity_state), node('span', a.timezone));
    if(a.pause?.admin_paused)meta.append(node('span','Pausa administrativa'));
    if(a.pause?.user_paused)meta.append(node('span','Pausa del usuario'));
    const bottom = node('div', undefined, 'card-bottom');
    const actions = node('div', undefined, 'agent-actions');
    const enabled = a.configuration_state === 'ENABLED';
    actions.append(btn(enabled ? 'Deshabilitar' : 'Habilitar',
      function () { return toggleAgent(a, this); },
      enabled ? 'secondary' : 'primary'));
    actions.append(pauseButton(a),deleteButton(a));
    actions.append(link('Configurar →', '/agents/' + a.id + '/edit', 'quiet'));
    bottom.append(node('span', 'Revisión ' + a.revision, 'muted'), actions);
    c.append(top, node('h3', a.name), node('p', a.description || 'Sin descripción'), meta);
    if(a.points){
      const p=a.points,summary=node('div',undefined,'agent-point-summary'),status=node('span',undefined,'agent-point-status'),dot=node('span',undefined,'agent-point-dot');
      dot.dataset.color=p.color;dot.setAttribute('aria-hidden','true');status.append(dot,node('span',p.effective_remaining+' puntos restantes'));
      summary.append(status,node('small','Asignados: '+p.budget+' · Gastados: '+p.budget_consumed+' · Reservados: '+p.budget_reserved));c.append(summary);
    }
    const tasks=node('details',undefined,'configured-task-list'),summary=node('summary','Tareas configuradas'),host=node('div');tasks.append(summary,host);
    let loaded=false;
    tasks.addEventListener('toggle',async()=>{
      if(!tasks.open||loaded)return;loaded=true;host.replaceChildren(node('p','Cargando tareas…','help'));
      try{const data=await api('/agents/'+a.id+'/configured-tasks');host.replaceChildren();
        summary.textContent='Tareas configuradas ('+data.items.length+')';
        if(!data.items.length)host.append(node('p','No hay tareas configuradas.','help'));
        else taskScheduleTable(host,data.items,a.id);
      }catch(e){loaded=false;showError(e,host);}
    });
    c.append(tasks,bottom);
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
      ['Resultados entregados', counts.DELIVERED || 0, 'Disponibles para consulta']
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
  async function editor(id, taskId=null, administrative=false) {
    const taskPath=taskId?(administrative?'/admin':'')+'/agents/'+encodeURIComponent(id)+'/configured-tasks/'+taskId:null;
    const task=taskPath?(await api(taskPath)).task:null;
    const a=task?{...task.configuration,id,revision:task.revision,search_parameters:task.configuration.tool_parameters}:
      id?(await api('/agents/'+encodeURIComponent(id))).agent:null;
    const tasks=id&&!taskId?(await api('/agents/'+encodeURIComponent(id)+'/configured-tasks')).items:[];
    const generalOnly=!!a&&!taskId&&tasks.length>0;
    const back=administrative?'/administration':'/agents';
    heading(task ? 'Configurar tarea' : a ? 'Configurar agente' : 'Crear un agente', a ? 'Guardá cambios sobre la revisión ' + a
      .revision + '.' : 'Dale un propósito y ajustá sus límites.', link(administrative?'Volver a Administración':'Volver a mis agentes',
        back, 'secondary'));
    if(task)root.append(banner('Configuración independiente de esta tarea. Guardar no ejecuta herramientas ni genera cargos.'));
    if(tasks.length){const taskSection=node('section',undefined,'panel');taskSection.append(node('h2','Configuración de tareas'));table(taskSection,['Tarea'],tasks.map(t=>[link(t.name,'/agents/'+id+'/tasks/'+t.id+'/edit','quiet')]));root.append(taskSection);}
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
    field(grid, task ? 'Instrucciones de la tarea' : 'Instrucciones del agente', 'instructions', 'textarea', a?.instructions, {
      required: true,
      maxLength: 8000
    }).parentElement.className = 'full';
    general.append(grid);
    form.append(general);
    const toolPanel = node('fieldset', undefined, 'panel');
    toolPanel.append(node('legend', '02 · Herramientas y parámetros'), node('p',
      'Seleccioná las herramientas del agente. Para usar APIs, autorizá el agente en Integraciones.', 'help'));
    const selected = [];
    (generalOnly?[]:context.tools).forEach(t => {
      const label = node('label', undefined, 'tool-choice'),
        check = node('input');
      check.type = 'checkbox';
      check.name = 'capability';
      check.value = t.id;
      check.checked = t.provider === 'mcp' ? true : (a ? a.capabilities.includes(t.id) : t.id === 'openai.analysis');
      label.append(check, node('span', names[t.id] || t.id),
        t.id === 'dpia.test.echo' ? node('span', 'Local', 'badge active') :
        t.implementation_status === 'IMPLEMENTED' ? node('span', 'Disponible', 'badge active') : pending());
      toolPanel.append(label);
      const host = node('div', undefined, 'tool-fields');
      host.hidden = !check.checked;
      toolPanel.append(host);
      const savedParams = a?.search_parameters?.[t.id];
      const params = t.provider === 'mcp' && (!savedParams || !Object.keys(savedParams).length) ? (t.parameter_template || {}) : (savedParams || {}),
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
      if(t.provider==='mcp'){
        const input=field(host,'Parámetros JSON de '+t.id,t.id+':json','textarea',JSON.stringify(params,null,2),{disabled:!check.checked,maxLength:65536});
        controls.push({key:'$json',input,rawJSON:true,schema:{}});
      }else if (t.id === 'dpia.amazon.search') {
        const schema = t.input_schema.properties;
        const initial = params;
        const inputs = {};
        const add = (key, label, type = 'select') => {
          const required = (t.input_schema.required || []).includes(key);
          inputs[key] = field(host, label, t.id + ':' + key, type, initial[key] ?? '', {
            required: check.checked && required, disabled: !check.checked
          });
          controls.push({key, input: inputs[key], required, schema: schema[key]});
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
    toolPanel.hidden=generalOnly;
    if(generalOnly)toolPanel.querySelectorAll('input,select,textarea').forEach(el=>el.disabled=true);
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
    if(task){limitsGrid.querySelector('[name="max_tool_calls"]').closest('.field').hidden=true;panel.append(node('p','El manager calcula automáticamente las llamadas necesarias y adapta el plan al límite del servicio.','help'));}
    panel.append(limitsGrid);
    panel.hidden=generalOnly;
    if(generalOnly)panel.querySelectorAll('input').forEach(el=>el.disabled=true);
    form.append(panel);
    let scheduleCommand=null;
    if(task){
      const section=node('fieldset',undefined,'panel'),grid=node('div',undefined,'form-grid');
      section.append(node('legend','04 — Programación automática'),node('p','Los resultados se revisan y entregan automáticamente. Los datos sin verificación se muestran como información no verificada.','help'));
      const saved=task.schedules?.[0],timing=saved?.configuration||{};
      const enabled=field(grid,'Habilitar programación','schedule-enabled','select',saved?.enabled?'Sí':'No',{values:['No','Sí']}),
        frequency=field(grid,'Frecuencia','schedule-frequency','select',timing.frequency==='ONCE'?'Una vez':timing.frequency==='DAILY'?'Diaria':'Semanal',{values:['Una vez','Diaria','Semanal']}),
        day=field(grid,'Día de la semana','schedule-day','select',String(timing.weekdays?.[0]||1),{values:['1','2','3','4','5','6','7']}),
        executionDate=field(grid,'Fecha de ejecución','schedule-date','date',timing.execution_date||''),
        executionTime=field(grid,'Hora de ejecución','schedule-time','time',timing.execution_time||'09:00',{required:true}),
        zone=field(grid,'Zona horaria de ejecución IANA','schedule-timezone','text',saved?.timezone||a.timezone,{required:true,maxLength:64});
      [...day.options].forEach((option,index)=>{option.textContent=['lunes','martes','miércoles','jueves','viernes','sábado','domingo'][index];});
      const preview=node('p','Próxima ejecución: '+scheduleDate(saved?.next_run_at,saved?.timezone||a.timezone),'help');preview.setAttribute('role','status');preview.setAttribute('aria-live','polite');preview.tabIndex=-1;
      section.append(grid,preview);form.append(section);
      let dirty=false,sequence=0,timer;
      function command(){
        const c={enabled:enabled.value==='Sí',expected_revision:saved?.revision||0,timezone:zone.value.trim(),
          frequency:frequency.value==='Una vez'?'ONCE':frequency.value==='Diaria'?'DAILY':'WEEKLY',
          weekdays:frequency.value==='Semanal'?[Number(day.value)]:frequency.value==='Diaria'?[1,2,3,4,5,6,7]:[],
          execution_time:executionTime.value,delivery_time:timing.delivery_time||executionTime.value,dst_policy:'REJECT_AMBIGUOUS_OR_NONEXISTENT'};
        // Preserve multi-day weekly schedules unless the user explicitly changes days/frequency.
        if(c.frequency==='WEEKLY'&&!day.dataset.changed&&!frequency.dataset.changed&&timing.weekdays?.length)c.weekdays=[...timing.weekdays];
        if(c.frequency==='ONCE')c.execution_date=executionDate.value;
        return c;
      }
      function visibility(){day.parentElement.hidden=frequency.value!=='Semanal';executionDate.parentElement.hidden=frequency.value!=='Una vez';executionDate.required=frequency.value==='Una vez';}
      async function calculate(explicit=false){
        clearTimeout(timer);const serial=++sequence;
        preview.className='help';preview.textContent='Calculando próxima ejecución…';preview.setAttribute('aria-busy','true');
        calculateButton.disabled=true;
        if(explicit){preview.focus({preventScroll:true});preview.scrollIntoView({block:'nearest'});}
        try{
          const data=await api(taskPath+'?schedule_preview='+encodeURIComponent(JSON.stringify(command())),{
            signal:AbortSignal.any([abort.signal,AbortSignal.timeout(10000)])
          });
          if(serial!==sequence)return;
          if(!data.preview)throw Error('La API no devolvió el cálculo de la próxima ejecución. Reintentá.');
          const value=data.preview.candidate_run_at??data.preview.next_run_at;
          if(value){
            preview.textContent=(enabled.value==='Sí'?'Próxima ejecución calculada: ':'Vista previa con programación deshabilitada: ')+
              scheduleDate(value,zone.value.trim())+' · '+zone.value.trim()+'. Guardá los cambios para aplicar la programación.';
          }else{
            preview.textContent=enabled.value==='Sí'?'No hay una próxima ejecución válida. Revisá la fecha y la hora.':
              'Programación deshabilitada. La fecha seleccionada ya pasó; elegí una fecha futura para calcular la vista previa.';
          }
        }catch(e){
          if(serial===sequence&&!abort.signal.aborted){preview.className='error';preview.textContent=
            e.name==='TimeoutError'?'El cálculo tardó demasiado. Volvé a intentarlo.':e.message||'No se pudo calcular la próxima ejecución. Reintentá.';}
        }finally{if(serial===sequence){calculateButton.disabled=false;preview.removeAttribute('aria-busy');}}
      }
      for(const input of [enabled,frequency,day,executionDate,executionTime,zone])input.addEventListener('input',()=>{
        dirty=true;input.dataset.changed='true';visibility();clearTimeout(timer);timer=setTimeout(calculate,300);
      });
      const calculateButton=btn('Calcular próxima ejecución',()=>calculate(true));
      section.append(calculateButton);visibility();
      scheduleCommand=()=>dirty?command():null;
      if(task.schedules?.length>1){section.append(banner('Hay más de una programación vinculada. Requiere revisión antes de editar.'));section.querySelectorAll('input,select,button').forEach(input=>input.disabled=true);}
    }
    const message = node('p', undefined, 'error');
    message.hidden = true;
    message.setAttribute('role', 'alert');
    message.tabIndex = -1;
    form.append(message, banner(a ?
      'Guardar conserva el estado actual. Las APIs requieren autorización en Integraciones.' :
      'El agente se creará deshabilitado. Guardar no ejecuta herramientas ni programa tareas.'));
    const actions = node('div', undefined, 'form-actions'),
      save = node('button', a ? 'Guardar cambios' : 'Crear agente', 'primary');
    save.type = 'submit';
    actions.append(link('Cancelar', back, 'secondary'), save);
    form.append(actions);
    form.onsubmit = async event => {
      event.preventDefault();
      if (save.disabled) return;
      message.hidden = true;
      const chosen = selected.filter(t => t.check.checked);
      if (!generalOnly && !chosen.length) {
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
      let parameterError=false;
      chosen.forEach(t => {
        const params = {};
        t.controls.forEach(({
          key,
          input,
          schema,rawJSON
        }) => {
          if(rawJSON){try{const value=JSON.parse(input.value);if(!value||Array.isArray(value)||typeof value!=='object')throw Error();Object.assign(params,value);}catch(_){parameterError=true;}return;}
          if (input.value !== '') params[key] = schema.type === 'integer' ? Number(input
            .value) : input.value;
        });
        body.tool_parameters[t.check.value] = params;
      });
      if(parameterError){message.textContent='Revisá los parámetros JSON de las herramientas MCP.';message.hidden=false;message.focus();return;}
      if (a) body.expected_revision = a.revision;
      const timing=scheduleCommand?.();if(timing)body.schedule=timing;
      save.disabled = true;
      try {
        const payload=generalOnly?Object.fromEntries(['name','description','instructions','timezone','expected_revision'].map(k=>[k,body[k]])):body;
        await api(taskPath || (generalOnly?'/agents/'+a.id+'/identity':a ? '/agents/' + a.id : '/agents'), {
          method: a ? 'PATCH' : 'POST',
          body: JSON.stringify(payload)
        });
        notify(a ? 'Configuración guardada.' : 'Agente creado y deshabilitado.');
        navigate(back);
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
    heading('Programaciones', 'Abrí un agente para consultar sus horarios e historial.');
    const list=node('div',undefined,'schedule-agent-list');root.append(list);
    let cursor=null;
    const more=btn('Cargar más agentes',load);root.append(more);
    async function load(){
      more.disabled=true;
      try{
        const data=await api('/schedule-view'+(cursor?'?after='+encodeURIComponent(cursor):''));
        if(!data.items.length&&!cursor)empty(list,'Sin agentes','No hay agentes disponibles para tu cuenta.');
        for(const agent of data.items){
          const card=node('details',undefined,'panel schedule-agent-card'),summary=node('summary');
          summary.append(node('strong',agent.name),node('p','Propietario #'+agent.owner_id,'muted'));
          summary.append(node('p',agent.next_run_at?'Próxima corrida: '+date(agent.next_run_at):'Sin corrida habilitada','help'));
          for(const task of (agent.tasks||[])){summary.append(node('strong',task.name),taskScheduleCell(task));}
          agent.schedules.filter(s=>s.legacy_task_id==null).forEach(s=>summary.append(node('p','Programación heredada sin tarea asignada: '+scheduleText(s)+(s.enabled?'':' · Deshabilitada'),'help')));
          if(!agent.schedules.length)summary.append(node('p','Sin programaciones','help'));
          card.append(summary);const content=node('div');card.append(content);list.append(card);
          let loaded=false;
          card.addEventListener('toggle',async()=>{
            if(!card.open||loaded)return;loaded=true;content.replaceChildren(node('p','Cargando historial…','muted'));
            try{
              const detail=await api('/schedule-view/'+agent.id);content.replaceChildren();
              content.append(node('h3','Programaciones'));
              taskScheduleTable(content,detail.tasks||[],agent.id,context.session.admin,agent.can_edit!==false);
              const mapped=new Set((detail.tasks||[]).map(task=>task.id));
              const legacy=detail.schedules.filter(schedule=>!mapped.has(schedule.legacy_task_id));
              if(legacy.length){content.append(node('h3','Programaciones heredadas sin asociación inequívoca'));table(content,['Horario','Estado','Próxima ejecución'],legacy.map(s=>[scheduleText(s),s.enabled?'Habilitada':s.preference_only?'Preferencia guardada; ejecución deshabilitada':'Deshabilitada',scheduleDate(s.next_run_at,s.timezone)]));}
              content.append(node('h3','Historial de ejecuciones'));
              if(detail.jobs.length)table(content,['Creada','Estado','Inicio','Finalización','Motivo'],detail.jobs.map(j=>[date(j.created_at),j.state,date(j.started_at),date(j.finished_at),j.error_code?(errors[j.error_code]||j.error_code):'—']));
              else content.append(node('p','Sin ejecuciones.'));
              content.append(node('h3','Historial de programación'));
              if(detail.events.length)table(content,['Fecha','Acción','Motivo','Actor'],detail.events.map(e=>[date(e.created_at),e.action,e.reason_code?(errors[e.reason_code]||e.reason_code)+' ('+e.reason_code+')':'—',e.actor_type+' · '+e.actor_id]));
              else content.append(node('p','Sin eventos registrados.'));
              content.append(node('p','Hasta '+detail.list_limit+' registros recientes por historial.','help'));
            }catch(e){loaded=false;content.replaceChildren();showError(e,content);}
          });
        }
        cursor=data.next_cursor;more.hidden=!cursor;
      }catch(e){showError(e,list);}finally{more.disabled=false;}
    }
    await load();
  }
  async function executionsPage() {
    heading('Ejecuciones', 'Historial real de los trabajos de tu cuenta.');
    const launch = node('section', undefined, 'panel');
    launch.append(node('h2', 'Ejecutar prueba interna'),
      node('p', 'Solo usa el adaptador local. No llama a OpenAI ni a Apify. El resultado queda sin verificar.', 'help'));
    const launchForm = node('form', undefined, 'manual-execution-form');
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
          max_corrections: Math.min(2, selected.limits.max_corrections)
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
              'quiet') : j.state === 'REVIEWING' ? btn('Revisar resultado', () => reviewResult(j.id), 'quiet') : j.state === 'CORRECTION_REQUIRED' ? btn('Ver corrección', () => correctionHistory(j.id), 'quiet') : j.error_code === 'no_sources_available' ? 'Ninguna fuente está disponible' : 'Todavía no disponible'
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
  async function correctionHistory(id) {
    const dialog = document.querySelector('#result-dialog');
    const host = document.querySelector('#result-content');
    host.replaceChildren(node('p', 'Cargando historial…'));
    dialog.showModal();
    try {
      const data = await api('/jobs/' + encodeURIComponent(id) + '/review-history');
      host.replaceChildren(node('h3', 'Historial de correcciones'));
      host.append(node('p', 'Correcciones solicitadas: ' + data.correction_count +
        ' / ' + data.max_corrections));
      data.results.forEach(r => {
        host.append(node('h4', 'Versión ' + r.version),
          node('p', r.payload.summary || 'Sin resumen'),
          node('p', 'Evidencia: ' + r.evidence_status));
        if (Array.isArray(r.payload.warnings)) r.payload.warnings.forEach(w => host.append(banner(w)));
      });
      data.reviews.forEach(r => host.append(node('p', 'Revisión ' + r.cycle + ': ' +
        r.decision + ' · Motivos: ' + r.reason_codes.join(', '))));
      if (data.state === 'CORRECTION_REQUIRED') {
        const retry = btn('Reprocesar prueba interna', async () => {
          if (!window.confirm('¿Volver a ejecutar la prueba local? No se usan APIs externas.')) return;
          retry.disabled = true;
          try {
            await api('/jobs/' + encodeURIComponent(id) + '/retry-correction', {
              method: 'POST', body: JSON.stringify({expected_revision: data.revision})
            });
            dialog.close();
            window.location.reload();
          } catch (e) { notify(e.message || 'No se pudo reprocesar.'); retry.disabled = false; }
        }, 'primary');
        if (data.correction_count > data.max_corrections || data.correction_count > 2) {
          retry.disabled = true;
          host.append(banner('Este trabajo no permite más correcciones. Creá una nueva prueba.'));
        }
        host.append(retry);
      }
    } catch (e) { showError(e, host); }
  }

  async function reviewResult(id) {
    const dialog = document.querySelector('#result-dialog');
    const host = document.querySelector('#result-content');
    host.replaceChildren(node('p', 'Cargando revisión…'));
    dialog.showModal();
    try {
      const data = await api('/jobs/' + encodeURIComponent(id) + '/review');
      const report = data.review;
      host.replaceChildren(node('h3', 'Resultado en revisión'));
      const payload = data.result || {};
      host.append(node('p', payload.summary || 'Sin resumen disponible.'));
      if (Array.isArray(payload.findings) && payload.findings.length) {
        const findings = node('ul');
        payload.findings.forEach(f => findings.append(node('li', f.text || JSON.stringify(f))));
        host.append(node('h4', 'Hallazgos'), findings);
      }
      if (Array.isArray(payload.warnings)) payload.warnings.forEach(w => host.append(banner(w)));
      host.append(node('h4', 'Informe del verificador'));
      const status = node('p', 'Estructura: ' +
        (report.report.structurally_valid ? 'válida' : 'inválida') +
        ' · Evidencia: ' + report.evidence_status +
        ' · Aprobación: ' + (report.ready_for_approval ? 'permitida' : 'bloqueada'));
      host.append(status);
      if (report.report.reason_codes.length)
        host.append(node('p', 'Observaciones: ' + report.report.reason_codes.join(', ')));
      const actions = node('div', undefined, 'review-actions');
      const reason = field(host, 'Motivo (código en mayúsculas, sin espacios)',
        'review-reason', 'text', 'RESULTADO_NO_VERIFICADO',
        {maxLength: 80});
      reason.pattern = '[A-Z0-9_]+';
      const submit = async (decision) => {
        if (!window.confirm('¿Confirmás la decisión ' + decision + '? Esta acción cambia el estado del trabajo.'))
          return;
        const code = reason.value.trim();
        if (decision !== 'APPROVED' && !/^[A-Z0-9_]{1,80}$/.test(code)) {
          notify('Ingresá un motivo válido, por ejemplo RESULTADO_NO_VERIFICADO.');
          return;
        }
        actions.querySelectorAll('button').forEach(b => b.disabled = true);
        try {
          await api('/jobs/' + encodeURIComponent(id) + '/review', {
            method: 'POST',
            body: JSON.stringify({
              decision, reason_codes: decision === 'APPROVED' ? [] : [code],
              expected_revision: report.revision
            })
          });
          dialog.close();
          notify('Decisión registrada: ' + decision + '. Actualizá el historial.');
          window.location.reload();
        } catch (e) {
          notify(e.message || 'No se pudo registrar la revisión.');
          actions.querySelectorAll('button').forEach(b => b.disabled = false);
        }
      };
      actions.append(
        btn('Solicitar corrección', () => submit('CORRECTION_REQUIRED'), 'secondary'),
        btn('Rechazar', () => submit('REJECTED'), 'secondary'),
        btn('Aprobar', () => submit('APPROVED'), 'primary')
      );
      actions.lastChild.disabled = !report.ready_for_approval;
      host.append(actions);
    } catch (e) {
      showError(e, host);
    }
  }
  async function result(id, admin = false) {
    const dialog = document.querySelector('#result-dialog'),
      host = document.querySelector('#result-content');
    host.replaceChildren(node('p', 'Cargando resultado…'));
    dialog.showModal();
    try {
      const data = await api((admin ? '/admin' : '') + '/jobs/' + id + '/result');
      host.replaceChildren(node('p', data.result.summary));
      if (data.evidence_status === 'UNVERIFIED') host.prepend(banner(
        'Resultado informativo no verificado. No implica aprobación ni autorización de publicación.'));
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

  const integrationErrors = {
    integration_not_configured: 'Guardá una configuración válida antes de activar.',
    integration_encryption_unavailable: 'Falta la clave maestra de cifrado o no permite abrir la credencial guardada.',
    invalid_credential: 'Ingresá una credencial válida, sin espacios.',
    credential_required: 'Ingresá la credencial del proveedor.',
    wrong_credential_system: 'El token de clientes DPIA Agents no sirve como credencial de este proveedor.',
    invalid_provider_url: 'La URL debe usar HTTPS y un host permitido por el servidor.',
    invalid_model: 'El identificador del modelo no es válido.',
    model_not_configured: 'El modelo debe estar autorizado en la configuración del servidor.',
    invalid_credentials: 'Credenciales inválidas, vencidas o revocadas.',
    insufficient_permissions: 'Permisos insuficientes para utilizar el proveedor.',
    provider_resource_unavailable: 'El modelo o recurso no está disponible para esta cuenta.',
    provider_invalid_response: 'El proveedor devolvió una respuesta que no cumple el contrato.',
    provider_timeout: 'La conexión superó el tiempo de espera.',
    provider_unavailable: 'No se pudo conectar con el proveedor.',
    provider_rate_limited: 'El proveedor limitó las solicitudes. Reintentá más tarde.',
    worker_unavailable: 'Worker no disponible. Revisá su proceso y su última señal.',
    adapter_not_implemented: 'El adaptador requerido no está implementado.',
    integration_disabled: 'La integración está desactivada.',
    provider_not_authorized: 'Autorizá explícitamente este proveedor para el agente.',
    tool_not_authorized: 'El agente no tiene esta herramienta.',
    agent_budget_exceeded: 'Los límites del agente no alcanzan para esta prueba.',
    cost_confirmation_required: 'La búsqueda requiere confirmación explícita del posible costo.',
    revision_conflict: 'La configuración cambió. Actualizá los datos antes de repetir la acción.'
  };
  Object.assign(errors, integrationErrors);

  async function mcpSection(){
    const section=node('section',undefined,'panel'),list=node('div'),formHost=node('div'),status=node('p',undefined,'help');
    status.setAttribute('role','status');section.id='mcp-servers';
    section.append(node('h2','Servidores MCP'),node('p','Catálogo central de herramientas MCP. Los agentes utilizan las herramientas de bajo riesgo habilitadas según las políticas del motor. Descubrir no ejecuta herramientas.','help'),btn('Agregar servidor MCP',()=>edit()),status,formHost,list);root.append(section);
    const action=(path,method,body)=>api('/mcp'+path,{method,body:JSON.stringify(body),headers:{'X-DPIA-Action':'manage-mcp'}});
    let cursor=null,busy=false;
    const more=btn('Cargar más servidores',()=>load(false));section.append(more);
    async function run(fn){if(busy)return;busy=true;section.setAttribute('aria-busy','true');section.querySelectorAll('button').forEach(b=>b.disabled=true);status.textContent='Procesando…';try{await fn();status.textContent='Cambio confirmado.';await load();}catch(e){status.textContent=e.message;status.className='error';}finally{busy=false;section.removeAttribute('aria-busy');section.querySelectorAll('button').forEach(b=>b.disabled=false);}}
    async function load(reset=true){if(reset){list.replaceChildren();cursor=null;}const data=await api('/mcp/servers?limit=25'+(cursor?'&after='+encodeURIComponent(cursor):''));
      if(!data.items.length&&!cursor)list.append(node('p','No hay servidores MCP registrados.','help'));
      for(const server of data.items){const card=node('article',undefined,'mcp-server agent-card'),actions=node('div',undefined,'agent-actions');card.dataset.mcpServer=server.id;
        card.append(node('h3',server.name),node('p',server.description||'Sin descripción'),node('p',server.endpoint_url,'help'),node('p',(server.enabled?'Activo':'Pausado')+' · '+server.last_health_status+' · '+(server.last_error_code||'Sin errores')+' · Revisión '+server.revision));
        card.append(node('p','Última comprobación: '+date(server.last_checked_at),'help'));
        actions.append(btn('Editar configuración',()=>edit(server)),btn('Probar conexión',()=>run(()=>action('/servers/'+server.id+'/test','POST',{expected_revision:server.revision}))),btn('Descubrir herramientas',()=>run(()=>action('/servers/'+server.id+'/discover','POST',{expected_revision:server.revision}))),btn(server.enabled?'Pausar MCP':'Activar MCP',()=>run(()=>action('/servers/'+server.id+'/status','PATCH',{expected_revision:server.revision,enabled:!server.enabled}))),btn('Eliminar MCP',()=>{if(window.confirm('¿Eliminar este servidor MCP? Se revocarán sus herramientas y se conservará el historial.'))run(()=>action('/servers/'+server.id,'DELETE',{expected_revision:server.revision,confirm:true}));},'agent-delete'));
        card.append(actions);const details=node('details'),summary=node('summary','Herramientas y permisos'),host=node('div');details.append(summary,host);card.append(details);list.append(card);
        details.addEventListener('toggle',async()=>{if(!details.open)return;host.replaceChildren(node('p','Cargando herramientas…'));try{const data=await api('/mcp/servers/'+server.id+'/tools');host.replaceChildren();
          for(const tool of data.items){const row=node('section',undefined,'panel'),risk=document.createElement('select');['LOW','MEDIUM','HIGH','CRITICAL'].forEach(value=>{const option=node('option',value);option.value=value;risk.append(option);});risk.value=tool.risk_level;risk.setAttribute('aria-label','Nivel de riesgo de '+tool.tool_name);risk.disabled=!context.session.scopes.includes('mcp:approve');
            row.append(node('h4',tool.tool_name),node('p',tool.description||'Sin descripción'),node('code',tool.catalog_id),risk,btn(tool.enabled?'Deshabilitar herramienta':'Habilitar herramienta',()=>{if(tool.risk_level==='HIGH'||tool.risk_level==='CRITICAL'){if(!confirm('Esta herramienta tiene riesgo alto. ¿Confirmás habilitarla? Se aplicarán las políticas de seguridad del motor.'))return;}run(()=>action('/tools/'+tool.id,'PATCH',{expected_revision:data.catalog_version,enabled:!tool.enabled,risk_level:risk.value}));}));
            host.append(row);
          }
          if(!data.items.length)host.append(node('p','No hay herramientas descubiertas.'));
        }catch(e){host.replaceChildren(node('p',e.message,'error'));}});
      }cursor=data.next_cursor;more.hidden=!cursor;
    }
    function edit(server=null){
      const form=node('form',undefined,'panel'),grid=node('div',undefined,'form-grid');form.append(node('h3',server?'Editar servidor MCP':'Agregar servidor MCP'),grid);
      const name=field(grid,'Nombre MCP','mcp-name','text',server?.name,{required:true,maxLength:150}),description=field(grid,'Descripción MCP','mcp-description','textarea',server?.description,{maxLength:4000}),url=field(grid,'URL HTTPS del MCP','mcp-url','url',server?.endpoint_url,{required:true,maxLength:2048}),auth=field(grid,'Autenticación MCP','mcp-auth','select',server?.auth_type||'none',{values:['none','bearer','header']}),credential=field(grid,'Credencial MCP (vacía conserva la actual)','mcp-credential','password','',{maxLength:8192,autocomplete:'new-password'}),timeout=field(grid,'Timeout MCP (segundos)','mcp-timeout','number',server?.timeout_seconds||15,{min:1,max:120,required:true}),priority=field(grid,'Prioridad MCP','mcp-priority','number',server?.priority??100,{min:-32768,max:32767,required:true});
      const template=field(grid,'Plantillas JSON por herramienta (nombre MCP → argumentos)','mcp-template','textarea',JSON.stringify(server?.connection_template || {},null,2),{maxLength:65536});
      template.parentElement.className='full';
      form.append(node('p','Se guarda pausado. El registro prueba la conexión y descubre herramientas, sin invocarlas. Autenticación header utiliza X-API-Key.','help'));const save=node('button','Guardar MCP','primary');save.type='submit';form.append(save,btn('Cancelar',()=>formHost.replaceChildren()));
      form.onsubmit=event=>{event.preventDefault();const body={name:name.value,description:description.value,endpoint_url:url.value,transport:'streamable_http',auth_type:auth.value,enabled:false,timeout_seconds:Number(timeout.value),priority:Number(priority.value)};
        if(credential.value)body.credential=auth.value==='header'?{name:'X-API-Key',value:credential.value}:credential.value;
        try { body.connection_template=JSON.parse(template.value); if(!body.connection_template || Array.isArray(body.connection_template) || typeof body.connection_template!=='object' || Object.values(body.connection_template).some(v=>!v || Array.isArray(v) || typeof v!=='object')) throw Error(); }
        catch (_) { status.textContent='La plantilla debe ser un objeto JSON que asocie nombres de herramientas con objetos de argumentos.'; status.className='error'; return; }
        if(server)body.expected_revision=server.revision;
        run(async()=>{await action('/servers'+(server?'/'+server.id:''),server?'PATCH':'POST',body);credential.value='';formHost.replaceChildren();});};formHost.replaceChildren(form);name.focus();
    }
    await load();
  }
  async function integrationsPage() {
    heading('Integraciones', 'Configuración, conexión y habilitación independiente de proveedores.');
    const dev = node('section', undefined, 'panel');
    const portalLink = link('Abrir portal API', '/developers');
    delete portalLink.dataset.nav; // Standalone Flask page, outside the workspace router.
    dev.append(node('h2', 'API / Desarrolladores'), node('p', 'Endpoints, clientes API y permisos.'), portalLink);
    root.append(dev);
    if(context.session.mcp_manage)await mcpSection();
    if (!context.session.admin) {
      root.append(banner('La administración de integraciones requiere una sesión de administrador.'));
      return;
    }
    const data = await api('/integrations');
    const cards = node('div', undefined, 'cards');
    root.append(cards);
    const operation = (id, action, body, method = 'POST', extraHeaders = {}) => api('/integrations/' + id + action, {
      method, body: JSON.stringify(body), headers: {'X-DPIA-Action': 'manage-integrations', ...extraHeaders}
    });
    for (const initial of data.items) {
      let state = initial, busy = false;
      const card = node('article', undefined, 'agent-card integration-card');
      card.dataset.provider = initial.id;
      cards.append(card);
      const title = initial.id === 'openai' ? 'OpenAI' : 'DPIA Scraper';
      async function refresh() {
        const latest = (await api('/integrations/' + initial.id + '/health')).integration;
        if (latest.revision >= state.revision) state = latest;
        draw();
      }
      async function act(action) {
        if (busy) return;
        busy = true; draw();
        try {
          const result = await operation(state.id, '/' + action, {expected_revision: state.revision});
          state = result.integration;
          if (result.error) notify(integrationErrors[result.error] || 'La verificación falló.');
          else notify(action === 'disable' ? 'Integración desactivada. Las llamadas ya iniciadas podrán finalizar.' :
            action === 'enable' ? 'Integración activada.' : 'Verificación completada sin ejecutar tareas.');
        } catch (e) {
          if (e.data?.integration) state = e.data.integration;
          notify(e.message);
        } finally {
          busy = false; draw();
        }
      }
      function draw() {
        card.replaceChildren(); card.setAttribute('aria-busy', String(busy));
        const top = node('div', undefined, 'card-top');
        top.append(icon('integration', 'agent-icon'), badge(state.enabled ? 'ENABLED' : 'Desactivado'));
        const diagnostic = !state.credential_present ? 'Sin configurar' : !state.checked_at ? 'Configurado' :
          state.authenticated === false ? 'Credenciales inválidas' : state.last_error === 'insufficient_permissions' ?
          'Permisos insuficientes' : state.healthy && state.authenticated && state.permissions_ok ? 'Conectado' : 'Error de conexión';
        const label = node('label', undefined, 'integration-toggle'), toggle = node('input');
        toggle.type = 'checkbox'; toggle.setAttribute('role', 'switch'); toggle.checked = state.enabled;
        toggle.disabled = busy; toggle.setAttribute('aria-label', 'Activar / Desactivar API ' + title);
        toggle.onchange = () => act(state.enabled ? 'disable' : 'enable');
        label.append(toggle, node('span', 'Activar / Desactivar API'));
        const buttons = node('div', undefined, 'actions');
        const test = btn(busy ? 'Verificando…' : 'Probar conexión', () => act('test'));
        const configure = btn('Configurar', () => configureModal());
        test.disabled = configure.disabled = busy;
        buttons.append(test, configure);
        card.append(top, node('h3', title), node('p', state.provider, 'muted'), label,
          node('p', diagnostic, 'integration-diagnostic'),
          node('p', 'Worker ' + state.capability + ': ' + (state.worker_available ? 'Disponible' : 'Worker no disponible')),
          node('p', 'Adaptador: ' + (state.adapter_implemented ? 'Implementado' : 'Pendiente')),
          node('p', 'Última conexión exitosa: ' + (state.last_success_at ? date(state.last_success_at) : 'Sin registro')),
          node('p', 'Última prueba: ' + (state.checked_at ? date(state.checked_at) : 'Sin registro')));
        if (state.latency_ms !== null) card.append(node('p', 'Latencia: ' + state.latency_ms + ' ms'));
        if (state.last_error) card.append(banner(integrationErrors[state.last_error] || 'Error de conexión.'));
        card.append(buttons, node('small', initial.id === 'openai' ?
          'El diagnóstico consulta el modelo; no genera contenido ni garantiza cuota o permisos de inferencia.' :
          'El diagnóstico verifica API y permisos; no ejecuta scraping ni comprueba Apify.'));
        if (state.id === 'dpia-scraper') {
          const caps = node('details'); caps.append(node('summary', 'Ver capacidades'));
          for (const marketplace of ['amazon', 'mercadolibre', 'ebay', 'aliexpress']) {
            const present = Object.hasOwn(state.marketplaces, marketplace);
            caps.append(node('p', marketplace + ': catálogo ' + (present ? 'disponible' : 'sin confirmar') +
              '; adaptador ' + (marketplace === 'amazon' ? 'implementado' : 'pendiente') + '; búsqueda real no certificada por este diagnóstico.'));
          }
          const trial = btn('Ejecutar búsqueda de prueba', () => trialModal().catch(e => notify(e.message)));
          trial.disabled = busy || !state.enabled || !state.worker_available;
          card.append(caps, trial);
        }
      }
      function modal(name) {
        const dialog = node('dialog', undefined, 'integration-dialog');
        dialog.id = state.id + '-dialog'; dialog.setAttribute('aria-label', name);
        const heading = node('h2', name), message = node('p'); message.setAttribute('role', 'status');
        dialog.append(heading, message); document.body.append(dialog);
        dialog.addEventListener('close', () => { dialog.querySelectorAll('input[type=password]').forEach(x => x.value = ''); dialog.remove(); });
        dialog.showModal();
        return {dialog, message};
      }
      function inputField(form, text, type, value, options = {}) {
        const label = node('label', text), input = node('input');
        input.type = type; input.value = value ?? ''; Object.assign(input, options);
        label.append(input); form.append(label); return input;
      }
      async function configureModal() {
        const {dialog, message} = modal('Configurar ' + title), form = node('form');
        form.autocomplete = 'off'; dialog.append(form);
        let url, model, maxTokens, saving = false;
        if (state.id === 'dpia-scraper') url = inputField(form, 'URL de la API', 'url', state.config.base_url, {required: true});
        const credential = inputField(form, state.id === 'openai' ? 'API Key' : 'Token Bearer', 'password', '', {
          required: !state.credential_present, maxLength: 4096, autocomplete: 'new-password',
          placeholder: state.credential_present ? 'Dejar vacío para conservar la credencial' : ''});
        const reveal = btn('Mostrar / Ocultar', () => credential.type = credential.type === 'password' ? 'text' : 'password', 'quiet');
        form.append(reveal);
        dialog.addEventListener('close', () => credential.value = '');
        if (state.id === 'openai') {
          const label = node('label', 'Modelo configurado'); model = node('select'); model.required = true;
          model.append(new Option('Seleccioná un modelo', ''));
          for (const id of state.available_models) model.append(new Option(id, id));
          model.value = state.config.model; label.append(model); form.append(label);
          maxTokens = inputField(form, 'Límite de tokens de salida por ejecución', 'number', state.config.max_output_tokens, {min: 16, max: 16000, required: true});
        } else form.append(node('p', 'Permisos confirmados: ' + (state.permissions.join(', ') || 'Sin verificar')),
          node('small', 'Se requieren scraper:read y scraper:write. La credencial debe proceder de DPIA Scraper.'));
        const timeout = inputField(form, 'Timeout (segundos)', 'number', state.config.timeout_seconds,
          {min: state.id === 'dpia-scraper' ? 90 : 5, max: 180, required: true});
        form.append(node('p', 'Guardar desactiva la integración hasta verificar y activar la nueva configuración.'));
        const actions = node('div', undefined, 'actions'), save = btn('Guardar', null, 'primary'), cancel = btn('Cancelar', () => dialog.close());
        save.type = 'submit'; actions.append(save, cancel); form.append(actions);
        form.onsubmit = async event => {
          event.preventDefault(); if (saving) return; saving = true; save.disabled = cancel.disabled = true;
          const config = state.id === 'openai' ? {model: model.value, timeout_seconds: Number(timeout.value), max_output_tokens: Number(maxTokens.value)} :
            {base_url: url.value, timeout_seconds: Number(timeout.value)};
          const body = {expected_revision: state.revision, config};
          if (credential.value) body.credential = credential.value;
          credential.value = ''; message.textContent = 'Guardando…';
          try {
            state = (await operation(state.id, '', body, 'PUT')).integration;
            dialog.close(); draw(); notify('Configuración guardada. Activá la API cuando esté lista.');
          } catch (e) { message.textContent = e.message; }
          finally { delete body.credential; saving = false; save.disabled = cancel.disabled = false; }
        };
        const assignments = node('section'); assignments.append(node('h3', 'Autorizar mis agentes'));
        dialog.append(assignments);
        try {
          const agents = (await api('/integrations/' + state.id + '/agents')).items;
          if (!agents.length) assignments.append(node('p', 'No hay agentes propios. Creá uno desde Mis agentes.'));
          if (!state.credential_present) assignments.append(node('p', 'Guardá primero la credencial para autorizar agentes.'));
          for (const agent of agents) {
            const row = node('div'), description = node('p');
            const updateDescription = () => description.textContent = agent.name + ': ' + (!agent.has_capability ?
              'falta la herramienta del proveedor.' : agent.authorized ? 'autorizado.' : 'sin autorización.');
            updateDescription(); row.append(description);
            if (!agent.has_capability) {
              row.append(link('Asignar herramienta', '/agents/' + agent.id + '/edit', 'secondary'));
            } else {
              const authorize = btn(agent.authorized ? 'Quitar autorización' : 'Autorizar agente', async () => {
                authorize.disabled = true;
                try {
                  await operation(state.id, '/agents/' + agent.id, {authorized: !agent.authorized, expected_revision: state.revision}, 'PUT');
                  agent.authorized = !agent.authorized; updateDescription();
                  authorize.textContent = agent.authorized ? 'Quitar autorización' : 'Autorizar agente';
                } catch (e) { message.textContent = e.message; }
                finally { authorize.disabled = !state.credential_present; }
              });
              authorize.disabled = !state.credential_present; row.append(authorize);
            }
            assignments.append(row);
          }
        } catch (e) { assignments.append(node('p', e.message)); }
      }
      async function trialModal() {
        const {dialog, message} = modal('Búsqueda de prueba · DPIA Scraper'), form = node('form');
        dialog.append(form);
        form.append(banner('Puede consumir créditos de Apify. Una consulta Amazon, una llamada y hasta 10 resultados del proveedor. No hay un tope monetario por solicitud documentado; configurá un presupuesto en el proveedor antes de continuar.'));
        const agents = (await api('/integrations/dpia-scraper/agents')).items;
        const label = node('label', 'Agente autorizado'), select = node('select'); select.required = true;
        select.append(new Option('Seleccioná un agente', ''));
        agents.forEach(x => select.append(new Option(x.name + (!x.has_capability ? ' · falta dpia.amazon.search' : !x.authorized ? ' · sin autorización' : !x.enabled ? ' · deshabilitado' : ''), x.id))); label.append(select); form.append(label);
        const countries = {'argentina':'Argentina','italia':'Italia','espana':'España','polonia':'Polonia','mexico':'México','uruguay':'Uruguay'};
        const countryLabel = node('label', 'País'), country = node('select'); country.required = true;
        for (const key of state.marketplaces.amazon || []) country.append(new Option(countries[key], countries[key]));
        countryLabel.append(country); form.append(countryLabel);
        const query = inputField(form, 'Consulta', 'text', '', {required: true, maxLength: 500});
        const count = inputField(form, 'Máximo de productos conservados (no limita el costo externo)', 'number', 5, {required: true, min: 1, max: 10});
        const confirm = inputField(form, 'Confirmo el posible costo y que revisé el presupuesto del proveedor', 'checkbox', '', {required: true});
        const send = btn('Confirmar y ejecutar una búsqueda', null, 'primary'); send.type = 'submit';
        form.append(send, btn('Cancelar', () => dialog.close()));
        let sending = false;
        const selectionMessage = node('p'), editAgent = link('Configurar agente', '/agents', 'secondary');
        const authorizeAgent = btn('Autorizar agente', async () => {
          const agent = agents.find(x => x.id === select.value);
          if (!agent || !agent.has_capability) return;
          authorizeAgent.disabled = true; select.disabled = true;
          try {
            await operation(state.id, '/agents/' + agent.id, {authorized: true, expected_revision: state.revision}, 'PUT');
            agent.authorized = true;
            select.selectedOptions[0].textContent = agent.name + (agent.enabled ? '' : ' · deshabilitado');
            message.textContent = 'Agente autorizado.';
          } catch (e) { message.textContent = e.message; }
          finally { authorizeAgent.disabled = false; select.disabled = false; updateSelection(); }
        });
        const updateSelection = () => {
          const agent = agents.find(x => x.id === select.value);
          selectionMessage.textContent = !agents.length ? 'No hay agentes propios. Creá uno con dpia.amazon.search.' :
            !agent ? 'Seleccioná un agente.' : !agent.has_capability ? 'Asigná dpia.amazon.search desde la configuración del agente.' :
            !agent.authorized ? 'Este agente necesita autorización explícita para acceder a DPIA Scraper.' :
            !agent.enabled ? 'Habilitá el agente desde Mis agentes.' : 'Agente habilitado y autorizado.';
          authorizeAgent.hidden = !agent || !agent.has_capability || agent.authorized;
          editAgent.hidden = !agent || (agent.has_capability && agent.enabled);
          if (agent) editAgent.href = '/agents/' + agent.id + '/edit';
          send.disabled = sending || !agent || !agent.has_capability || !agent.authorized || !agent.enabled;
        };
        select.onchange = updateSelection;
        form.insertBefore(selectionMessage, send); form.insertBefore(authorizeAgent, send); form.insertBefore(editAgent, send);
        updateSelection();
        const key = crypto.randomUUID();
        form.onsubmit = async event => {
          event.preventDefault(); if (sending || send.disabled) return; sending = true; send.disabled = true;
          try {
            const result = await operation(state.id, '/trial', {expected_revision: state.revision, agent_id: select.value,
              query: query.value, country: country.value, max_products: Number(count.value), confirm_cost: confirm.checked},
              'POST', {'Idempotency-Key': key});
            form.remove(); message.textContent = 'Trabajo creado: ' + result.job.id + '. Estado: ' + (states[result.job.state] || result.job.state);
            dialog.append(node('p', 'Los resultados de búsqueda con estructura válida se entregan como información no verificada, sin aprobación ni publicación.'),
              link('Ver ejecuciones', '/executions'), btn('Cerrar', () => dialog.close()));
          } catch (e) { message.textContent = e.message; sending = false; updateSelection(); }
        };
      }
      draw();
      const timer = setInterval(() => {
        if (!card.isConnected) { clearInterval(timer); return; }
        if (!busy && !document.querySelector('.integration-dialog')) refresh().catch(() => {});
      }, 15000);
      abort.signal.addEventListener('abort', () => clearInterval(timer), {once: true});
    }
  }
  async function administrationPage() {
    if (!context.session.admin) {
      heading('Acceso restringido', 'Esta sección requiere una sesión de administrador.');
      return;
    }
    const data = await api('/admin/overview');
    heading('Administración', 'Supervisión global de agentes, trabajos y workers.',btn('Actualizar estado',render,'secondary'));
    root.append(banner(
      'La gestión de usuarios y roles está pendiente: todavía no existe una API de administración de usuarios.'
      ));
    for (const [title, headers, items, rows] of [
        ['Agentes', ['Agente', 'Propietario', 'Configuración', 'Actividad', 'Pausa'], data.agents, data.agents.map(
            a => [a.name, 'Usuario ' + a.owner_id, badge(a.configuration_state), badge(a.activity_state), adminPauseCell(a)]
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
    const taskSection=node('section',undefined,'panel'),taskHost=node('div');
    taskSection.append(node('h2','Tareas configuradas'),taskHost);root.append(taskSection);
    let taskCursor=null;
    const more=btn('Cargar más tareas',loadTasks,'secondary');taskSection.append(more);
    async function loadTasks(){more.disabled=true;try{
      const tasks=await api('/admin/configured-tasks?limit=25'+(taskCursor?'&after='+taskCursor:''));
      if(!tasks.items.length&&!taskCursor)empty(taskHost,'Sin tareas','No hay tareas configuradas.');
      if(tasks.items.length)table(taskHost,['Tarea'],tasks.items.map(t=>{
        const cell=node('div');cell.append(link(t.name,'/administration/agents/'+t.agent_id+'/tasks/'+t.id+'/edit','quiet'),node('p',t.agent_name+' · Usuario '+t.owner_id,'help'));return [cell];
      }));
      taskCursor=tasks.next_cursor;more.hidden=!taskCursor;
    }catch(e){showError(e,taskHost);}finally{more.disabled=false;}}
    await loadTasks();
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
    document.querySelectorAll('.integration-dialog').forEach(d => d.close());
    document.querySelector('#result-dialog').close();
    document.querySelector('#result-content').replaceChildren();
    root.replaceChildren(node('p', 'Cargando tu espacio…', 'loading'));
    root.setAttribute('aria-busy', 'true');
    document.querySelector('#admin-nav').hidden = true;
    const path = location.pathname,
      active = path.startsWith('/administration') ? '/administration' : path.startsWith('/agents') ? '/agents' : path === '/admin/agents' ? '/administration' :
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
      else if (/^\/(administration\/)?agents\/[a-f0-9-]+\/tasks\/\d+\/edit$/.test(path)){const parts=path.split('/');const adminTask=parts[1]==='administration';await editor(parts[adminTask?3:2],parts[adminTask?5:4],adminTask);}
      else if (/^\/agents\/[a-f0-9-]+\/edit$/.test(path)) await editor(path.split('/')[2]);
      else if (path === '/schedules') await schedulesPage();
      else if (path === '/executions') await executionsPage();
      else if (path === '/integrations') await integrationsPage();
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
    document.querySelectorAll('.integration-dialog').forEach(d => d.close());
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
