/* History and galleries are loaded through authenticated Flask endpoints. */
(()=>{
 const $=id=>document.getElementById(id);
 let trackingBusy=false,trackingGeneration=0;
 let generation=0,offset=0,chosen=null,imageBusy=false,identity=typeof currentEmail==='string'?currentEmail:null;
 function showQuery(){
  $('currentQueryPanel').hidden=false;$('queryHistoryPanel').hidden=true;
  $('queryCurrentTab').setAttribute('aria-selected','true');$('queryHistoryTab').setAttribute('aria-selected','false');
 }
 const historyRows=[];
 const tr=text=>window.DPIAI18N?.translate(text)||text;
 function renderHistory(){
  $('queryHistoryList').replaceChildren();
  const states={reserved:'Reservada',dispatching:'En curso',pending:'Pendiente de confirmación',consumed:'Finalizada',released:'No iniciada',stored:'Trabajo guardado'};
  for(const {row,place} of historyRows){
   const raw=String(row.query||'').replace(/\s+/g,' ').trim();
   const shorten=(text,max)=>text.length>max?text.slice(0,max-1).trimEnd()+'…':text;
   const card=document.createElement('button');card.type='button';card.className='query-history-card';
   const title=document.createElement('strong');title.className='query-history-title';
   // Long saved prompts belong in the summary, not in the title.
   title.textContent=raw.length>100?(row.category||tr('Búsqueda guardada')):raw||row.category||tr('Búsqueda guardada');
   title.setAttribute('data-catalog-name','');
   const date=document.createElement('time');date.className='query-history-date';
   const stamp=row.created_at?new Date(row.created_at):null;
   if(stamp&&!Number.isNaN(stamp.getTime())){date.dateTime=row.created_at;date.textContent=new Intl.DateTimeFormat(window.DPIAI18N?.language||'es',{dateStyle:'medium',timeStyle:'short'}).format(stamp);}else date.textContent=tr('Fecha no disponible');
   const summary=document.createElement('span');summary.className='query-history-summary';summary.setAttribute('data-catalog-name','');summary.textContent=shorten(raw||row.category||'',180);
   const meta=document.createElement('span');meta.className='query-history-meta';
   const state=document.createElement('span');state.className='query-history-state';state.dataset.state=row.state;state.textContent=tr(states[row.state]||'Estado sin confirmar');
   const count=document.createElement('span');count.textContent=row.product_count==null?tr('Productos por consultar'):String(row.product_count)+' '+tr('productos');
   const context=document.createElement('span');context.setAttribute('data-catalog-name','');context.textContent=[row.source,row.city,row.category].filter(Boolean).join(' · ');
   meta.append(state,count,context);
   const action=document.createElement('span');action.className='query-history-open';action.textContent=tr('Consultar resultados')+' →';
   card.append(title,date);if(summary.textContent&&raw!==title.textContent)card.append(summary);card.append(meta,action);
   card.onclick=()=>row.remote?loadRemote(row.operation_id,place):loadQueryOperation(row.operation_id);
   $('queryHistoryList').append(card);
  }
 }
 $('languageSelect').addEventListener('change',()=>setTimeout(renderHistory,0));
 async function history(append=false){
  if(!currentEmail){openAuth();return;}
  const email=currentEmail,serial=++generation,remote=$('queryHistoryOrigin').value==='scraper',place=country;
  if(!append){offset=0;historyRows.length=0;renderHistory();}
  $('queryHistoryStatus').textContent='Cargando historial…';$('moreQueryHistory').hidden=true;
  try{
   const response=await fetch(remote?'/api/consultas/historial/scrapeador?pais='+encodeURIComponent(place):'/api/consultas/historial?offset='+offset,{cache:'no-store'}),data=await response.json();
   if(remote&&Array.isArray(data.trabajos))data.operations=data.trabajos.map(row=>({operation_id:row.archivo,query:row.nombre,source:'Scrapeador API',city:place,state:'stored',product_count:null,remote:true}));
   if(serial!==generation||email!==currentEmail)return;
   if(response.status===401){openAuth();return;}
   if(!response.ok||!data.success||!Array.isArray(data.operations))throw new Error(data.error||'No se pudo consultar el historial.');
   historyRows.push(...data.operations.map(row=>({row,place})));renderHistory();
   offset+=data.operations.length;$('moreQueryHistory').hidden=!data.has_more;
   $('queryHistoryStatus').textContent=$('queryHistoryList').children.length?'':'Todavía no tenés búsquedas guardadas en esta PWA.';
  }catch(error){if(serial===generation&&email===currentEmail)$('queryHistoryStatus').textContent=error.message;}
 }
 function showHistory(){
  if(!currentEmail){openAuth();return;}
  $('currentQueryPanel').hidden=true;$('queryHistoryPanel').hidden=false;
  $('queryCurrentTab').setAttribute('aria-selected','false');$('queryHistoryTab').setAttribute('aria-selected','true');history();
 }
 function showSavedPublication(stage){
  if(!Number.isInteger(stage?.publication?.id)||stage.publication.id<=0)return false;
  closeImages();openHomePublication({id:stage.publication.id});return true;
 }
 function gallery(data){
  if(showSavedPublication(data))return;
  if(chosen)chosen.stage=data;
  $('prepareProductImages').disabled=imageBusy;
  $('prepareProductImages').textContent=data.status==='complete'?'Ver imágenes':'Preparar imágenes';
  const ready=data.status==='complete'&&data.images?.length;
  $('productImagesForm').hidden=!!ready;$('productImagesStatus').hidden=!!ready;
  $('productGallery').replaceChildren();
  for(const value of data.images||[]){const url=safeQueryUrl(value);if(!url)continue;const label=document.createElement('label'),check=document.createElement('input'),img=document.createElement('img');check.type='checkbox';check.name='publicationPhoto';check.value=url;let saved=null;try{saved=JSON.parse(localStorage.getItem(photoKey())||'null');}catch(_){}check.checked=!Array.isArray(saved)||saved.includes(url);check.onchange=()=>{try{localStorage.setItem(photoKey(),JSON.stringify([...document.querySelectorAll('[name="publicationPhoto"]:checked')].map(n=>n.value)));}catch(_){}};img.src=url;img.alt='Imagen del producto';img.loading='lazy';img.onerror=()=>label.remove();label.append(check,img);$('productGallery').append(label);}
  $('queryPublicationForm').hidden=!(data.status==='complete'&&data.images?.length);
  $('saveQueryPublication').disabled=!!data.publication;
  if(data.publication)$('queryPublicationStatus').textContent='Publicación guardada · ID '+data.publication.id;
  const d=data.diagnostics;
  const diagnosis=d?`Precio: ${d.price??'N/D'} · Rating: ${d.rating??'N/D'} · Reseñas: ${d.rating_missing?'No exigidas sin rating':d.reviews}. `:'';
  const reasons=d?Object.entries(d.checks).filter(([,ok])=>!ok).map(([key])=>({precio:'precio',rating:'rating',resenas:'reseñas'}[key])):[];
  const text=data.status==='not_started'?'Aplicá los filtros y prepará las imágenes cuando quieras.':data.status==='running'?'Preparación en ejecución confirmada en DPIA. Podés cerrar este modal.':data.status==='pending'?'Preparación pendiente de confirmación. Podés cerrar este modal y continuar navegando.':data.status==='filtered'?`No cumple los filtros de ${reasons.join(', ')}. Podés ajustarlos antes de preparar imágenes.`:data.status==='complete'?(data.images?.length?'Imágenes preparadas.':'La API no devolvió imágenes válidas.'):data.error||'Preparación pendiente de confirmación.';
  $('productImagesStatus').textContent=diagnosis+(data.tracking_supported===false?data.error:text+(['pending','running'].includes(data.status)&&data.error?' '+data.error:''));
 }
 function openImages(operation,index,product,stage){
  if(showSavedPublication(stage))return;
  if(!currentEmail){openAuth();return;}
  chosen={operation,index,email:currentEmail,product};$('prepareProductImages').disabled=imageBusy;$('prepareProductImages').textContent='Preparar imágenes';$('queryPublicationForm').hidden=true;$('queryPublicationStatus').textContent='';$('publicationTitle').value=product.title.slice(0,120);$('publicationDescription').value=product.title;$('publicationCurrency').value=product.currency||'';$('productImagesTitle').textContent=product.title;
  $('imagePriceMin').value='0';$('imagePriceMax').value='';$('imageRatingMin').value='';$('imageReviewsMin').value='';
  $('productImagesForm').hidden=false;$('productImagesStatus').hidden=false;
  $('productGallery').replaceChildren();$('productImagesStatus').textContent='Se usará el producto original del trabajo DPIA. Preparar imágenes no publica el producto.';
  if(stage){if(stage.filters){$('imagePriceMin').value=stage.filters.precio_minimo;$('imagePriceMax').value=stage.filters.precio_maximo??'';$('imageRatingMin').value=stage.filters.rating_minimo??'';$('imageReviewsMin').value=stage.filters.resenas_minimas??'';}gallery(stage);}
  $('productImagesOverlay').hidden=false;$('closeProductImages').focus();if(!stage)refreshChosen({...chosen});
 }
 function confirmImagePreparation(message){
  return new Promise(resolve=>{
   const dialog=document.createElement('dialog');dialog.className='auth-dialog image-preparation-confirm';
   const title=document.createElement('h2');title.id='imagePreparationConfirmTitle';title.textContent='Confirmar preparación de imágenes';dialog.setAttribute('aria-labelledby',title.id);
   const text=document.createElement('p');text.textContent=message||'Preparar o volver a solicitar las imágenes puede consumir puntos. ¿Querés permitirlo?';
   const allow=document.createElement('button');allow.type='button';allow.className='primary';allow.textContent='Permitir';
   const cancel=document.createElement('button');cancel.type='button';cancel.className='action-button';cancel.textContent='Cancelar';
   const actions=document.createElement('div');actions.className='image-preparation-confirm-actions';actions.append(cancel,allow);
   const finish=value=>{dialog.close();dialog.remove();resolve(value);};
   allow.onclick=()=>finish(true);cancel.onclick=()=>finish(false);dialog.oncancel=event=>{event.preventDefault();finish(false);};
   dialog.addEventListener('keydown',event=>{if(event.key==='Escape')event.stopPropagation();});
   dialog.append(title,text,actions);document.body.append(dialog);dialog.showModal();cancel.focus();
  });
 }
 async function createImageSearch(target,body){
  if(currentEmail!==target.email||chosen?.operation!==target.operation||chosen?.index!==target.index)return;
  const key='dpia-image-search:'+target.email+':'+target.operation;
  let record;
  try{record=JSON.parse(sessionStorage.getItem(key)||'null');}catch(_){}
  if(record?.id){
   if($('imagePreparationNotice'))$('imagePreparationNotice').hidden=true;
   setQueryArtState('warning');
   await loadQueryOperation(record.id);$('productImagesOverlay').hidden=true;return;
  }
  record={id:crypto.randomUUID()};
  // Save before POST. An uncertain response can only be recovered by reading it.
  sessionStorage.setItem(key,JSON.stringify(record));
  $('productImagesStatus').textContent='Creando búsqueda Amazon compatible con imágenes…';
  if($('imagePreparationNotice'))$('imagePreparationNotice').hidden=true;
  setScrapingStatus('running','Buscando en Amazon… · Consultar');
  $('scrapingActivity').dataset.operationId=record.id;
  const response=await fetch('/api/consultas/scraping-directo',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({...body,request_id:record.id}),signal:AbortSignal.timeout(200000)});
  const data=await response.json();
  if(currentEmail!==target.email)return;
  if(!response.ok||!data.success){
   if(response.status<500)sessionStorage.removeItem(key);
   if(response.status===402)window.DPIACredits?.insufficient(data);
   throw new Error(data.error||'No se confirmó la búsqueda.');
  }
  $('productImagesOverlay').hidden=true;chosen=null;
  if(data.sources)updateScrapingStatus(data);else setQueryArtState('success');
  await loadQueryOperation(record.id);window.DPIACredits?.refresh();
  $('queryStatus').textContent='Nueva búsqueda guardada. Elegí el producto y pulsá Preparar imágenes.';
 }
 let imageActivityKey='';
 function imageActivity(task){
  const stage=task.stage,state=['pending','running'].includes(stage.status)?'running':stage.status==='complete'?'complete':stage.status==='filtered'?'warning':'failed';
  let notice=$('imagePreparationNotice');
  if(!notice){notice=document.createElement('button');notice.id='imagePreparationNotice';notice.type='button';notice.className='scraping-activity';notice.style.bottom='150px';notice.setAttribute('aria-live','polite');document.body.append(notice);}
  notice.hidden=false;notice.dataset.state=state;
  notice.textContent=state==='running'?'Preparando imágenes… · Consultar':state==='complete'?'Las imágenes de tu producto están listas · Ver':state==='warning'?'Revisá los filtros de imágenes · Ver':'La preparación de imágenes informó un error · Ver';
  notice.onclick=()=>{notice.hidden=true;const preview=$('aiExplorePreview');if(preview?.open)preview.close();openImages(task.operation_id,task.product_index,task.product,stage);};
  const key=JSON.stringify([task.operation_id,task.product_index,state]);
  if(key!==imageActivityKey){imageActivityKey=key;setQueryArtState(state==='running'?'running':state==='complete'?'success':state==='warning'?'warning':'error');}
 }
 async function prepareImages(){
  if(imageBusy||!chosen||chosen.email!==currentEmail)return;
  const form=$('productImagesForm');if(!form.reportValidity())return;
  const target={...chosen};
  if(target.stage?.status==='complete'){await refreshChosen(target);return;}
  imageBusy=true;
  let preflight;
  try{
   const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(target.operation)+'/imagenes?product_index='+target.index,{cache:'no-store'});
   preflight=await response.json();
   if(!response.ok||!preflight.success)throw new Error(preflight.error||'No se pudo verificar la preparación.');
  }catch(error){imageBusy=false;$('productImagesStatus').textContent=error.message;return;}
  if(chosen?.operation!==target.operation||chosen?.index!==target.index||currentEmail!==target.email){imageBusy=false;return;}
  if(preflight.status==='complete'){gallery(preflight);imageBusy=false;$('prepareProductImages').disabled=false;return;}
  const allowed=await confirmImagePreparation(preflight.search_required?'Esta búsqueda anterior requiere una nueva búsqueda Amazon, que puede consumir 1 punto. Los resultados pueden cambiar y deberás elegir el producto nuevamente. ¿Querés permitirlo?':undefined);
  if(!allowed||chosen?.operation!==target.operation||chosen?.index!==target.index||currentEmail!==target.email){imageBusy=false;return;}
  $('prepareProductImages').disabled=true;
  $('productImagesStatus').textContent='Consultando imágenes en DPIA…';
  const filters={precio_minimo:Number($('imagePriceMin').value),precio_maximo:$('imagePriceMax').value===''?null:Number($('imagePriceMax').value),rating_minimo:$('imageRatingMin').value===''?null:Number($('imageRatingMin').value),resenas_minimas:$('imageReviewsMin').value===''?null:Number($('imageReviewsMin').value)};
  $('productImagesOverlay').hidden=true;
  imageActivity({operation_id:target.operation,product_index:target.index,product:target.product,stage:{status:'pending',images:[]}});
  try{
   if(preflight.search_required){await createImageSearch(target,preflight.search_body);return;}
   const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(target.operation)+'/imagenes',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_index:target.index,filters,confirmed:true}),signal:AbortSignal.timeout(30000)}),data=await response.json();
   if(currentEmail!==target.email)return;
   if(response.status===409&&data.code==='image_search_required'){imageActivity({operation_id:target.operation,product_index:target.index,product:target.product,stage:{status:'filtered',error:data.error,images:[]}});if(chosen?.operation===target.operation&&chosen?.index===target.index){gallery({...data,status:'filtered',images:[]});$('productImagesOverlay').hidden=false;}return;}
   if(!response.ok||!data.success)throw new Error(data.error||'No se pudieron preparar las imágenes.');
   if(chosen?.operation===target.operation&&chosen?.index===target.index)gallery(data);
   imageActivity({operation_id:target.operation,product_index:target.index,product:target.product,stage:data});trackImages();
  }catch(error){if(currentEmail===target.email){const stage={status:error.name==='TimeoutError'?'pending':'failed',images:[],error:error.message};$('productImagesStatus').textContent=error.message;imageActivity({operation_id:target.operation,product_index:target.index,product:target.product,stage});}}
  finally{imageBusy=false;$('prepareProductImages').disabled=false;}
 }
 async function publish(){
  if(imageBusy||!chosen||chosen.email!==currentEmail||!$('queryPublicationForm').reportValidity())return;
  const target={...chosen};imageBusy=true;$('saveQueryPublication').disabled=true;
  $('queryPublicationStatus').textContent='Guardando publicación…';
  try{
   const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(target.operation)+'/publicar',{
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_index:target.index,
    titulo:$('publicationTitle').value,descripcion:$('publicationDescription').value,moneda:$('publicationCurrency').value,
    imagenes:[...document.querySelectorAll('[name="publicationPhoto"]:checked')].map(input=>input.value)})}),data=await response.json();
   if(currentEmail!==target.email)return;
   if(!response.ok||!data.success||!data.guardado)throw new Error(data.error||'No se pudo confirmar la publicación.');
   for(const button of document.querySelectorAll('[data-image-operation]')){
    if(button.dataset.imageOperation===target.operation&&button.dataset.productIndex===String(target.index)){
     button.textContent='Ver publicación';button.onclick=()=>openHomePublication({id:data.publicacion_id});
    }
   }
   closeImages();
   notify('Publicación guardada');
   window.DPIAPublications?.openProfile();
   $('queryPublicationStatus').textContent='Publicación guardada · ID '+data.publicacion_id;
  }catch(error){$('queryPublicationStatus').textContent=error.message;$('saveQueryPublication').disabled=false;}
  finally{imageBusy=false;}
 }
 $('queryPublicationForm').onsubmit=e=>{e.preventDefault();publish();};
 async function loadRemote(filename,place=country){
  const email=currentEmail,serial=++generation;
  $('queryHistoryStatus').textContent='Consultando trabajo en la API DPIA…';
  try{
   const params=new URLSearchParams({pais:place,archivo:filename});
   const response=await fetch('/api/consultas/historial/scrapeador?'+params,{cache:'no-store'}),data=await response.json();
   if(serial!==generation||email!==currentEmail)return;
   if(!response.ok||!data.success)throw new Error(data.error||'No se pudo recuperar el trabajo.');
   show('consultPage');renderQueryResult(data.payload);$('queryStatus').textContent='Trabajo recuperado de la API DPIA.';
  }catch(error){if(serial===generation&&email===currentEmail)$('queryHistoryStatus').textContent=error.message;}
 }
 function remoteImageButton(job){
  const wrap=document.createElement('div'),button=document.createElement('button'),status=document.createElement('p'),results=document.createElement('div');
  button.className='action-button';button.type='button';button.textContent='Preparar imágenes del trabajo';status.className='hint';
  button.onclick=async()=>{
   if(button.disabled)return;
   const email=currentEmail;button.disabled=true;status.textContent='Aplicando los filtros del Scrapeador y preparando imágenes…';
   try{
    const response=await fetch('/api/consultas/historial/scrapeador',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...job,filters:{}}),signal:AbortSignal.timeout(650000)}),data=await response.json();
    if(email!==currentEmail)return;
    if(!response.ok||!data.success)throw new Error(data.error||'No se pudo confirmar la preparación de imágenes.');
    results.replaceChildren();
    for(const row of data.selected||[]){const article=document.createElement('article'),title=document.createElement('h4'),gallery=document.createElement('div');title.textContent=row.title;gallery.className='product-gallery';
     for(const value of row.images||[]){const url=safeQueryUrl(value);if(url){const image=document.createElement('img');image.src=url;image.alt='Imagen del producto';image.onerror=()=>image.remove();gallery.append(image);}}
     article.append(title,gallery);results.append(article);}
    status.textContent=data.selected?.length?'Selección final de imágenes recuperada de DPIA.':'No hay productos que superen los filtros del Scrapeador.';
   }catch(error){if(email===currentEmail)status.textContent=error.message;}
   finally{button.disabled=false;}
  };
  wrap.append(button,status,results);return wrap;
 }
 function photoKey(){return 'dpia-gallery-selection:'+JSON.stringify([currentEmail,chosen?.operation,chosen?.index]);}
 async function refreshChosen(target){
  if(imageBusy)return;imageBusy=true;$('prepareProductImages').disabled=true;
  $('productImagesStatus').textContent='Consultando el estado guardado en DPIA…';
  try{
   const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(target.operation)+'/imagenes?product_index='+target.index,{cache:'no-store'}),data=await response.json();
   if(!response.ok||!data.success)throw new Error(data.error||'No se pudo consultar la preparación.');
   if(chosen?.operation===target.operation&&chosen?.index===target.index&&currentEmail===target.email){gallery(data);const stamp=document.createElement('small');stamp.textContent=' Estado consultado: '+new Date().toLocaleTimeString();$('productImagesStatus').append(stamp);}
  }catch(error){if(chosen?.operation===target.operation&&currentEmail===target.email)$('productImagesStatus').textContent=error.message;}
  finally{imageBusy=false;$('prepareProductImages').disabled=false;}
 }
 async function trackImages(){
  if(trackingBusy||!currentEmail||document.hidden)return;
  const email=currentEmail,serial=trackingGeneration;trackingBusy=true;
  try{
   const response=await fetch('/api/consultas/imagenes/seguimiento',{cache:'no-store'});if(!response.ok)return;
   const data=await response.json();if(!data.success||email!==currentEmail||serial!==trackingGeneration)return;
   const active=(data.preparations||[]).find(task=>['pending','running'].includes(task.stage.status));
   if(active)imageActivity(active);
   for(const task of data.preparations||[]){
    if(chosen?.operation===task.operation_id&&chosen?.index===task.product_index){
     if(JSON.stringify(chosen.stage)!==JSON.stringify(task.stage))gallery(task.stage);
    }
    if(!['complete','failed'].includes(task.stage.status))continue;
    const key='dpia-image-notice:'+JSON.stringify([email,task.operation_id,task.product_index,task.stage.updated_at]);
    let seen=false;try{seen=localStorage.getItem(key)==='1';}catch(_){}
    if(seen)continue;
    if(!(data.preparations||[]).some(t=>['pending','running'].includes(t.stage.status)))imageActivity(task);
    try{localStorage.setItem(key,'1');}catch(_){}
   }
  }catch(_){}finally{trackingBusy=false;}
 }
 setInterval(trackImages,5000);
 document.addEventListener('visibilitychange',trackImages);
 setTimeout(trackImages,0);
 function imageButton(operation,index,product,stage){
  const button=document.createElement('button');button.className='action-button';button.type='button';button.dataset.imageOperation=operation;button.dataset.productIndex=String(index);button.textContent=stage?.publication?.id?'Ver publicación':stage?.status==='complete'?'Ver imágenes / ajustar filtros':'Preparar imágenes';
  button.onclick=()=>openImages(operation,index,product,stage);return button;
 }
 $('queryCurrentTab').onclick=showQuery;$('queryHistoryTab').onclick=showHistory;
 $('refreshQueryHistory').onclick=()=>history();$('moreQueryHistory').onclick=()=>history(true);
 $('queryHistoryOrigin').onchange=()=>history();
 $('productImagesForm').onsubmit=e=>{e.preventDefault();prepareImages();};
 function closeImages(){$('productImagesOverlay').hidden=true;chosen=null;}
 $('closeProductImages').onclick=closeImages;
 $('productImagesOverlay').onclick=e=>{if(e.target===$('productImagesOverlay'))closeImages();};
 document.addEventListener('keydown',e=>{if(e.key==='Escape')closeImages();});
 new MutationObserver(()=>{if(identity!==currentEmail){identity=currentEmail;generation++;trackingGeneration++;imageActivityKey='';if($('imagePreparationNotice'))$('imagePreparationNotice').hidden=true;setTimeout(trackImages,0);$('queryHistoryList').replaceChildren();historyRows.length=0;$('productImagesOverlay').hidden=true;chosen=null;}}).observe($('userBtn'),{childList:true,subtree:true,characterData:true});
 window.DPIAHistory={showQuery,showHistory,imageButton,remoteImageButton};
})();
