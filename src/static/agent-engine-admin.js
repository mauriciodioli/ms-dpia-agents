(() => {
  'use strict';
  const root = '/api/agents/v1';
  const get = id => document.getElementById(id);
  let busy = false;
  function cell(value) { const td = document.createElement('td'); td.textContent = value ?? 'No disponible'; return td; }
  function table(id, rows, width, build) {
    const body = get(id); body.replaceChildren();
    for (const row of rows) { const tr = document.createElement('tr'); build(row).forEach(td => tr.append(td)); body.append(tr); }
    if (!rows.length) { const tr = document.createElement('tr'); const td = cell('Sin registros'); td.colSpan = width; td.className = 'empty'; tr.append(td); body.append(tr); }
  }
  function badge(text) { const td = cell(''); const span = document.createElement('span'); span.className = 'badge'; span.textContent = text; td.append(span); return td; }
  async function request(path) {
    const response = await fetch(root + path, {credentials:'same-origin', cache:'no-store'});
    if (!response.ok) throw new Error(response.status === 401 || response.status === 403 ? 'Se requiere una sesión administrativa activa.' : 'No se pudieron consultar los datos. La información anterior puede estar desactualizada.');
    return response.json();
  }
  async function showResult(id) {
    try { const data = await request('/admin/jobs/' + encodeURIComponent(id) + '/result'); get('result').textContent = JSON.stringify(data, null, 2); get('result-panel').hidden = false; get('result-panel').scrollIntoView({behavior:'smooth'}); }
    catch(error) { get('notice').textContent = error.message; get('notice').className = 'error'; }
  }
  function duration(job) {
    if (!job.started_at) return 'No disponible';
    const seconds = Math.max(0, Math.round(((job.finished_at ? Date.parse(job.finished_at) : Date.now()) - Date.parse(job.started_at))/1000));
    return seconds + ' s';
  }
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const data = await request('/admin/overview');
      get('counts').replaceChildren();
      const groups = [['Pendientes',['CREATED','SCHEDULED','QUEUED']],['En ejecución',['RUNNING']],['En revisión',['REVIEWING','CORRECTION_REQUIRED']],['Completados',['DELIVERED']],['Fallidos',['FAILED']]];
      for (const [name, states] of groups) { const card = document.createElement('div'); card.className='card'; const label = document.createElement('span'); label.textContent=name; const value = document.createElement('strong'); value.textContent=states.reduce((n,state)=>n+(data.jobs_by_state[state]||0),0); card.append(label,value); get('counts').append(card); }
      table('agents',data.agents,5,a=>[cell(a.name),cell(a.owner_id),badge(a.configuration_state),badge(a.activity_state),cell(a.timezone)]);
      table('jobs',data.jobs,8,j=>{const result=cell('No publicado'); if(j.state==='DELIVERED'){const button=document.createElement('button');button.textContent='Ver resultado';button.type='button';button.addEventListener('click',()=>showResult(j.id));result.replaceChildren(button);}return [cell(j.id),cell(j.owner_id),badge(j.state),cell(j.progress===null?'No disponible':j.progress+' %'),cell(j.attempt_count),cell(duration(j)),cell(j.error_code||'—'),result];});
      table('workers',data.workers,4,w=>[cell(w.id),cell(w.capabilities.join(', ')),badge(w.availability),cell(w.heartbeat_at)]);
      table('usage',data.provider_usage,6,u=>[cell(u.provider_id),cell(u.calls),cell(u.input_tokens),cell(u.output_tokens),cell(u.cost),cell(u.currency)]);
      get('usage-status').textContent=data.provider_usage.length?'Mediciones confirmadas por los proveedores. Los importes desconocidos no se estiman.':'No hay mediciones verificables disponibles.';
      get('updated').textContent='Actualizado '+new Date(data.snapshot_at).toLocaleTimeString();
      get('notice').textContent='Datos consultados correctamente.';get('notice').className='';
    } catch(error) { get('notice').textContent=error.message;get('notice').className='error'; }
    finally { busy=false; }
  }
  get('refresh').addEventListener('click',refresh);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  setInterval(refresh,5000);refresh();
})();
