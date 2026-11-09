// Postal IDs stay on the server; the user sees the selected city.
let localCategory = null;
let publicationRegion = 'local';
const regionText=text=>window.DPIAI18N?.translate(text)||text;
function openPublicationRegion(scope){
 publicationRegion=scope;
 mapLocationRequest++;mapLocationController?.abort();
 document.querySelector('#mapFrame').removeAttribute('src');
 document.querySelector('#localMap').hidden=true;
 const heading=document.querySelector('#mapPage .page-head h2');
 const key=scope==='exterior'?'Publicaciones del exterior':'Publicaciones del país';
 heading.setAttribute('data-i18n',key);heading.textContent=regionText(key);
 document.querySelector('#mapDescription').textContent=scope==='exterior'?regionText('Fuera de')+' '+country:country;
 show('mapPage');loadLocalPublications();
}

let localPublicationsGeneration = 0, localPublicationsOffset = 0;
function localSearchText(){return document.querySelector('#promptText').value.trim() || document.querySelector('#searchText').value.trim();}
async function loadLocalPublications(append = false) {
 const generation = ++localPublicationsGeneration, chosenCountry = country, chosenCity = city, chosenRegion = publicationRegion;
 const chosenCategory = localCategory?.id || '', chosenQuery = localSearchText();
 const params = new URLSearchParams({pais:chosenCountry, ciudad:chosenCity, offset:String(append ? localPublicationsOffset : 0)});
 if(chosenRegion!=='local')params.set('alcance',chosenRegion);
 if (chosenCategory) params.set('categoria_id', chosenCategory);
 else if(typeof queryJourney!=='undefined'&&queryJourney){
  const ids=journeyCategories().map(item=>item.categoria_id);
  if(ids.length)params.set('categoria_ids',ids.join(','));
  else{document.querySelector('#localPublications').replaceChildren();document.querySelector('#localPublicationsStatus').textContent=regionText('No hay ámbitos y categorías compatibles con esta opción en la ubicación seleccionada.');document.querySelector('#moreLocalPublications').hidden=true;document.querySelector('#retryLocalPublications').hidden=true;return;}
 }
 if (chosenQuery) params.set('q', chosenQuery);
 document.querySelector('#localPublicationsHeading').textContent = [regionText(chosenRegion==='local'?'Publicaciones locales':chosenRegion==='pais'?'Publicaciones del país':'Publicaciones del exterior'), localCategory?.name, chosenQuery].filter(Boolean).join(' · ');
 const grid = document.querySelector('#localPublications'), status = document.querySelector('#localPublicationsStatus');
 const retry = document.querySelector('#retryLocalPublications'), more = document.querySelector('#moreLocalPublications');
 if (!append) { localPublicationsOffset = 0; grid.replaceChildren(); }
 retry.hidden = true; more.hidden = true; status.textContent = regionText(chosenRegion==='local'?'Cargando publicaciones locales…':'Cargando publicaciones…');
 try {
  const response = await fetch('/api/publicaciones/locales?' + params, {signal:AbortSignal.timeout(20000)});
  const payload = await response.json();
  if (!response.ok || !payload.success || !Array.isArray(payload.publicaciones)) throw new Error('publications');
  if (generation !== localPublicationsGeneration || country !== chosenCountry || city !== chosenCity || publicationRegion !== chosenRegion || (localCategory?.id || '') !== chosenCategory || localSearchText() !== chosenQuery) return;
  for (const item of payload.publicaciones) {
   const card = document.createElement('article'); card.className = 'product';
   const image = document.createElement('img'); image.alt = ''; image.loading = 'lazy'; image.src = '/static/images/industry.svg';
   try { const url = new URL(item.imagen, location.origin); if (item.imagen && ['https:', 'http:'].includes(url.protocol)) image.src = url.href; } catch (_) {}
   image.onerror = () => { image.onerror = null; image.src = '/static/images/industry.svg'; };
   const title = document.createElement('strong'); title.textContent = item.titulo;
   const description = document.createElement('p'); description.textContent = item.descripcion || '';
   const detail = document.createElement('small'); detail.textContent = chosenRegion==='local'?chosenCity:(chosenRegion==='pais'?chosenCountry:'');
   card.append(image, title, description, detail);
   if (item.precio != null) {
    const price = document.createElement('small'); price.textContent = `${item.precio} ${item.moneda || ''}`.trim(); card.append(price);
   }
   card.dataset.catalogName = ''; grid.append(card);
  }
  localPublicationsOffset += payload.publicaciones.length;
  status.textContent = grid.children.length ? '' : chosenRegion!=='local'?regionText('No hay publicaciones que coincidan con esta búsqueda en la región seleccionada.'):(chosenQuery ? `No hay publicaciones locales que coincidan con «${chosenQuery}» en esta ciudad y categoría.` : 'No hay publicaciones locales disponibles en esta ciudad.');
  more.hidden = !payload.has_more;
 } catch (_) {
  if (generation !== localPublicationsGeneration || country !== chosenCountry || city !== chosenCity || publicationRegion !== chosenRegion || (localCategory?.id || '') !== chosenCategory || localSearchText() !== chosenQuery) return;
  status.textContent = regionText(chosenRegion==='local'?'No se pudieron cargar las publicaciones locales.':'No se pudieron cargar las publicaciones.'); retry.hidden = false;
  retry.onclick = () => loadLocalPublications(append);
 }
 more.onclick = () => loadLocalPublications(true);
}

