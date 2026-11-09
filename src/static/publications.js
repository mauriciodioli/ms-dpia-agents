/* Owned publications only; IDs come from confirmed MySQL records. */
(()=>{
 const $=id=>document.getElementById(id),tr=text=>window.DPIAI18N?.translate(text)||text;
 let generation=0,offset=0,selected=null,deleting=false,previousFocus=null,promotionSummary=null,promoting=false,profileView='publications';
 function clear(){
  generation++;offset=0;selected=null;promotionSummary=null;document.querySelector('#promotePublicationOverlay')?.remove();
  $('publicationHistory').replaceChildren();$('profileOverlay').hidden=true;
  $('deletePublicationOverlay').hidden=true;
 }
 function close(){if(deleting||promoting)return;clear();const target=$(profileView==='profile'?'accountProfile':'accountPublications');(target&&!target.hidden&&!$('accountPage').hidden?target:document.querySelector('nav [data-page=accountPage]')).focus();}
 function cancelDelete(){
  if(deleting)return;
  selected=null;$('deletePublicationOverlay').hidden=true;
  $('profileOverlay').removeAttribute('aria-hidden');previousFocus?.focus();
 }
 function requestDelete(publication,card,button){
  if(deleting)return;
  selected={publication,card,email:currentEmail};previousFocus=button;
  $('deletePublicationDescription').dataset.catalogName='';
  $('deletePublicationDescription').textContent=tr('¿Eliminar «{titulo}»? Esta acción elimina únicamente esta publicación y sus asociaciones.').replace('{titulo}',publication.titulo);
  $('deletePublicationStatus').textContent='';$('deletePublicationConfirm').disabled=false;
  $('profileOverlay').setAttribute('aria-hidden','true');
  $('deletePublicationOverlay').hidden=false;$('deletePublicationCancel').focus();
 }
 function cardFor(publication){
  const card=document.createElement('article');card.className='scraped-product';
  card.dataset.publicationId=String(publication.id);
  const imageUrl=safeQueryUrl(publication.imagen);
  if(imageUrl){const image=document.createElement('img');image.src=imageUrl;image.alt='';image.loading='lazy';image.onerror=()=>image.remove();card.append(image);}
  const title=document.createElement('button');title.type='button';title.className='publication-detail-link';const heading=document.createElement('strong');heading.textContent=publication.titulo;heading.dataset.catalogName='';title.append(heading);title.onclick=()=>openHomePublication({id:publication.id});
  const description=document.createElement('p');description.textContent=publication.descripcion||'';description.dataset.catalogName='';
  const price=document.createElement('p');price.textContent=publication.precio==null?'Precio no informado':`${publication.precio} ${publication.moneda||''}`.trim();
  card.append(title,description,price);
  if(publication.can_delete&&String(publication.estado).trim().toLowerCase()==='activo'&&promotionSummary){
   const active=promotionSummary.promociones.find(row=>row.publicacion_id===publication.id);
   if(active){const info=document.createElement('small');info.textContent=tr('Destacada hasta')+' '+new Date(active.fin_en).toLocaleString(catalogLanguage());card.append(info);}
   else{const promote=document.createElement('button');promote.className='action-button';promote.type='button';promote.textContent='Destacar 5 días · 5 puntos';promote.onclick=()=>requestPromotion(publication,promote);card.append(promote);}
  }
  if(publication.can_delete&&Number.isInteger(publication.id)&&publication.id>0){
   const button=document.createElement('button');button.className='action-button danger-button';button.type='button';button.textContent='Eliminar publicación';
   button.onclick=()=>requestDelete(publication,card,button);card.append(button);
  }
  return card;
 }
 function requestPromotion(publication,trigger){
  if(promoting||document.querySelector('#promotePublicationOverlay'))return;
  const email=currentEmail,operationId=crypto.randomUUID();
  const overlay=document.createElement('div');overlay.className='auth-overlay';overlay.id='promotePublicationOverlay';
  const dialog=document.createElement('div');dialog.className='auth-dialog';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-labelledby','promotePublicationTitle');
  const title=document.createElement('h2');title.id='promotePublicationTitle';title.textContent='Destacar publicación';
  const text=document.createElement('p');text.dataset.catalogName='';text.textContent=tr('Destacar «{titulo}» durante 5 días cuesta 5 puntos. Saldo disponible: {saldo}. Se mostrará a otros usuarios de la misma zona.').replace('{titulo}',publication.titulo).replace('{saldo}',promotionSummary.saldo);
  const status=document.createElement('p');status.setAttribute('role','status');
  const cancel=document.createElement('button');cancel.className='action-button';cancel.textContent='Cancelar';
  const confirm=document.createElement('button');confirm.className='action-button';confirm.textContent='Confirmar · Gastar 5 puntos';confirm.disabled=promotionSummary.saldo<5;
  if(confirm.disabled)status.textContent='Saldo insuficiente. Necesitás 5 puntos disponibles.';
  const dismiss=()=>{if(promoting)return;overlay.remove();$('profileOverlay').removeAttribute('aria-hidden');trigger.focus();};
  cancel.onclick=dismiss;overlay.onclick=event=>{if(event.target===overlay)dismiss();};
  overlay.onkeydown=event=>{if(event.key==='Escape'){event.stopPropagation();dismiss();}if(event.key==='Tab'){const targets=[cancel,confirm].filter(button=>!button.disabled);if(targets.length===1||(!event.shiftKey&&document.activeElement===targets.at(-1))||(event.shiftKey&&document.activeElement===targets[0])){event.preventDefault();(event.shiftKey?targets.at(-1):targets[0]).focus();}}};
  confirm.onclick=async()=>{
   if(promoting||currentEmail!==email)return;promoting=true;confirm.disabled=true;cancel.disabled=true;status.textContent='Activando promoción…';
   let saved=false;
   try{
    const response=await fetch('/api/publicaciones/'+publication.id+'/destacar',{method:'POST',headers:{'Content-Type':'application/json','X-DPIA-Action':'promote-publication'},body:JSON.stringify({operacion_id:operationId}),signal:AbortSignal.timeout(20000)}),data=await response.json();
    if(currentEmail!==email)return;
    if(!response.ok||!data.success)throw new Error(data.error||'No se confirmó la promoción.');
    saved=true;overlay.remove();$('profileOverlay').removeAttribute('aria-hidden');homePublicationsCache=null;await load();window.DPIACredits?.refresh();
   }catch(error){status.textContent=tr(error.name==='TimeoutError'?'Resultado pendiente. Actualizá el perfil para comprobarlo o reintentá esta misma operación.':error.message);}
   finally{promoting=false;cancel.disabled=false;confirm.disabled=false;if(saved)$('closeProfile').focus();}
  };
  dialog.append(title,text,status,cancel,confirm);overlay.append(dialog);document.body.append(overlay);$('profileOverlay').setAttribute('aria-hidden','true');cancel.focus();
 }
 async function load(append=false){
  if(!currentEmail){openAuth();return;}
  const email=currentEmail,serial=++generation;
  if(!append){offset=0;$('publicationHistory').replaceChildren();}
  $('profileStatus').textContent='Cargando tus publicaciones…';$('moreMyPublications').hidden=true;
  try{
   const response=await fetch('/api/publicaciones/mias?offset='+offset,{cache:'no-store'}),data=await response.json();
   if(serial!==generation||email!==currentEmail)return;
   if(response.status===401){clear();openAuth();return;}
   if(!response.ok||!data.success)throw new Error(data.error||'No se pudieron consultar tus publicaciones.');
   try{
    const pointsResponse=await fetch('/api/publicaciones/promociones',{cache:'no-store'}),points=await pointsResponse.json();
    if(serial!==generation||email!==currentEmail)return;
    promotionSummary=pointsResponse.ok&&points.success?points:null;
   }catch(_){promotionSummary=null;}
   if(serial!==generation||email!==currentEmail)return;
   $('profilePromotionBalance').textContent=promotionSummary?tr('Puntos disponibles: {saldo} · 5 puntos = 5 días').replace('{saldo}',promotionSummary.saldo):'No se pudieron consultar los puntos disponibles.';
   for(const publication of data.publicaciones)$('publicationHistory').append(cardFor(publication));
   offset+=data.publicaciones.length;$('moreMyPublications').hidden=!data.has_more;
   $('profileStatus').textContent=$('publicationHistory').children.length?'':'Todavía no tenés publicaciones guardadas.';
  }catch(error){if(serial===generation&&email===currentEmail)$('profileStatus').textContent=tr(error.message);}
 }
 async function confirmDelete(){
  if(deleting||!selected||selected.email!==currentEmail)return;
  deleting=true;const target=selected;$('deletePublicationConfirm').disabled=true;
  $('deletePublicationStatus').textContent='Eliminando publicación…';
  try{
   const response=await fetch('/api/publicaciones/'+target.publication.id,{method:'DELETE',headers:{'X-DPIA-Action':'delete-publication'}}),data=await response.json();
   if(target.email!==currentEmail)return;
   if(!response.ok||!data.success||!data.eliminado||data.publicacion_id!==target.publication.id)throw new Error(data.error||'No se pudo confirmar la eliminación. Actualizá el listado antes de reintentar.');
   target.card.remove();offset=Math.max(0,offset-1);
   $('deletePublicationOverlay').hidden=true;$('profileOverlay').removeAttribute('aria-hidden');selected=null;
   // Refresh the currently visible local list, preserving its filters.
   if(typeof page!=='undefined'&&page==='mapPage')loadLocalPublications();
   $('profileStatus').textContent='Publicación eliminada.';$('closeProfile').focus();
  }catch(error){if(target.email===currentEmail)$('deletePublicationStatus').textContent=tr(error.message);}
  finally{deleting=false;$('deletePublicationConfirm').disabled=false;}
 }
 function renderProfileView(){
  $('profileTitle').textContent=tr(profileView==='profile'?'Mi perfil':'Mis publicaciones');
  $('profileIdentity').hidden=profileView!=='profile';
  $('profilePublicationsSection').hidden=profileView==='profile';
 }
 function openProfile(view='publications'){
  if(!currentEmail){openAuth();return;}
  profileView=view==='profile'?'profile':'publications';renderProfileView();
  $('profileOverlay').removeAttribute('aria-hidden');$('profileOverlay').hidden=false;
  $('profileEmail').textContent=currentEmail;$('closeProfile').focus();
  if(profileView==='publications')load();
 }
 $('closeProfile').onclick=close;$('reloadMyPublications').onclick=()=>load();
 $('moreMyPublications').onclick=()=>load(true);
 $('deletePublicationCancel').onclick=cancelDelete;$('deletePublicationConfirm').onclick=confirmDelete;
 $('profileOverlay').onclick=e=>{if(e.target===$('profileOverlay'))close();};
 $('deletePublicationOverlay').onclick=e=>{if(e.target===$('deletePublicationOverlay'))cancelDelete();};
 document.addEventListener('keydown',e=>{if(e.key==='Escape'){if(document.querySelector('#promotePublicationOverlay'))return;if(!$('deletePublicationOverlay').hidden)cancelDelete();else if(!$('profileOverlay').hidden)close();}});
 $('profileLogout').onclick=async()=>{
  if(deleting||promoting)return;
  try{const response=await fetch('/api/auth/logout',{method:'POST'});if(!response.ok)throw new Error('No se pudo cerrar la sesión.');clear();updateUser(null);notify('Sesión cerrada');}
  catch(error){$('profileStatus').textContent=tr(error.message);}
 };
 let identity=typeof currentEmail==='string'?currentEmail:null;
 new MutationObserver(()=>{const next=typeof currentEmail==='string'?currentEmail:null;if(next!==identity){identity=next;clear();}}).observe($('userBtn'),{childList:true,subtree:true,characterData:true});
 $('languageSelect')?.addEventListener('change',()=>{if(!$('profileOverlay').hidden&&!promoting&&!deleting){renderProfileView();if(profileView==='publications')load();}});
 window.DPIAPublications={openProfile,refresh:()=>load()};
})();
