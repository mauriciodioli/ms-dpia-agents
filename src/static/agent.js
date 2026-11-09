/* Configuration-only UI. No scheduler, scraping, AI, notifications or point mutations. */
(()=>{
 const root=document.getElementById('agentContent');
 const TASKS={products:'Productos nuevos',prices:'Cambios de precios',suppliers:'Proveedores',local:'Oportunidades locales',jobs:'Oportunidades laborales',trends:'Tendencias'};
 const FREQUENCIES={daily:'Diario',twice:'Dos veces por semana',weekly:'Semanal'};
 const STATES={unconfigured:'No configurado',inactive:'Configurado e inactivo',active:'Activo',running:'Ejecutando',paused:'Pausado',insufficient:'Créditos insuficientes',error:'Error'};
 const STEPS=['Qué monitorear','Dónde y sobre qué','Cuándo','Límites y notificaciones','Confirmación'];
 let wizard=false,index=0,draft=null,record=null,identity=null,scopes=[],categories=[],cities=[],loading=false,loadSerial=0,controller=null,error='',serverRevision=0,serverReady=false,serverBusy=false,readSerial=0;
 const tr=text=>window.DPIAI18N?.translate(text)||text;
 const who=()=>typeof currentEmail==='string'?currentEmail:null;
 const key=()=> 'dpia-agent-config:v1:'+ (who()||'guest');
 function node(tag,text,className){const el=document.createElement(tag);if(text!==undefined){el.textContent=tr(text);el.dataset.i18n=text;}if(className)el.className=className;return el;}
 function raw(tag,text,className){const el=document.createElement(tag);el.textContent=text;el.dataset.catalogName='';if(className)el.className=className;return el;}
 function button(text,handler,className='action-button'){const el=node('button',text,className);el.type='button';if(handler)el.onclick=handler;return el;}
 function inputLabel(text,control){control.setAttribute('aria-label',tr(text));control.setAttribute('data-i18n-aria-label',text);const label=node('label',undefined,'agent-field');label.append(node('span',text),control);return label;}
 function select(items,value,change){const el=document.createElement('select');for(const [id,text,translate=true] of items){const option=translate?node('option',text):raw('option',text);option.value=id;el.append(option);}el.value=value;el.onchange=()=>change(el.value);return el;}
 function timeZone(){return Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC';}
 function validZone(value){try{new Intl.DateTimeFormat('en',{timeZone:value});return typeof value==='string';}catch(_){return false;}}
 function validLabels(value){return value===undefined||(Array.isArray(value)&&value.length<=500&&value.every(row=>row&&Number.isSafeInteger(row.id)&&row.id>0&&typeof row.name==='string'&&row.name.length<=500));}
 function valid(value){return value&&validLabels(value.scopeLabels)&&validLabels(value.categoryLabels)&&value.version===1&&Array.isArray(value.tasks)&&value.tasks.length>0&&value.tasks.every(t=>Object.hasOwn(TASKS,t))&&typeof value.country==='string'&&value.country.trim().length>0&&value.country.length<=100&&typeof value.city==='string'&&value.city.trim().length>0&&value.city.length<=100&&Array.isArray(value.scopes)&&value.scopes.length>0&&value.scopes.length<=500&&value.scopes.every(v=>Number.isSafeInteger(v)&&v>0)&&Array.isArray(value.categories)&&value.categories.length>0&&value.categories.length<=500&&value.categories.every(v=>Number.isSafeInteger(v)&&v>0)&&Object.hasOwn(FREQUENCIES,value.frequency)&&Array.isArray(value.days)&&value.days.every(v=>Number.isInteger(v)&&v>=0&&v<=6)&&new Set(value.days).size===value.days.length&&(value.frequency==='daily'||value.days.length===(value.frequency==='twice'?2:1))&&/^\d{2}:\d{2}$/.test(value.time)&&Number(value.time.slice(0,2))<24&&Number(value.time.slice(3))<60&&validZone(value.timezone)&&Number.isSafeInteger(value.points)&&value.points>=0&&value.points<=1000000&&['week','month'].includes(value.period)&&typeof value.notifications==='boolean';}
 function readLocalDraft(){try{const result=JSON.parse(localStorage.getItem(key())||'null');return valid(result)?result:null;}catch(_){return null;}}
 function defaults(){return {version:1,tasks:[],country:typeof country==='string'?country:'',city:typeof city==='string'?city:'',scopes:[...selected].map(Number),categories:[],frequency:'weekly',days:[1],time:'09:00',timezone:timeZone(),points:0,period:'month',notifications:false};}
 function weekday(day){return new Intl.DateTimeFormat(window.DPIAI18N?.language||'es',{weekday:'long',timeZone:'UTC'}).format(new Date(Date.UTC(2026,10,1+day)));}
 function feedback(parent){if(error){const el=node('p',error,'agent-feedback');el.setAttribute('role','alert');parent.append(el);}}
 function statusBadge(state){const el=node('span',STATES[state]||STATES.error,'agent-status');el.dataset.state=state;return el;}
 function storageNotice(){return node('p','La configuración se guarda en tu cuenta DPIA. Guardarla no activa el agente.','agent-notice');}
 function engineNotice(){const el=node('p','La activación, las pausas y los avisos reales requieren el servicio del agente. Todavía no hay ejecuciones ni cargos.','agent-notice');el.id='agentEngineNotice';return el;}
 function summary(config){
  const dl=document.createElement('dl');
  const names=(ids,list,field,saved)=>ids.map(id=>list.find(row=>row[field]===id)?.nombre||(saved||[]).find(row=>row.id===id)?.name||String(id)).join(', ');
  const rows=[['Tareas configuradas',config.tasks.map(id=>tr(TASKS[id])).join(', ')],['Ubicación',[config.city,config.country].filter(Boolean).join(', ')],['Ámbitos',names(config.scopes,scopes,'ambito_id',config.scopeLabels)],['Categorías',names(config.categories,categories,'categoria_id',config.categoryLabels)],['Frecuencia',tr(FREQUENCIES[config.frequency])],['Días',config.frequency==='daily'?tr('Todos los días'):config.days.map(weekday).join(', ')],['Horario',config.time+' · '+config.timezone],['Límite de puntos',String(config.points)+' / '+tr(config.period==='week'?'Por semana':'Por mes')],['Avisos de novedades',tr(config.notifications?'Solicitados, aún no disponibles':'Desactivados')]];
  for(const [label,value] of rows)dl.append(node('dt',label),raw('dd',value));return dl;
 }
 function executionControl(state){
  const text=state==='paused'?'Reanudar agente':['active','running'].includes(state)?'Pausar agente':'Activar agente';
  const control=button(text,null,'primary');control.disabled=true;control.setAttribute('aria-describedby','agentEngineNotice');return control;
 }
 function dashboard(){
  root.replaceChildren();wizard=false;
  const panel=node('div',undefined,record?'agent-summary':'agent-intro');
  if(who()&&!serverReady){
   if(serverBusy)panel.append(node('p','Cargando configuración del agente…','hint'));
   else panel.append(button('Reintentar',open));
   feedback(panel);root.append(panel);return;
  }
  panel.append(statusBadge(record?'inactive':'unconfigured'));
  if(!record){
   panel.append(node('h3','DPIA busca por vos'),node('p','Encontrá productos nuevos, cambios de precios, proveedores y oportunidades sin buscar todos los días'),button('Configurar mi agente',()=>who()?start():openAuth(),'primary'));
   if(who()&&readLocalDraft())panel.append(button('Recuperar borrador local',()=>start(readLocalDraft())));
   if(!who())panel.append(node('p','Iniciá sesión para guardar tu agente.','agent-notice'));
  }
  else{
   panel.append(summary(record));
   const dl=document.createElement('dl');for(const text of ['Próxima ejecución','Última ejecución','Resultados recientes','Puntos consumidos'])dl.append(node('dt',text),node('dd','Sin ejecuciones'));
   panel.append(dl);
   const actions=node('div',undefined,'agent-actions');actions.append(button('Editar configuración',()=>start()));
   actions.append(executionControl('inactive'));panel.append(actions);
  }
  panel.append(engineNotice(),storageNotice());feedback(panel);root.append(panel);window.DPIAI18N?.refresh();
 }
 async function json(url){const r=await fetch(url,{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('catalog');const data=await r.json();if(data.success!==true)throw Error('catalog');return data;}
 async function loadLocation(reloadCities=true){
  const serial=++loadSerial,owner=who();controller?.abort();controller=new AbortController();loading=true;error='';
  if(index===1&&wizard)renderStep();
  try{
   if(reloadCities){const data=await json('/api/catalogos/ciudades?'+new URLSearchParams({pais:draft.country}));if(serial!==loadSerial||owner!==who())return;cities=(data.ciudades||[]).map(row=>row.nombre);if(!cities.includes(draft.city))draft.city='';}
   if(draft.city){
    const data=await json('/api/catalogos/ubicacion?'+new URLSearchParams({pais:draft.country,ciudad:draft.city,idioma:window.DPIAI18N?.language||'es'}));
    if(serial!==loadSerial||owner!==who())return;
    scopes=data.ambitos||[];categories=data.categorias||[];
    draft.scopes=draft.scopes.filter(id=>scopes.some(row=>row.ambito_id===id));pruneCategories();
   }else{scopes=[];categories=[];draft.scopes=[];draft.categories=[];}
  }catch(e){if(e.name!=='AbortError'&&serial===loadSerial)error='No se pudo cargar el catálogo del agente. Reintentá.';}
  finally{if(serial===loadSerial&&owner===who()){loading=false;if(wizard&&index===1)renderStep();}}
 }
 function pruneCategories(){draft.categories=draft.categories.filter(id=>categories.some(row=>row.categoria_id===id&&row.ambito_ids.some(scope=>draft.scopes.includes(scope))));}
 function start(imported=null){
  if(!who()){openAuth();return;}
  if(!serverReady||serverBusy)return;
  identity=who();draft=record?structuredClone(record):imported?structuredClone(imported):defaults();wizard=true;index=0;error='';
  scopes=structuredClone(catalogAmbitos);categories=structuredClone(catalogCategorias);cities=draft.city?[draft.city]:[];
  renderStep();if(draft.country)loadLocation();
 }
 function choice(parent,text,checked,change,translated=true){const label=node('label',undefined,'agent-choice'),check=document.createElement('input');check.type='checkbox';check.checked=checked;check.onchange=()=>change(check.checked);label.append(check,translated?node('span',text):raw('span',text));parent.append(label);}
 function listHeading(parent,text){parent.append(node('h4',text,'agent-label'));const choices=node('div',undefined,'agent-choices agent-catalog');parent.append(choices);return choices;}
 function toggle(list,value,checked){if(checked&&!list.includes(value))list.push(value);if(!checked){const at=list.indexOf(value);if(at>=0)list.splice(at,1);}}
 function stepLocation(panel){
  const fields=node('div',undefined,'agent-fields');
  const countries=[...document.querySelectorAll('#countryList [data-country]')].map(el=>[el.dataset.country,el.textContent,false]);
  fields.append(inputLabel('País',select([['','Elegí un país'],...countries],draft.country,value=>{draft.country=value;draft.city='';draft.scopes=[];draft.categories=[];scopes=[];categories=[];cities=[];if(value)loadLocation();else renderStep();})),inputLabel('Ciudad',select([['','Elegí tu ciudad'],...cities.map(name=>[name,name,false])],draft.city,value=>{draft.city=value;draft.scopes=[];draft.categories=[];scopes=[];categories=[];loadLocation(false);})));
  panel.append(fields);
  if(loading){panel.append(node('p','Cargando catálogo…','hint'));return;}
  if(error){panel.append(button('Reintentar',()=>loadLocation()));return;}
  if(!draft.city){panel.append(node('p','Elegí un país y una ciudad para cargar las opciones.','hint'));return;}
  const scopeList=listHeading(panel,'Ámbitos');for(const item of scopes)choice(scopeList,item.nombre,draft.scopes.includes(item.ambito_id),checked=>{toggle(draft.scopes,item.ambito_id,checked);pruneCategories();renderStep();},false);
  const categoryList=listHeading(panel,'Categorías');const available=categories.filter(item=>item.ambito_ids.some(id=>draft.scopes.includes(id)));
  for(const item of available)choice(categoryList,item.nombre,draft.categories.includes(item.categoria_id),checked=>toggle(draft.categories,item.categoria_id,checked),false);
  if(!scopes.length||!available.length)panel.append(node('p','No hay opciones disponibles para esta selección.','hint'));
 }
 function stepWhen(panel){
  const fields=node('div',undefined,'agent-fields');const time=document.createElement('input');time.type='time';time.value=draft.time;time.oninput=()=>draft.time=time.value;
  const zones=[...new Set([timeZone(),draft.timezone,'UTC',...(Intl.supportedValuesOf?Intl.supportedValuesOf('timeZone'):[])])];
  fields.append(inputLabel('Frecuencia',select(Object.entries(FREQUENCIES),draft.frequency,value=>{draft.frequency=value;draft.days=value==='twice'?[1,4]:[1];renderStep();})),inputLabel('Horario',time),inputLabel('Zona horaria',select(zones.map(z=>[z,z,false]),draft.timezone,z=>draft.timezone=z)));panel.append(fields);
  if(draft.frequency!=='daily'){
   const days=listHeading(panel,draft.frequency==='twice'?'Elegí dos días':'Elegí un día');
   for(const day of [1,2,3,4,5,6,0])choice(days,weekday(day),draft.days.includes(day),checked=>toggle(draft.days,day,checked),false);
  }
  panel.append(node('p','El horario es una preferencia. No hay tareas programadas todavía.','agent-notice'));
 }
 function stepLimits(panel){
  const fields=node('div',undefined,'agent-fields'),points=document.createElement('input');points.type='number';points.min='0';points.max='1000000';points.step='1';points.value=draft.points;points.oninput=()=>draft.points=points.value===''?null:Number(points.value);
  fields.append(inputLabel('Presupuesto máximo de puntos',points),inputLabel('Período',select([['week','Por semana'],['month','Por mes']],draft.period,value=>draft.period=value)));panel.append(fields);
  choice(panel,'Recibir avisos de novedades',draft.notifications,value=>draft.notifications=value);
  panel.append(node('p','Las búsquedas externas pueden consumir puntos. Guardar esta configuración no descuenta puntos ni reserva saldo.','agent-notice'),node('p','Los avisos se guardan como preferencia; no se solicitará permiso ni se enviarán notificaciones en esta etapa.','agent-notice'));
 }
 function check(step){
  if(step===0&&!draft.tasks.length)return 'Seleccioná al menos una tarea.';
  if(step===1&&(loading||error||!draft.country||!draft.city||!draft.scopes.length||!draft.categories.length))return 'Elegí ubicación, ámbitos y categorías disponibles.';
  if(step===2&&(!/^\d{2}:\d{2}$/.test(draft.time)||!validZone(draft.timezone)||(draft.frequency!=='daily'&&draft.days.length!==(draft.frequency==='twice'?2:1))))return 'Revisá el horario y los días seleccionados.';
  if(step===3&&(!Number.isSafeInteger(draft.points)||draft.points<0||draft.points>1000000))return 'Ingresá un límite de puntos entero y no negativo.';
  return '';
 }
 async function save(){
  if(serverBusy)return;
  if(identity!==who()){error='La cuenta cambió. Volvé a abrir la configuración.';renderStep();return;}
  if(!who()){openAuth();return;}
  for(let step=0;step<4;step++){const issue=check(step);if(issue){index=step;error=issue;renderStep();return;}}
  const value={...structuredClone(draft),version:1,language:window.DPIAI18N?.language||'es'};
  for(const field of ['scopeLabels','categoryLabels','savedAt'])delete value[field];
  if(!valid(value)){error='La configuración guardada no es válida. Revisala antes de guardar.';renderStep();return;}
  const owner=who(),serial=++readSerial;serverBusy=true;error='';renderStep();
  try{
   const response=await fetch('/api/agente/configuracion',{method:'PUT',credentials:'same-origin',headers:{'Content-Type':'application/json','X-DPIA-Action':'configure-agent'},body:JSON.stringify({configuration:value,expected_revision:serverRevision}),signal:AbortSignal.timeout(60000)});
   const data=await response.json();
   if(owner!==who()||serial!==readSerial)return;
   if(response.status===401)openAuth();
   if(!response.ok||data.success!==true)throw Error(data.error||'No se confirmó el guardado del agente. Volvé a cargar su configuración.');
   if(!data.agent||!valid(data.agent.configuration)||!Number.isSafeInteger(data.agent.revision)||data.agent.revision<1||data.agent.state!=='inactive'||data.execution_available!==false)throw Error('La respuesta del agente no es válida. Volvé a cargar su configuración.');
   record=data.agent.configuration;serverRevision=data.agent.revision;serverReady=true;loadSerial++;controller?.abort();
   serverBusy=false;dashboard();
  }catch(e){
   if(owner===who()&&serial===readSerial){error=e.message&&e.name==='Error'?e.message:'No se confirmó el guardado del agente. Volvé a cargar su configuración.';serverBusy=false;renderStep();}
  }finally{if(owner===who()&&serial===readSerial)serverBusy=false;}
 }
 function renderStep(){
  root.replaceChildren();const panel=node('div',undefined,'agent-wizard'),progress=document.createElement('ol');progress.className='agent-progress';progress.setAttribute('aria-label',tr('Pasos'));
  for(let i=0;i<5;i++){const li=document.createElement('li');li.setAttribute('aria-label',(i+1)+' · '+tr(STEPS[i]));if(i===index)li.setAttribute('aria-current','step');if(i<index)li.className='agent-complete';progress.append(li);}panel.append(progress,raw('small',(index+1)+' / 5'));const heading=node('h3',STEPS[index]);heading.tabIndex=-1;panel.append(heading);
  if(index===0){const tasks=node('div',undefined,'agent-choices');for(const [id,text] of Object.entries(TASKS))choice(tasks,text,draft.tasks.includes(id),checked=>toggle(draft.tasks,id,checked));panel.append(tasks);}
  if(index===1)stepLocation(panel);if(index===2)stepWhen(panel);if(index===3)stepLimits(panel);
  if(index===4){panel.classList.add('agent-summary');panel.append(summary(draft),engineNotice(),storageNotice());}
  if(serverBusy){const status=node('p','Guardando configuración…','hint');status.setAttribute('role','status');panel.append(status);}
  feedback(panel);const actions=node('div',undefined,'agent-actions');
  actions.append(button('Cancelar',()=>{loadSerial++;controller?.abort();dashboard();}));
  if(index>0)actions.append(button('Anterior',()=>{index--;error='';renderStep();}));
  const next=button(index===4?'Guardar sin activar':'Siguiente',()=>{if(index===4){save();return;}const issue=check(index);if(issue){error=issue;renderStep();return;}error='';index++;renderStep();root.querySelector('h3').focus();},'primary');next.disabled=index===1&&loading;actions.append(next);
  if(index===4)actions.append(executionControl('inactive'));
  if(error&&index===4)actions.append(button('Volver a cargar configuración',open));
  panel.append(actions);if(serverBusy)panel.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);root.append(panel);window.DPIAI18N?.refresh();
 }
 async function open(){
  if(serverBusy&&identity===who())return;
  identity=who();const owner=who(),serial=++readSerial;record=null;serverRevision=0;serverReady=false;error='';
  loadSerial++;controller?.abort();loading=false;
  if(!owner){serverBusy=false;dashboard();return;}
  serverBusy=true;dashboard();
  try{
   const response=await fetch('/api/agente/configuracion',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000)});
   const data=await response.json();if(owner!==who()||serial!==readSerial)return;
   if(response.status===401)openAuth();
   if(!response.ok||data.success!==true)throw Error(data.error||'No se pudo cargar la configuración del agente.');
   if(data.execution_available!==false)throw Error('La respuesta del agente no es válida. Volvé a cargar su configuración.');
   if(data.agent!==null){
    if(!data.agent||!valid(data.agent.configuration)||!Number.isSafeInteger(data.agent.revision)||data.agent.revision<1||data.agent.state!=='inactive')throw Error('La respuesta del agente no es válida. Volvé a cargar su configuración.');
    record=data.agent.configuration;serverRevision=data.agent.revision;
   }
   serverReady=true;
  }catch(e){if(owner===who()&&serial===readSerial)error=e.name==='Error'?e.message:'No se pudo cargar la configuración del agente.';}
  finally{if(owner===who()&&serial===readSerial){serverBusy=false;dashboard();}}
 }
 new MutationObserver(()=>{if(identity!==who()){
  loadSerial++;readSerial++;controller?.abort();serverBusy=false;serverReady=false;serverRevision=0;
  identity=who();record=null;draft=null;wizard=false;root.replaceChildren();
  if(!document.getElementById('agentPage').hidden)open();
 }}).observe(document.getElementById('userBtn'),{childList:true,subtree:true,characterData:true});
 document.getElementById('languageSelect').addEventListener('change',()=>setTimeout(()=>{if(wizard){renderStep();if(draft.country&&draft.city)loadLocation(false);}else if(!document.getElementById('agentPage').hidden)dashboard();},0));
 // Future service may reuse these visual state definitions. No state can activate a task here.
 window.DPIAAgent={open,presentationFor:state=>({label:tr(STATES[state]||STATES.error),canEdit:state!=='running',showPause:['active','running'].includes(state),showResume:state==='paused',executionControlsEnabled:false})};
})();