// Home uses existing local publications, independently of the consultation draft.
let homePublicationsRequest=0,homePublicationsCache=null;
const homePublicationMessages={
 es:{loading:'Cargando publicaciones de tu ciudad…',empty:'No hay publicaciones de tus intereses en esta ciudad.',interests:'Elegí tus ámbitos de interés para ver publicaciones cercanas.',error:'No se pudieron cargar las publicaciones. Reintentá.',close:'Cerrar',detail:'Detalle de la publicación',refresh:'Recargar ↗'},
 en:{loading:'Loading publications in your city…',empty:'No publications match your interests in this city.',interests:'Choose your interests to see nearby publications.',error:'Could not load publications. Try again.',close:'Close',detail:'Publication details',refresh:'Refresh ↗'},
 pl:{loading:'Wczytywanie ogłoszeń z Twojego miasta…',empty:'Brak ogłoszeń zgodnych z Twoimi zainteresowaniami w tym mieście.',interests:'Wybierz zainteresowania, aby zobaczyć pobliskie ogłoszenia.',error:'Nie udało się wczytać ogłoszeń. Spróbuj ponownie.',close:'Zamknij',detail:'Szczegóły ogłoszenia',refresh:'Odśwież ↗'},
 it:{loading:'Caricamento annunci della tua città…',empty:'Nessun annuncio corrisponde ai tuoi interessi in questa città.',interests:'Scegli i tuoi interessi per vedere gli annunci vicini.',error:'Impossibile caricare gli annunci. Riprova.',close:'Chiudi',detail:'Dettagli annuncio',refresh:'Aggiorna ↗'}
};
function homePublicationImage(item){
 const visual=document.createElement('div');visual.className='scraped-product-visual';
 const url=safeQueryUrl(item.imagen);
 if(url){const image=document.createElement('img');image.src=url;image.alt='';image.loading='lazy';image.onerror=()=>image.remove();visual.append(image);}
 return visual;
}
async function openHomePublication(item){
 const messages=homePublicationMessages[catalogLanguage()]||homePublicationMessages.es;
 const previous=document.activeElement,overlay=document.createElement('div');overlay.className='auth-overlay publication-detail-overlay';
 const dialog=document.createElement('div');dialog.className='auth-dialog profile-dialog publication-detail-dialog';dialog.setAttribute('role','dialog');dialog.setAttribute('aria-modal','true');dialog.setAttribute('aria-labelledby','homePublicationTitle');
 const close=document.createElement('button');close.className='auth-close';close.type='button';close.textContent='×';close.setAttribute('aria-label',messages.close);
 const title=document.createElement('h2');title.id='homePublicationTitle';title.textContent=messages.detail;
 const content=document.createElement('div');content.textContent='Cargando publicación…';content.setAttribute('role','status');
 dialog.append(close,title,content);overlay.append(dialog);document.body.append(overlay);close.focus();
 const dismiss=()=>{overlay.remove();previous?.focus();};close.onclick=dismiss;
 overlay.onclick=event=>{if(event.target===overlay)dismiss();};
 overlay.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();dismiss();}if(event.key==='Tab'){const targets=[...dialog.querySelectorAll('button,a[href]')];if(event.shiftKey&&document.activeElement===targets[0]){event.preventDefault();targets.at(-1).focus();}else if(!event.shiftKey&&document.activeElement===targets.at(-1)){event.preventDefault();targets[0].focus();}}};
 try{
  const response=await fetch('/api/publicaciones/'+encodeURIComponent(item.id),{cache:'no-store'}),data=await response.json();
  if(!overlay.isConnected)return;
  if(!response.ok||!data.success)throw new Error(data.error||'No se pudo consultar la publicación.');
  const saved=data.publicacion;title.textContent=saved.titulo;title.dataset.catalogName='';content.replaceChildren();
  const gallery=document.createElement('div');gallery.className='publication-detail-gallery';
  for(const value of saved.imagenes||[]){const url=safeQueryUrl(value);if(!url)continue;const image=document.createElement('img');image.src=url;image.alt=saved.titulo;image.onerror=()=>image.remove();gallery.append(image);}
  const description=document.createElement('p');description.className='publication-detail-description';description.textContent=saved.descripcion||'';
  const price=document.createElement('p');price.className='publication-detail-price';price.textContent=saved.precio==null?'Precio no informado':`${saved.precio} ${saved.moneda||''}`.trim();
  const metadata=document.createElement('dl');metadata.className='publication-detail-metadata';
  for(const [label,key] of [['Ámbito','ambito'],['Categoría','categoria'],['Ciudad','ciudad'],['Código postal','codigoPostal'],['País','pais'],['Idioma','idioma'],['Fecha','fecha']]){if(!saved[key])continue;const term=document.createElement('dt'),value=document.createElement('dd');term.textContent=label;value.textContent=saved[key];metadata.append(term,value);}
  content.append(gallery,price,description);
  if(saved.texto&&saved.texto!==saved.descripcion&&!/^(pwa|b44)-[0-9a-f]{64}$/i.test(saved.texto)){const body=document.createElement('p');body.className='publication-detail-description';body.dataset.catalogName='';body.textContent=saved.texto;content.append(body);}
  content.append(metadata);
  const url=safeQueryUrl(saved.afiliado_link);if(url){const link=document.createElement('a');link.href=url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Ver producto';content.append(link);}
 }catch(error){if(overlay.isConnected)content.textContent=error.message;}
}
function renderHomePublications(items){
 const grid=document.querySelector('#products');grid.replaceChildren();grid.scrollLeft=0;
 for(const item of items){
  const card=document.createElement('button');card.type='button';card.className='product';card.dataset.publicationId=item.id;card.dataset.catalogName='';
  const title=document.createElement('strong');title.textContent=item.titulo;
  const detail=document.createElement('small');detail.textContent=item.precio==null?(item.ciudad||city):`${item.precio} ${item.moneda||''}`.trim();
  if(item.destacado){const badge=document.createElement('small');badge.className='promotion-badge';badge.textContent={es:'Destacado',en:'Featured',pl:'Promowane',it:'In evidenza'}[catalogLanguage()]||'Destacado';card.append(badge);}
  card.append(homePublicationImage(item),title,detail);card.onclick=()=>openHomePublication(item);grid.append(card);
 }
 requestAnimationFrame(updateHomeCarousel);
}
async function loadHomePublications(force=false){
 const generation=++homePublicationsRequest,status=document.querySelector('#homePublicationsStatus'),grid=document.querySelector('#products');
 if(!status)return;
 const messages=homePublicationMessages[catalogLanguage()]||homePublicationMessages.es;
 const refresh=document.querySelector('#refreshHomePublications');refresh.textContent=messages.refresh;refresh.onclick=()=>loadHomePublications(true);
 if(!country||!city||catalogState.ambitos==='loading'||catalogState.categorias==='loading'){grid.replaceChildren();updateHomeCarousel();status.textContent=messages.loading;return;}
 if(catalogState.ambitos==='error'||catalogState.categorias==='error'){grid.replaceChildren();updateHomeCarousel();status.textContent=messages.error;return;}
 const categoryIds=catalogCategorias.filter(item=>item.ambito_ids.some(id=>selected.has(String(id)))).map(item=>item.categoria_id);
 const chosenCountry=country,chosenCity=city,key=JSON.stringify([country,city,catalogLanguage(),categoryIds,typeof currentEmail==='string'?currentEmail:null,Math.floor(Date.now()/172800000)]);
 const apply=items=>{renderHomePublications(items);status.textContent=items.length?'':messages.empty;};
 if(!force&&homePublicationsCache?.key===key&&Date.now()-homePublicationsCache.time<60000){apply(homePublicationsCache.items);return;}
 grid.replaceChildren();updateHomeCarousel();status.textContent=messages.loading;
 try{
  const params=new URLSearchParams({pais:chosenCountry,ciudad:chosenCity,rotar:'1',promociones:categoryIds.length?'1':'solo'});
  if(categoryIds.length)params.set('categoria_ids',categoryIds.join(','));
  const response=await fetch('/api/publicaciones/locales?'+params,{signal:AbortSignal.timeout(20000)}),payload=await response.json();
  if(!response.ok||!payload.success||!Array.isArray(payload.publicaciones))throw new Error('publications');
  if(generation!==homePublicationsRequest||country!==chosenCountry||city!==chosenCity)return;
  homePublicationsCache={key,time:Date.now(),items:payload.publicaciones};apply(payload.publicaciones);
 }catch(_){if(generation===homePublicationsRequest)status.textContent=messages.error;}
}

