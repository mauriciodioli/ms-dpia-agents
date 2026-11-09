/* Candidate marketplace search through existing authenticated DPIA routes. */
(()=>{
 const names={amazon:'Amazon',ebay:'eBay',aliexpress:'AliExpress',mercadolibre:'Mercado Libre'};
 let dialog=null,selected=null,opener=null;
 const tr=text=>window.DPIAI18N?.translate(text)||text;
 function element(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
 function imageUrl(value){
  if(typeof value!=='string')return null;
  try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&url.hostname&&!url.username&&!url.password?url.href:null;}catch(_){return null;}
 }
 function addImage(parent,value,title){
  const url=imageUrl(value);if(!url)return;
  // A detached image loads without allocating any visible box or placeholder.
  const image=new Image();image.alt=title||'';image.referrerPolicy='no-referrer';image.decoding='async';
  image.onload=()=>{if(!image.naturalWidth||!parent.isConnected)return;const figure=element('figure',undefined,'ai-preview-image');figure.append(image);parent.prepend(figure);};
  image.onerror=()=>{const figure=image.closest('.ai-preview-image');if(figure)figure.remove();else image.remove();};image.src=url;
 }
 function metadata(context){
  const list=element('dl',undefined,'ai-suggestion-context');
  for(const [label,key] of [['Ámbito','ambito'],['Categoría','categoria'],['Ciudad','ciudad'],['Código postal','codigoPostal'],['País','pais'],['Usuario','usuario'],['Fecha','fecha'],['Idioma','idioma']]){
   const value=element('dd',String(context[key]??''));value.dataset.catalogName='';list.append(element('dt',tr(label)),value);
  }
  return list;
 }
 function operationKey(target,source){return 'dpia-candidate-operation:'+JSON.stringify([target.email,target.ids,target.context.pais,target.context.ciudad,target.context.idioma,target.item.producto,source]);}
 function operation(target){
  try{return JSON.parse(sessionStorage.getItem(operationKey(target,target.marketplace))||'null');}catch(_){return null;}
 }
 function active(target){return selected===target&&currentEmail===target.email&&dialog.open;}
 function controls(target){
  if(!active(target))return;
  const started=operation(target)?.submitted;
  dialog.querySelector('#aiPreviewSearch').disabled=!!target.busy||!target.marketplace||!(window.DPIA_ENABLED_MARKETPLACES||['amazon']).includes(target.marketplace);
  dialog.querySelector('#aiPreviewSearch').textContent=tr(target.busy?'Buscando…':started?'Consultar estado':'Buscar productos reales');
  dialog.querySelectorAll('[name="aiPreviewMarketplace"]').forEach(node=>node.disabled=!!target.busy||!(window.DPIA_ENABLED_MARKETPLACES||['amazon']).includes(node.value));
 }
 function results(target,data){
  if(!active(target))return;
  const root=dialog.querySelector('#aiPreviewResults');root.replaceChildren();
  for(const [source,outcome] of Object.entries(data.sources||{})){
   const state=element('p',tr(({complete:'Búsqueda completada',empty:'Sin resultados',partial:'Resultados parciales',failed:'La búsqueda falló',pending:'Pendiente de confirmación'})[outcome.status]||'Pendiente de confirmación'));
   root.append(state);if(outcome.error)root.append(element('p',outcome.error));
   const grid=element('div',undefined,'scraped-products');
   for(const product of outcome.products||[]){
    const card=element('article',undefined,'scraped-product');card.dataset.realProduct='';
    const title=element('strong',product.title||'');title.dataset.catalogName='';card.append(title);addImage(card,product.image,product.title);
    if(product.price!=null){const value=typeof product.price==='object'?JSON.stringify(product.price):String(product.price);card.append(element('p',value+' '+(product.currency||'')));}
    if(product.seller||product.vendedor)card.append(element('p',String(product.seller||product.vendedor)));
    const url=imageUrl(product.url);if(url){const link=element('a',tr('Ver producto'));link.href=url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}
    if(source==='amazon'&&data.request_id&&window.DPIAHistory){
     const index=(outcome.products||[]).indexOf(product),stage=outcome.image_stages?.[String(index)];
     const action=window.DPIAHistory.imageButton(data.request_id,index,product,stage),handler=action.onclick;
     action.onclick=()=>{close();setTimeout(handler,0);};card.append(action);
    }
    card.append(element('small',names[source]||source));grid.append(card);
   }
   root.append(grid);
  }
 }
 async function readJSON(response){
  if(!response.headers.get('content-type')?.includes('application/json'))throw new Error(tr('El servidor no devolvió JSON. Consultá el estado antes de reintentar.'));
  return response.json();
 }
 async function search(){
  const target=selected;if(!target||target.busy||!target.marketplace||!(window.DPIA_ENABLED_MARKETPLACES||['amazon']).includes(target.marketplace))return;
  if(currentEmail!==target.email){close();return;}
  target.busy=true;controls(target);
  const status=dialog.querySelector('#aiPreviewSearchStatus');status.textContent=tr('Verificando consulta…');
  try{
   let record=operation(target);
   if(record?.submitted){
    status.textContent=tr('Consultando estado…');
    const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(record.id),{cache:'no-store'}),data=await readJSON(response);
    if(!response.ok||!data.success)throw new Error(data.error||tr('No se pudo consultar el estado.'));
    results(target,data.payload);if(active(target))status.textContent=tr('Estado recuperado. No se repitió el scraping.');return;
   }
   const ids=target.ids,context=target.context;
   if(!ids.ambito_id||!ids.categoria_id||!ids.codigo_postal_id)throw new Error(tr('Prepará nuevamente la consulta para recuperar su contexto.'));
   if(!target.item.producto?.trim()||target.item.producto.length>500)throw new Error(tr('El nombre del candidato debe tener entre 1 y 500 caracteres.'));
   const creditResponse=await fetch('/api/consultas/creditos',{cache:'no-store'}),credit=await readJSON(creditResponse);
   if(!creditResponse.ok||!credit.success)throw new Error(credit.error||tr('No se pudieron consultar los puntos.'));
   if(!active(target))return;
   if(!(credit.credits?.available>=1))throw new Error(tr('No quedan puntos disponibles.'));
   record={id:crypto.randomUUID(),submitted:true};
   // Persist before dispatch: uncertain responses and reopened dialogs only GET status.
   try{sessionStorage.setItem(operationKey(target,target.marketplace),JSON.stringify(record));}catch(_){throw new Error(tr('No se pudo guardar el identificador de operación. No se inició scraping.'));}
   status.textContent=tr('Buscando productos reales…');
   const response=await fetch('/api/consultas/scraping-directo',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({pais:context.pais,ciudad:context.ciudad,idioma:context.idioma,...ids,mode:'buscar',...(target.marketplace==='amazon'?{image_pipeline:'base44'}:{}),user_message:target.item.producto.trim(),attachments:[],sources:[target.marketplace],request_id:record.id}),signal:AbortSignal.timeout(200000)});
   const data=await readJSON(response);
   if(!response.ok||!data.success){
    if([400,401,402,403].includes(response.status)||data.code==='persistence_not_configured')sessionStorage.removeItem(operationKey(target,target.marketplace));
    throw new Error(data.error||tr('No se pudo confirmar el scraping. Consultá el estado.'));
   }
   results(target,data);if(active(target))status.textContent=tr('Consulta finalizada. Revisá los resultados.');
  }catch(error){if(active(target))status.textContent=error.name==='TimeoutError'?tr('La ejecución sigue pendiente. Consultá el estado; no se reenviará.'):error.message;}
  finally{target.busy=false;controls(target);window.DPIACredits?.refresh();}
 }
 function close(){if(dialog?.open)dialog.close();}
 function ensureDialog(){
  if(dialog)return;
  dialog=element('dialog',undefined,'ai-preview-dialog');dialog.id='aiExplorePreview';dialog.setAttribute('aria-labelledby','aiPreviewTitle');
  dialog.addEventListener('click',event=>{if(event.target!==dialog)return;const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)close();});
  dialog.addEventListener('keydown',event=>{
   if(event.key!=='Tab')return;
   const radios=[...dialog.querySelectorAll('input[type="radio"]')],activeRadio=radios.find(node=>node.checked)||radios[0];
   const targets=[...dialog.querySelectorAll('button:not([disabled]),input:not([disabled])')].filter(node=>node.type!=='radio'||node===activeRadio);
   const index=targets.indexOf(document.activeElement),next=(index+(event.shiftKey?-1:1)+targets.length)%targets.length;
   event.preventDefault();targets[next]?.focus();
  });
  dialog.addEventListener('close',()=>{selected=null;dialog.replaceChildren();if(opener?.isConnected)opener.focus();opener=null;});
  document.body.append(dialog);
  const user=document.querySelector('#userBtn');
  if(user)new MutationObserver(()=>{if(selected&&selected.email!==currentEmail)close();}).observe(user,{childList:true,subtree:true,characterData:true});
 }
 function open(snapshot,button){
  if(!currentEmail){openAuth();return;}
  ensureDialog();if(dialog.open)return;
  opener=button;selected={...structuredClone(snapshot),email:currentEmail};
  const {item,context}=selected;
  const header=element('header',undefined,'ai-preview-header'),heading=element('div');
  heading.append(element('span',tr('Sugerencia de IA'),'ai-preview-kicker'));
  const title=element('h2',item.producto);title.id='aiPreviewTitle';title.dataset.catalogName='';heading.append(title);
  const exit=element('button','×','ai-preview-close');exit.type='button';exit.setAttribute('aria-label',tr('Cerrar'));exit.onclick=close;header.append(heading,exit);
  const body=element('div',undefined,'ai-preview-body'),summary=element('section',undefined,'ai-preview-summary');
  const description=element('p',item.descripcion||'');description.dataset.catalogName='';summary.append(description);
  if(typeof item.precio_venta_sugerido==='number'){const price=element('p',tr('Precio sugerido:')+' '+item.precio_venta_sugerido+' '+(selected.constraints?.price?.currency||''));price.dataset.catalogName='';summary.append(price);}
  summary.append(metadata(context));addImage(summary,item.imagen,item.producto);
  const markets=element('section',undefined,'ai-preview-markets'),fieldset=element('fieldset');fieldset.append(element('legend',tr('Elegí un marketplace')));
  const options=element('div',undefined,'ai-preview-options');
  // Reuse the existing local integrations and Mercado Libre country restriction.
  // The existing backend checks live availability and permissions before dispatch.
  for(const source of externalQuerySources){
   if(!names[source]||(source==='mercadolibre'&&!['Argentina','México'].includes(context.pais)))continue;
   const label=element('label',undefined,'ai-preview-market'),radio=element('input');radio.type='radio';radio.name='aiPreviewMarketplace';radio.value=source;radio.disabled=!(window.DPIA_ENABLED_MARKETPLACES||['amazon']).includes(source);
   radio.onchange=()=>{selected.marketplace=source;dialog.querySelector('#aiPreviewResults').replaceChildren();dialog.querySelector('#aiPreviewSearchStatus').textContent='';controls(selected);};label.append(radio,element('span',names[source]));if(radio.disabled)label.append(element('small',tr('Todavía no habilitado')));options.append(label);
  }
  fieldset.append(options);markets.append(fieldset,element('p',tr('DPIA verifica la disponibilidad para tu país y los permisos antes de iniciar scraping.'),'hint'));
  const note=element('p',tr('Cada búsqueda iniciada consume 1 punto. Consultar el estado no repite el scraping.'),'ai-preview-note');
  body.append(summary,markets);const footer=element('footer');const done=element('button',tr('Cerrar'),'action-button');done.type='button';done.onclick=close;const start=element('button',tr('Buscar productos reales'),'primary');start.id='aiPreviewSearch';start.type='button';start.disabled=true;start.onclick=search;
  const status=element('p',undefined,'hint');status.id='aiPreviewSearchStatus';status.setAttribute('role','status');
  const output=element('section');output.id='aiPreviewResults';output.setAttribute('aria-label',tr('Resultados de búsqueda'));
  footer.append(note,start,status,output,done);
  dialog.append(header,body,footer);dialog.showModal();exit.focus();
 }
 function button(item,context,ids,details={}){
  const snapshot=structuredClone({item,context,ids:ids||{},constraints:details.constraints,query:details.query}),node=element('button',tr('Explorar'),'action-button ai-preview-trigger');node.type='button';node.setAttribute('aria-haspopup','dialog');node.onclick=()=>open(snapshot,node);return node;
 }
 window.DPIAExplorePreview={button,addImage};
})();