function updateHomeCarousel(){
 const grid=document.querySelector('#products'),controls=document.querySelector('#homeCarouselControls');
 if(!grid||!controls)return;
 controls.hidden=grid.children.length<2||grid.scrollWidth<=grid.clientWidth+2;
 document.querySelector('#homeCarouselPrevious').disabled=grid.scrollLeft<=2;
 document.querySelector('#homeCarouselNext').disabled=grid.scrollLeft+grid.clientWidth>=grid.scrollWidth-2;
 const labels={es:['Publicaciones anteriores','Publicaciones siguientes'],en:['Previous publications','Next publications'],pl:['Poprzednie ogłoszenia','Następne ogłoszenia'],it:['Annunci precedenti','Annunci successivi']}[catalogLanguage()]||['Previous publications','Next publications'];
 document.querySelector('#homeCarouselPrevious').setAttribute('aria-label',labels[0]);document.querySelector('#homeCarouselNext').setAttribute('aria-label',labels[1]);
}
for(const [id,direction] of [['homeCarouselPrevious',-1],['homeCarouselNext',1]])document.querySelector('#'+id).onclick=()=>{
 const grid=document.querySelector('#products');grid.scrollBy({left:direction*grid.clientWidth*.8,behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});
};
document.querySelector('#products').addEventListener('scroll',updateHomeCarousel,{passive:true});
window.addEventListener('resize',updateHomeCarousel);

// Refresh only a visible, idle home screen; do not interrupt a card being used.
function refreshHomeRotation(){
 if(typeof page==='undefined'||page!=='home'||document.hidden)return;
 if(document.querySelector('.auth-overlay:not([hidden])')||document.querySelector('#products')?.contains(document.activeElement))return;
 if(homePublicationsCache&&Date.now()-homePublicationsCache.time<60000)return;
 loadHomePublications();
}
setInterval(refreshHomeRotation,60000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshHomeRotation();});
