// Explicit journeys use only IDs verified in the checked-in real catalogue.
let queryJourney=null;
const employmentCategoryIds=new Set([41,778]); // Trabajo Remoto; Oportunidades laborales.
const commercialScopeIds=new Set([6,10,108,109]); // Distribuidores, Supermercado, Mayorista, Minorista.
function journeyCategories(){
 if(!queryJourney)return catalogCategorias;
 if(queryJourney==='jobs')return catalogCategorias.filter(item=>employmentCategoryIds.has(Number(item.categoria_id)));
 const allowed=queryJourney==='import'?new Set([6,108]):commercialScopeIds;
 return catalogCategorias.filter(item=>!employmentCategoryIds.has(Number(item.categoria_id))&&item.ambito_ids.some(id=>allowed.has(Number(id))));
}
function journeyScopes(){
 if(!queryJourney)return catalogAmbitos;
 const categories=journeyCategories();
 const allowed=queryJourney==='jobs'?null:queryJourney==='import'?new Set([6,108]):commercialScopeIds;
 return catalogAmbitos.filter(scope=>(!allowed||allowed.has(Number(scope.ambito_id)))&&categories.some(item=>item.ambito_ids.includes(scope.ambito_id)));
}
function setQueryJourney(value){
 queryJourney=value;
 document.querySelector('#queryScope').value='';document.querySelector('#queryCategory').value='';
 const prompt=document.querySelector('#promptText');
 if(prompt.value===exploreAutoDraft||prompt.value===novelAutoDraft)prompt.value='';
 exploreAutoDraft='';novelAutoDraft='';exploreBudgetDraft='';
 localCategory=null;refreshQuerySelectors();
}
// Employment categories 41 and 778, verified in catalog-reference.json.
function isEmploymentQuery(ids){return employmentCategoryIds.has(Number(ids?.categoria_id??document.querySelector('#queryCategory').value));}
function employmentDraft(){
 const template=window.DPIAI18N?.translate('Orientame sobre oportunidades laborales en {categoria}, dentro de {ambito}, para {ciudad}, {pais}. Considerá puestos, experiencia, requisitos y modalidad. No inventes vacantes, empresas, salarios ni enlaces. Diferenciá orientaciones de ofertas verificadas y usá N/D para datos no confirmados.')||'';
 return template.replace('{categoria}',document.querySelector('#queryCategory').selectedOptions[0]?.textContent||'').replace('{ambito}',document.querySelector('#queryScope').selectedOptions[0]?.textContent||'').replace('{ciudad}',city).replace('{pais}',country);
}
function syncEmploymentFilters(){
 const jobs=isEmploymentQuery(),panel=document.querySelector('#queryBudget');
 for(const child of panel.children)child.hidden=jobs?child.id!=='querySalaryFilters':child.id==='querySalaryFilters';
 for(const id of ['toggleQueryBudget','queryBudget']){
  const el=document.getElementById(id),key=jobs?'Filtros laborales':'budget.filters';
  el.setAttribute('data-i18n-aria-label',key);if(id==='toggleQueryBudget')el.setAttribute('data-i18n-title',key);
 }
}
// The original user request is preserved; context and identity are verified by Flask.
let queryMode='buscar', queryPrepared=null, queryBusy=false, queryRequestId=null, pendingSourcesGeneration=false;
let novelAutoDraft='', exploreAutoDraft='', exploreBudgetDraft='', queryBudgetCountry='', queryBudgetOpen=false, queryBudgetEdited=false;
let queryPreparationTimer=null, queryPreparationQueued=false;
const externalQuerySources=['amazon','ebay','aliexpress','mercadolibre'];
const querySources=[...externalQuerySources,'local','dpia','historial'];
function sourceAvailableForCountry(source){return (!externalQuerySources.includes(source)||(window.DPIA_ENABLED_MARKETPLACES||['amazon','mercadolibre']).includes(source))&&(source!=='mercadolibre'||['Argentina','México'].includes(country));}
function refreshQuerySelectors(category=null, scopeId=null){
 const scopeSelect=document.querySelector('#queryScope'), categorySelect=document.querySelector('#queryCategory'), postalSelect=document.querySelector('#queryPostal');
 const oldScope=scopeSelect.value,oldCategory=categorySelect.value,oldPostal=postalSelect.value;
 scopeSelect.replaceChildren(new Option('Elegí un ámbito',''));
 for(const scope of journeyScopes()){const option=new Option(scope.nombre,String(scope.ambito_id));option.dataset.catalogName='';scopeSelect.add(option);}
 const desired=scopeId||category?.ambito_ids.find(id=>journeyScopes().some(scope=>scope.ambito_id===id))||oldScope;
 if([...scopeSelect.options].some(option=>option.value===String(desired)))scopeSelect.value=String(desired);
 categorySelect.replaceChildren(new Option('Elegí una categoría',''));
 for(const item of journeyCategories().filter(item=>item.ambito_ids.includes(Number(scopeSelect.value)))){
  const option=new Option(item.nombre,String(item.categoria_id));option.dataset.catalogName='';categorySelect.add(option);
 }
 const categoryId=category?.categoria_id||(oldScope===scopeSelect.value?oldCategory:'');
 if([...categorySelect.options].some(option=>option.value===String(categoryId)))categorySelect.value=String(categoryId);
 if(queryMode==='novedades'&&!categorySelect.value&&categorySelect.options.length>1)categorySelect.selectedIndex=1;
 document.querySelector('#queryCity').value=city;
 postalSelect.replaceChildren();
 for(const record of catalogPostalCodes)postalSelect.add(new Option(city,String(record.id)));
 if([...postalSelect.options].some(option=>option.value===oldPostal))postalSelect.value=oldPostal;
 invalidateQuery();if(queryMode==='novedades')updateNovelDraft();else if(queryMode==='explorar')updateExploreDraft();
}
function syncQueryConversation(){
 const prepared=!!queryPrepared&&JSON.stringify(queryBody())===queryPrepared.fingerprint;
 const sent=prepared&&!!(queryPrepared.sent||queryPrepared.pending);
 document.querySelector('#promptResult').hidden=!prepared;
 document.querySelector('#preparePrompt').hidden=false;
 document.querySelector('#preparePrompt').disabled=queryBusy||sent||(!prepared&&!!currentEmail);
 document.querySelector('#preparePrompt').setAttribute('data-i18n-aria-label',queryPrepared?.pending?'Consulta pendiente de confirmación':sent?'Consulta enviada':'Enviar consulta →');
 document.querySelector('#preparePrompt').setAttribute('data-i18n-title',document.querySelector('#preparePrompt').getAttribute('data-i18n-aria-label'));
 document.querySelector('#queryReadyPanel').hidden=!prepared;
 // Keep the existing send handler available without a second visible action.
 document.querySelector('#generateQuery').hidden=true;
 document.querySelector('#generateQuery').disabled=queryBusy;
 document.querySelector('#queryConversation').setAttribute('aria-busy',String(queryBusy));
 document.querySelector('#queryReadyMessage').setAttribute('data-i18n',queryPrepared?.pending?'La consulta está pendiente de confirmación. Consultá su estado antes de volver a enviarla.':sent?'Consulta enviada. Podés editar el pedido para preparar otra consulta.':'Esto es lo que se enviará. Podés modificar el pedido o los filtros antes de enviar.');
 window.DPIAI18N?.refresh();
}
function submitConsultQuery(){
 if(queryBusy)return;
 if(!currentEmail){openAuth();return;}
 if(!queryPrepared||JSON.stringify(queryBody())!==queryPrepared.fingerprint)return;
 return generateDPIAQuery();
}
function queueQueryPreparation(){
 clearTimeout(queryPreparationTimer);
 queryPreparationTimer=setTimeout(()=>{
  if(page!=='consultPage'||!currentEmail||catalogState.ambitos!=='ready'||catalogState.categorias!=='ready')return;
  if(queryBusy){queryPreparationQueued=true;return;}
  const body=queryBody();
  if(queryPrepared&&JSON.stringify(body)===queryPrepared.fingerprint)return;
  if(!body.ambito_id||!body.categoria_id||(!body.user_message&&!body.attachments.length))return;
  prepareDPIAQuery({automatic:true});
 },600);
}
function syncQueryBudgetPanel(){
 syncEmploymentFilters();
 document.querySelector('#toggleQueryBudget').hidden=false;
 document.querySelector('#toggleQueryBudget').setAttribute('aria-expanded',String(queryBudgetOpen));
 document.querySelector('#queryBudget').hidden=!queryBudgetOpen;
}
function setQueryBudgetOpen(open){if(open)setupExploreBudget();queryBudgetOpen=!!open;syncQueryBudgetPanel();}
document.querySelector('#toggleQueryBudget').onclick=()=>setQueryBudgetOpen(!queryBudgetOpen);
document.querySelector('#toggleQueryBudget').addEventListener('keydown',event=>{if(event.key==='Escape'&&queryBudgetOpen){event.stopPropagation();setQueryBudgetOpen(false);}});
document.querySelector('#queryBudget').addEventListener('keydown',event=>{
 if(event.key==='Escape'){event.stopPropagation();setQueryBudgetOpen(false);document.querySelector('#toggleQueryBudget').focus();}
});
function invalidateQuery(schedule=true){
 syncQueryBudgetPanel();
 if(schedule){if(queryBusy)queryPreparationQueued=true;queueQueryPreparation();}
 if(queryBusy){syncQueryConversation();return;}
 queryPrepared=null;queryRequestId=null;document.querySelector('#generateQuery').hidden=true;document.querySelector('#queryResults').replaceChildren();document.querySelector('#promptResult').hidden=true;syncQueryConversation();
}
function chooseQueryCategory(item, scopeId=null){queryMode='buscar';refreshQuerySelectors(item,scopeId);localCategory={id:String(item.categoria_id),name:item.nombre};}
function updateNovelDraft(force=false){
 const prompt=document.querySelector('#promptText'),scope=document.querySelector('#queryScope'),category=document.querySelector('#queryCategory');
 if(!scope.value||!category.value||(!force&&prompt.value.trim()&&prompt.value!==novelAutoDraft))return;
 const a=scope.selectedOptions[0].textContent,c=category.selectedOptions[0].textContent;
 const templates={
  es:`Buscá novedades y productos relevantes de ${c}, en el ámbito ${a}, para ${city}, ${country}. Proponé una búsqueda concreta de productos útiles y evitá duplicados. No inventes precios ni presentes tendencias como verificadas sin evidencia.`,
  en:`Find new and relevant products in ${c}, within ${a}, for ${city}, ${country}. Prepare a focused search for useful products and avoid duplicates. Do not invent prices or present trends as verified without evidence.`,
  it:`Cerca novità e prodotti rilevanti di ${c}, nell'ambito ${a}, per ${city}, ${country}. Prepara una ricerca concreta di prodotti utili, evitando duplicati. Non inventare prezzi o presentare tendenze come verificate senza prove.`,
  pl:`Znajdź nowości i przydatne produkty w kategorii ${c}, w obszarze ${a}, dla ${city}, ${country}. Przygotuj konkretne wyszukiwanie i unikaj duplikatów. Nie wymyślaj cen ani nie przedstawiaj trendów jako potwierdzonych bez dowodów.`};
 if(isEmploymentQuery()){queryMode='explorar';setupExploreBudget();updateExploreDraft(true);return;}
 novelAutoDraft=templates[catalogLanguage()]||templates.es;prompt.value=novelAutoDraft;
}
async function openNovelQuery(){
 if(queryBusy)return;
 queryMode='novedades';show('consultPage');invalidateQuery();
 const status=document.querySelector('#queryStatus');status.textContent='Cargando tus intereses para preparar novedades…';
 if(catalogState.ambitos==='loading'||catalogState.categorias==='loading')await loadCatalogs();
 const available=journeyScopes();
 const interests=available.filter(scope=>selected.has(String(scope.ambito_id)));
 const scopes=(queryJourney?available:(interests.length?interests:available)).filter(scope=>journeyCategories().some(category=>category.ambito_ids.includes(scope.ambito_id)));
 const current=document.querySelector('#queryScope').value;
 const scope=scopes.find(item=>String(item.ambito_id)===current)||scopes.find(item=>String(item.ambito_id)===activeCatalogScope)||scopes[0];
 if(!scope){refreshQuerySelectors();status.textContent=window.DPIAI18N.translate('No hay ámbitos y categorías compatibles con esta opción en la ubicación seleccionada.');return;}
 const oldCategory=Number(document.querySelector('#queryCategory').value);
 const category=journeyCategories().find(item=>item.categoria_id===oldCategory&&item.ambito_ids.includes(scope.ambito_id))||journeyCategories().find(item=>item.ambito_ids.includes(scope.ambito_id));
 refreshQuerySelectors(category,scope.ambito_id);syncLocalCategory();updateNovelDraft(true);
 status.textContent='Revisá los datos y el pedido. Prepará la consulta y confirmá cuando esté lista para enviar.';
}

async function openExploreQuery(){
 if(queryBusy)return;
 await openNovelQuery();queryMode='explorar';invalidateQuery();
 setupExploreBudget();updateExploreDraft(true);
 if(queryJourney&&(!document.querySelector('#queryScope').value||!document.querySelector('#queryCategory').value)){document.querySelector('#queryStatus').textContent=window.DPIAI18N.translate('No hay ámbitos y categorías compatibles con esta opción en la ubicación seleccionada.');return;}
 document.querySelector('#queryStatus').textContent='Revisá el pedido. Explorar genera sugerencias con IA, sin consumir ejecuciones de scraping.';
}
function updateExploreDraft(force=false){
 const prompt=document.querySelector('#promptText'),scopeSelect=document.querySelector('#queryScope'),categorySelect=document.querySelector('#queryCategory');
 if(!force&&prompt.value.trim()&&prompt.value!==exploreAutoDraft)return;
 if(!scopeSelect.value||!categorySelect.value){exploreAutoDraft='';prompt.value='';return;}
 const scope=scopeSelect.selectedOptions[0].textContent,category=categorySelect.selectedOptions[0].textContent;
 const drafts={es:`Sugerí productos útiles de ${category}, en ${scope}, para ${city}, ${country}. Explicá sus ventajas y proponé precios de venta orientativos cuando puedas fundamentarlos. Indicá sitios donde pueda comparar opciones.`,en:`Suggest useful products in ${category}, within ${scope}, for ${city}, ${country}. Explain their benefits and suggest indicative selling prices when justified. Include sites where I can compare options.`,it:`Suggerisci prodotti utili di ${category}, nell'ambito ${scope}, per ${city}, ${country}. Spiega i vantaggi e proponi prezzi indicativi quando motivati. Indica siti dove confrontare le opzioni.`,pl:`Zaproponuj przydatne produkty w kategorii ${category}, w obszarze ${scope}, dla ${city}, ${country}. Wyjaśnij zalety i zaproponuj uzasadnione ceny orientacyjne. Wskaż serwisy do porównania ofert.`};
 exploreBudgetDraft=exploreBudgetText();exploreAutoDraft=(isEmploymentQuery()?employmentDraft():drafts[catalogLanguage()]||drafts.es)+'\n'+exploreBudgetDraft;prompt.value=exploreAutoDraft;
}
function setupExploreBudget(){
 syncEmploymentFilters();
 const currency={Argentina:'ARS',Uruguay:'UYU','España':'EUR',Italia:'EUR',Polonia:'PLN','México':'MXN'}[country]||'USD';
 if(queryBudgetCountry!==country){
  const range={ARS:[10000,100000],UYU:[500,5000],EUR:[10,100],PLN:[50,500],MXN:[200,2000],USD:[10,100]}[currency];
  document.querySelector('#queryBudgetMin').value=range[0];document.querySelector('#queryBudgetMax').value=range[1];queryBudgetCountry=country;queryBudgetEdited=false;
  document.querySelector('#queryBudgetCurrency').value=currency;document.querySelector('#querySalaryCurrency').value=currency;
 }
}
function exploreBudgetText(){
 if(isEmploymentQuery()){
  const min=document.getElementById('querySalaryMin').value,max=document.getElementById('querySalaryMax').value;
  if(!min&&!max)return '';
  const tr=text=>window.DPIAI18N?.translate(text)||text;
  return tr('Remuneración pretendida:')+' '+(min||'N/D')+' – '+(max||'N/D')+' '+document.getElementById('querySalaryCurrency').value+' '+tr(document.getElementById('querySalaryPeriod').selectedOptions[0].getAttribute('data-i18n'))+'. '+tr('Es una expectativa del usuario, no un salario verificado.');
 }

 const min=document.querySelector('#queryBudgetMin').value,max=document.querySelector('#queryBudgetMax').value,currency=document.querySelector('#queryBudgetCurrency').value;
 const total=document.querySelector('#queryBudgetType').value==='total';
 const units={es:total?'en total':'por producto',en:total?'in total':'per product',it:total?'in totale':'per prodotto',pl:total?'łącznie':'za produkt'};
 const lang=catalogLanguage(),unit=units[lang]||units.es;
 return ({es:`Presupuesto de compra: de ${min} a ${max} ${currency} ${unit}. Respetá este máximo; no lo confundas con el precio de venta sugerido.`,en:`Purchase budget: ${min} to ${max} ${currency} ${unit}. Respect this maximum; do not confuse it with the suggested selling price.`,it:`Budget di acquisto: da ${min} a ${max} ${currency} ${unit}. Rispetta questo massimo; non confonderlo con il prezzo di vendita suggerito.`,pl:`Budżet zakupu: od ${min} do ${max} ${currency} ${unit}. Przestrzegaj tego limitu; nie myl go z sugerowaną ceną sprzedaży.`})[lang]||`Presupuesto de compra: de ${min} a ${max} ${currency} ${unit}.`;
}
function syncExploreBudget(){
 queryBudgetEdited=true;
 const prompt=document.querySelector('#promptText'),automatic=queryMode==='explorar'&&prompt.value===exploreAutoDraft,next=exploreBudgetText();
 if(automatic){updateExploreDraft(true);}else{
  prompt.value=exploreBudgetDraft&&prompt.value.includes(exploreBudgetDraft)?prompt.value.replace(exploreBudgetDraft,next):prompt.value.trim()+'\n'+next;
  exploreBudgetDraft=next;
 }
 invalidateQuery();
}
document.querySelector('#queryBudgetCurrency').addEventListener('change',()=>{
 const currency=document.querySelector('#queryBudgetCurrency').value;
 const range={ARS:[10000,100000],UYU:[500,5000],EUR:[10,100],PLN:[50,500],MXN:[200,2000],USD:[10,100],GBP:[10,100],BRL:[50,500],CAD:[15,150],AUD:[15,150],COP:[50000,500000]}[currency];
 document.querySelector('#queryBudgetMin').value=range[0];document.querySelector('#queryBudgetMax').value=range[1];syncExploreBudget();
});
for(const id of ['queryBudgetType','queryBudgetMin','queryBudgetMax'])document.querySelector('#'+id).addEventListener(id==='queryBudgetType'?'change':'input',syncExploreBudget);
function queryBody(){return {pais:country,ciudad:city,idioma:catalogLanguage(),ambito_id:Number(document.querySelector('#queryScope').value),categoria_id:Number(document.querySelector('#queryCategory').value),codigo_postal_id:Number(document.querySelector('#queryPostal').value),mode:queryMode,...(queryMode==='explorar'?{budget_currency:document.querySelector(isEmploymentQuery()?'#querySalaryCurrency':'#queryBudgetCurrency').value}:{}),user_message:document.querySelector('#promptText').value.trim(),attachments:media};}
function startHomeQuery(){
 document.querySelector('#promptText').value=document.querySelector('#searchText').value.trim();queryMode='buscar';queryBudgetEdited=false;setupExploreBudget();invalidateQuery();show('consultPage');prepareDPIAQuery();
}
async function prepareDPIAQuery({automatic=false}={}){
 clearTimeout(queryPreparationTimer);
 if(queryBusy)return;show('consultPage');
 if(!currentEmail){openAuth();return;}
 await queryMediaPending;if(queryBusy)return;
 if(isEmploymentQuery()){
  const min=document.getElementById('querySalaryMin'),max=document.getElementById('querySalaryMax');
  max.setCustomValidity('');
  if(min.value&&max.value&&Number(max.value)<Number(min.value))max.setCustomValidity(window.DPIAI18N.translate('Ingresá un rango de remuneración válido.'));
  if(!min.checkValidity()||!max.checkValidity()){setQueryBudgetOpen(true);min.reportValidity();max.reportValidity();return;}
 }else if(queryMode==='explorar'||queryBudgetEdited){
  const min=document.querySelector('#queryBudgetMin'),max=document.querySelector('#queryBudgetMax');
  max.setCustomValidity('');
  if(!min.value||!max.value||Number(max.value)<Number(min.value))max.setCustomValidity(({es:'Ingresá un rango válido: el máximo debe ser mayor o igual al mínimo.',en:'Enter a valid range: maximum must be at least the minimum.',it:'Inserisci un intervallo valido: il massimo deve essere almeno il minimo.',pl:'Podaj poprawny zakres: maksimum nie może być mniejsze od minimum.'})[catalogLanguage()]||'Invalid range');
  if(!min.checkValidity()||!max.checkValidity())setQueryBudgetOpen(true);
  if(!min.reportValidity()||!max.reportValidity()){setQueryArtState('warning');return;}
 }
 const status=document.querySelector('#queryStatus'),body=structuredClone(queryBody());
 if(!body.ambito_id||!body.categoria_id){setQueryArtState('warning');status.textContent='Elegí un ámbito y una categoría para continuar.';document.querySelector(body.ambito_id?'#queryCategory':'#queryScope').focus();return;}
 if(!body.user_message&&!body.attachments.length){setQueryArtState('warning');status.textContent='Escribí tu pedido o adjuntá una imagen o video.';return;}
 invalidateQuery(false);queryBusy=true;syncQueryConversation();status.textContent='Preparando tu consulta…';
 try{
  const response=await fetch('/api/consultas/preparar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(45000)});
  const data=await response.json();if(response.status===401)openAuth();if(!response.ok||!data.success)throw new Error(data.error||'No se pudo preparar la consulta.');
  if(JSON.stringify(queryBody())!==JSON.stringify(body)){
   status.textContent='El pedido cambió. DPIA está actualizando el resumen.';return;
  }
  queryPrepared={body:structuredClone(body),fingerprint:JSON.stringify(body),summary:data.summary};
  document.querySelector('#promptResult').textContent=data.summary;
  status.textContent='Revisá la respuesta de DPIA y enviá cuando esté lista. Los cambios se actualizan automáticamente.';
 }catch(error){status.textContent=error.name==='TimeoutError'?'La preparación tardó demasiado. Reintentá.':error.message;}
 finally{queryBusy=false;syncQueryConversation();if(queryPrepared&&!automatic)document.querySelector('#queryReadyMessage').focus();if(queryPreparationQueued){queryPreparationQueued=false;queueQueryPreparation();}}
}
function sourcePreferenceKey(){return 'dpia-query-sources:'+currentEmail+':'+country;}
function savedQuerySources(){
 try{const saved=JSON.parse(localStorage.getItem(sourcePreferenceKey()));return Array.isArray(saved)&&saved.length&&saved.every(s=>querySources.includes(s)&&sourceAvailableForCountry(s))&&saved.filter(s=>externalQuerySources.includes(s)).length<=1?[...new Set(saved)]:null;}catch(_){return null;}
}
function openSourceModal(generateAfter=false){
 if(queryBusy)return;
 pendingSourcesGeneration=generateAfter;
 const exploring=queryMode==='explorar',novel=queryMode==='novedades';
 document.querySelector('#queryAIOrigin').hidden=!exploring&&!novel;
 document.querySelector('#queryAIOriginNotice').setAttribute('data-i18n',novel?'sources.novelNotice':'sources.aiNotice');
 document.querySelector('#querySourcesHint').hidden=exploring;
 document.querySelector('#allQuerySources').closest('label').hidden=exploring;
 document.querySelector('.query-source-options').hidden=exploring;
 const confirm=document.querySelector('#confirmQuerySources');
 if(generateAfter)confirm.setAttribute('data-i18n',exploring?'sources.confirmAI':'sources.confirmSearch');
 else{confirm.removeAttribute('data-i18n');confirm.textContent=window.DPIAI18N.translate('Guardar y continuar');}
 window.DPIAI18N.refresh();
 const selected=savedQuerySources()||['amazon'];
 document.querySelector('#allQuerySources').checked=['local','dpia','historial'].every(source=>selected.includes(source));
 for(const checkbox of document.querySelectorAll('[name="querySource"]')){
  const source=checkbox.value,label=checkbox.closest('label');
  const regional=source==='allegro'?country==='Polonia':source!=='mercadolibre'||['Argentina','México'].includes(country);
  if(['mercadolibre','allegro'].includes(source))label.hidden=!regional;
  checkbox.disabled=source==='allegro'||!sourceAvailableForCountry(source);checkbox.checked=!checkbox.disabled&&selected.includes(source);
  if(externalQuerySources.includes(source)){
   let note=label.querySelector('[data-marketplace-disabled]');
   if(checkbox.disabled){if(!note){note=document.createElement('small');note.dataset.marketplaceDisabled='';label.append(note);}note.textContent=window.DPIAI18N.translate('Todavía no habilitado');}
   else note?.remove();
  }
 }
 document.querySelector('#querySourceError').textContent='';document.querySelector('#querySourcesModal').hidden=false;
 document.querySelector('#confirmQuerySources').focus();
}
function closeSourceModal(){document.querySelector('#querySourcesModal').hidden=true;pendingSourcesGeneration=false;}
let lastQueryOperationId=null;
function safeQueryUrl(value){
 try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)&&!url.username?url.href:null;}catch(_){return null;}
}
function renderQueryResult(data){
 const container=document.querySelector('#queryResults');container.replaceChildren();
 const states={complete:'Completado',partial:'Completado con advertencias',empty:'Completado sin productos',pending:'Pendiente de confirmación',failed:'Fallido',clarification_required:'Requiere aclaración'};
 for(const [source,outcome] of Object.entries(data.sources||{})){
  const section=document.createElement('section');section.className='source-result';section.dataset.source=source;
  const title=document.createElement('h3');title.textContent=source;section.append(title);
  const state=document.createElement('p');state.className='query-state';state.textContent=states[outcome.status]||'Pendiente de confirmación';section.append(state);
  if(outcome.error){const error=document.createElement('p');error.textContent=outcome.error;section.append(error);}
  if(data.remote_job&&source==='amazon'&&window.DPIAHistory)section.append(window.DPIAHistory.remoteImageButton(data.remote_job));
  const external=externalQuerySources.includes(source);
  if(external){
   const grid=document.createElement('div');grid.className='scraped-products';
   for(const [productIndex,product] of (outcome.products||[]).entries()){
    const card=document.createElement('article');card.className='scraped-product';card.dataset.realProduct='';
    const visual=document.createElement('div');visual.className='scraped-product-visual';
    const imageUrl=safeQueryUrl(product.image);
    if(imageUrl){const image=document.createElement('img');image.src=imageUrl;image.alt='';image.loading='lazy';image.onerror=()=>image.remove();visual.append(image);}
    const name=document.createElement('strong');name.textContent=product.title;
    const price=document.createElement('p');price.textContent=product.price==null?'Precio no informado':typeof product.price==='object'?JSON.stringify(product.price):String(product.price);
    const currency=document.createElement('small');currency.textContent=product.currency||'Moneda no informada';
    const marketplace=document.createElement('small');marketplace.textContent=product.marketplace||source;
    card.append(visual,name,price,currency,marketplace);
    const productUrl=safeQueryUrl(product.url);
    if(productUrl){const link=document.createElement('a');link.href=productUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Ver producto';card.append(link);}
    if(data.origin!=='scraper_api'&&source==='amazon'&&(data.request_id||lastQueryOperationId)&&window.DPIAHistory)card.append(window.DPIAHistory.imageButton(data.request_id||lastQueryOperationId,productIndex,product,outcome.image_stages?.[String(productIndex)]));
    grid.append(card);
   }
   section.append(grid);
   if(outcome.status==='pending'&&lastQueryOperationId){const refresh=document.createElement('button');refresh.className='action-button';refresh.type='button';refresh.textContent='Consultar estado';refresh.onclick=()=>loadQueryOperation(lastQueryOperationId);section.append(refresh);}
  }else{
   for(const row of outcome.data||[]){const article=document.createElement('article');article.className='prompt-result';const name=document.createElement('strong');name.dataset.catalogName='';name.textContent=row.titulo??row.producto??row.Producto??'';const description=document.createElement('p');description.textContent=row.descripcion||'';article.append(name,description);section.append(article);}
   if(!outcome.data?.length){const empty=document.createElement('p');empty.textContent='Sin resultados para este origen.';section.append(empty);}
  }
  container.append(section);
 }
 if(data.flow==='explorar'&&!data.result?.needs_clarification){
  const employment=isEmploymentQuery(data.context_ids);
  const heading=document.createElement('h3');heading.textContent='Sugerencias de IA';container.append(heading);
  const note=document.createElement('p');note.className='hint';note.textContent=employment?(window.DPIAI18N?.translate('Orientaciones laborales de IA, no vacantes verificadas. No se consultaron portales de empleo.')||''):'Precios estimados, sin verificar disponibilidad. Los enlaces permiten comparar opciones; no son fuentes consultadas.';container.append(note);
  const grid=document.createElement('div');grid.className='scraped-products';
  for(const item of data.result?.items||[]){
   const card=document.createElement('article');card.className='scraped-product';card.dataset.aiSuggestion='';
   const title=document.createElement('strong');title.textContent=item.producto;
   const description=document.createElement('p');description.textContent=item.descripcion;
   const price=document.createElement('p');price.textContent=typeof item.precio_venta_sugerido==='number'?`Precio sugerido: ${item.precio_venta_sugerido} ${data.result.constraints.price.currency}`:'Precio sugerido: N/D';
   const source=document.createElement('small');source.textContent='Sin fuente verificada';card.append(title,description);if(!employment)card.append(price);card.append(source);
   const context=data.result.context,metadata=document.createElement('dl');metadata.className='ai-suggestion-context';
   for(const [label,value] of [['Ámbito',context.ambito],['Categoría',context.categoria],['Ciudad',context.ciudad],['Código postal',context.codigoPostal],['País',context.pais],['Usuario',context.usuario],['Fecha',context.fecha],['Idioma',context.idioma]]){
    const term=document.createElement('dt'),detail=document.createElement('dd');term.textContent=label;detail.textContent=String(value??'');metadata.append(term,detail);
   }
   card.append(metadata);
   const searches={amazon:'https://www.amazon.com/s?k=',ebay:'https://www.ebay.com/sch/i.html?_nkw=',aliexpress:'https://www.aliexpress.com/w/wholesale-'};
   for(const [site,base] of Object.entries(employment?{}:searches)){
    const terms=item.busquedas?.[site]||item.producto;
    const link=document.createElement('a');link.href=base+encodeURIComponent(terms);link.target='_blank';link.rel='noopener noreferrer';link.textContent='Comparar en '+site;card.append(link);
   }
   if(!employment&&window.DPIAExplorePreview){window.DPIAExplorePreview.addImage(card,item.imagen,item.producto);card.append(window.DPIAExplorePreview.button(item,context,data.context_ids,{constraints:data.result.constraints,query:data.result.query}));}
   grid.append(card);
  }
  container.append(grid);
 }
 if(data.flow!=='explorar'&&data.rows?.length){
  const candidates=document.createElement('details'),heading=document.createElement('summary');
  candidates.className='query-candidates';heading.textContent='Candidatos de OpenAI · sin verificar';candidates.append(heading);
  for(const row of data.rows){const card=document.createElement('article');card.className='prompt-result';const title=document.createElement('strong');title.textContent=row.Producto;const detail=document.createElement('p');detail.textContent=row.descripcion;card.append(title,detail);candidates.append(card);}
  container.append(candidates);
 }
 const download=document.createElement('button');download.className='action-button';download.type='button';download.textContent='Descargar JSON';
 download.onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='dpia-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};container.append(download);
}
async function loadQueryOperation(id){
 const status=document.querySelector('#queryStatus');show('consultPage');
 try{
  const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(id),{cache:'no-store'}),data=await response.json();
  if(!response.ok||!data.success)throw new Error(data.error||'No se pudo consultar el estado.');
  lastQueryOperationId=id;renderQueryResult(data.payload);window.DPIACredits?.refresh();
  status.textContent=data.state==='pending'?'La ejecución sigue pendiente. No se reenviará.':data.state==='failed'?'La ejecución falló.':'Estado recuperado del servidor.';
 }catch(error){status.textContent=error.message;}
}
let queryArtTimer=null;
function setQueryArtState(state){
 const art=document.querySelector('.consult-art');if(!art)return;
 clearTimeout(queryArtTimer);art.dataset.activity=state;
 if(state!=='running')queryArtTimer=setTimeout(()=>{delete art.dataset.activity;},5000);
}
function setScrapingStatus(state,text){
 setQueryArtState(state==='running'||state==='preparing'?'running':state==='complete'?'success':state==='failed'?'error':'warning');
 const badge=document.querySelector('#scrapingActivity');
 badge.hidden=false;badge.dataset.state=state;
 if(state==='running'||state==='preparing')badge.dataset.operationId=queryRequestId||'';
 if(state==='pending'&&queryRequestId)badge.dataset.operationId=queryRequestId;
 badge.querySelector('span:last-child').textContent=text;
}
function updateScrapingStatus(data){
 document.querySelector('#scrapingActivity').dataset.operationId=data.request_id||lastQueryOperationId||'';
 const outcomes=Object.values(data.sources||{});
 if(outcomes.some(row=>row.generation?.status==='running'))setScrapingStatus('preparing','Preparando novedades con IA…');
 else if(outcomes.some(row=>row.status==='pending'))setScrapingStatus('pending','Scraping pendiente de confirmación · Consultar');
 else if(outcomes.some(row=>['partial','clarification_required'].includes(row.status)))setScrapingStatus('warning','Revisá los resultados de la consulta · Consultar');
 else if(outcomes.some(row=>row.status==='failed'))setScrapingStatus('failed','La búsqueda informó un error · Consultar');
 else {
  const count=outcomes.reduce((sum,row)=>sum+(row.products?.length||0),0);
  setScrapingStatus('complete',count?`${count} resultados disponibles · Consultar`:'Búsqueda completada sin resultados · Consultar');
 }
}
document.querySelector('#scrapingActivity').onclick=async()=>{const badge=document.querySelector('#scrapingActivity'),id=badge.dataset.operationId;badge.hidden=true;show('consultPage');if(id)await loadQueryOperation(id);document.querySelector('#queryResults').scrollIntoView({behavior:'smooth',block:'start'});};
async function generateDPIAQuery(sourceConfirmed=false){
 if(queryBusy||!queryPrepared||queryPrepared.sent||queryPrepared.pending)return;
 if(!currentEmail){openAuth();return;}
 if(JSON.stringify(queryBody())!==queryPrepared.fingerprint){invalidateQuery();document.querySelector('#queryStatus').textContent='El pedido cambió. Prepará nuevamente la consulta.';return;}
 const exploring=queryPrepared.body.mode==='explorar';
 if(sourceConfirmed!==true){openSourceModal(true);return;}
 const sources=exploring?['dpia']:savedQuerySources();if(!sources){openSourceModal(true);return;}
 if(queryPrepared.body.mode==='novedades'&&sources.filter(source=>externalQuerySources.includes(source)).length!==1){document.querySelector('#queryStatus').textContent='Elegí un marketplace para buscar novedades.';openSourceModal(true);return;}
 queryBusy=true;syncQueryConversation();const button=document.querySelector('#generateQuery'),status=document.querySelector('#queryStatus');button.disabled=true;
 const novel=queryPrepared.body.mode==='novedades',email=currentEmail;
 const direct=queryPrepared.body.mode==='buscar'&&!queryPrepared.body.attachments.length&&sources.length===1&&externalQuerySources.includes(sources[0]);
 queryRequestId ||= crypto.randomUUID();
 if(direct)setScrapingStatus('running','Scrapeando…');
 if(novel)setScrapingStatus('preparing','Preparando novedades con IA…');
 if(exploring){setScrapingStatus('preparing','Generando sugerencias con IA…');document.querySelector('#scrapingActivity').dataset.operationId='';}
 status.textContent=exploring?'Generando sugerencias con IA…':novel?'Preparando una búsqueda de novedades con OpenAI…':'Buscando en los orígenes seleccionados…';
 let polling=false;
 const operationId=queryRequestId;
 const progress=novel?setInterval(async()=>{
  if(polling||!queryBusy||currentEmail!==email)return;polling=true;
  try{const response=await fetch('/api/consultas/operaciones/'+encodeURIComponent(operationId),{cache:'no-store'});if(!response.ok)return;const data=await response.json();
   if(!queryBusy||currentEmail!==email)return;
   if(data.state==='dispatching')setScrapingStatus('running','Scrapeando novedades…');
   else if(data.state==='pending')setScrapingStatus('pending','Scraping pendiente de confirmación · Consultar');
  }catch(_){}finally{polling=false;}
 },3000):null;
 try{
  const response=await fetch(direct?'/api/consultas/scraping-directo':'/api/consultas/generar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...queryPrepared.body,sources,...(direct&&sources[0]==='amazon'?{image_pipeline:'base44'}:{}),request_id:queryRequestId}),signal:AbortSignal.timeout(650000)});
  const data=await response.json();if(novel&&currentEmail!==email)return;if(response.status===401)openAuth();
  if(response.status===402&&data.code==='insufficient_credit'){if(direct||novel)setScrapingStatus('failed','No se inició: ejecuciones insuficientes · Consultar');window.DPIACredits?.insufficient(data);return;}
  if(!response.ok||!data.success){const confirmedRejection=response.status<500||data.code==='persistence_not_configured'||data.not_started===true;if((direct||novel)&&confirmedRejection)setScrapingStatus('failed','No se inició la búsqueda · Consultar');const error=new Error(data.error||'No se pudo generar la consulta.');error.confirmedRejection=confirmedRejection;throw error;}
  if(queryPrepared)queryPrepared.sent=true;
  if(!exploring)lastQueryOperationId=data.request_id||queryRequestId;window.DPIACredits?.refresh();
  if(!direct&&!novel&&(!queryPrepared||JSON.stringify(queryBody())!==queryPrepared.fingerprint)){status.textContent='El pedido cambió. Prepará nuevamente la consulta.';return;}
  if(data.result?.needs_clarification){status.textContent='La IA necesita una aclaración: '+data.result.clarifying_question+' Agregá la respuesta al pedido y prepará nuevamente la consulta.';if(novel||exploring)setScrapingStatus('warning','La consulta necesita una aclaración · Consultar');renderQueryResult(data);return;}
  renderQueryResult(data);if(direct||novel)updateScrapingStatus(data);
  if(exploring)setScrapingStatus('complete',`${data.result.items.length} sugerencias disponibles · Consultar`);
  const outcomes=Object.values(data.sources||{});
  status.textContent=outcomes.some(row=>row.status==='pending')?'La ejecución sigue pendiente. No se reenviará.':outcomes.some(row=>row.status==='failed')?'La ejecución falló.':'Consulta completada. Revisá los resultados de cada origen.';
 }catch(error){if(queryPrepared&&!error.confirmedRejection)queryPrepared.pending=true;if(exploring)setScrapingStatus('failed','No se pudieron generar sugerencias · Consultar');if((direct||novel)&&!error.confirmedRejection)setScrapingStatus('pending','Scraping pendiente de confirmación · Consultar');status.textContent=error.name==='TimeoutError'?'La consulta sigue pendiente. No se reenviará automáticamente.':error.message;if(!exploring&&queryRequestId){lastQueryOperationId=queryRequestId;const refresh=document.createElement('button');refresh.className='action-button';refresh.textContent='Consultar estado';refresh.onclick=()=>loadQueryOperation(lastQueryOperationId);document.querySelector('#queryResults').append(refresh);}}
 finally{if(progress)clearInterval(progress);queryBusy=false;button.disabled=false;syncQueryConversation();window.DPIACredits?.refresh();if(queryPreparationQueued){queryPreparationQueued=false;queueQueryPreparation();}}
}
document.querySelector('#queryScope').addEventListener('change',()=>{refreshQuerySelectors();syncLocalCategory();});
for(const id of ['queryCategory','queryPostal','promptText','searchText'])document.querySelector('#'+id).addEventListener('input',invalidateQuery);
document.querySelector('#generateQuery').onclick=()=>generateDPIAQuery();
document.querySelector('#changeQuerySources').onclick=()=>openSourceModal(false);
document.querySelector('#closeQuerySources').onclick=closeSourceModal;
document.querySelector('#querySourcesModal').onclick=e=>{if(e.target.id==='querySourcesModal')closeSourceModal();};
document.querySelector('#allQuerySources').onchange=e=>{for(const box of document.querySelectorAll('[name="querySource"]'))if(['local','dpia','historial'].includes(box.value))box.checked=e.target.checked;};
document.querySelector('#confirmQuerySources').onclick=()=>{
 if(queryMode==='explorar'){
  const generate=pendingSourcesGeneration;closeSourceModal();if(generate)generateDPIAQuery(true);return;
 }
 const previous=savedQuerySources();
 const sources=[...document.querySelectorAll('[name="querySource"]:checked:not(:disabled)')].map(box=>box.value);
 if(pendingSourcesGeneration&&queryMode==='novedades'&&sources.filter(source=>externalQuerySources.includes(source)).length!==1){document.querySelector('#querySourceError').textContent='Elegí un marketplace para buscar novedades.';return;}
 if(!sources.length){document.querySelector('#querySourceError').textContent='Seleccioná al menos un origen de búsqueda.';return;}
 try{localStorage.setItem(sourcePreferenceKey(),JSON.stringify(sources));}catch(_){document.querySelector('#querySourceError').textContent='No se pudieron guardar los orígenes.';return;}
 const generate=pendingSourcesGeneration;if(JSON.stringify(previous)!==JSON.stringify(sources))queryRequestId=null;closeSourceModal();if(generate)generateDPIAQuery(true);
};
function syncLocalCategory(){const option=document.querySelector('#queryCategory').selectedOptions[0];localCategory=option?.value?{id:option.value,name:option.textContent}:null;}
document.querySelector('#queryCategory').addEventListener('change',()=>{syncLocalCategory();invalidateQuery();if(queryMode==='novedades')updateNovelDraft();else if(queryMode==='explorar')updateExploreDraft();});

document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!document.querySelector('#querySourcesModal').hidden)closeSourceModal();});
for(const box of document.querySelectorAll('[name="querySource"]'))box.addEventListener('change',()=>{if(box.checked&&externalQuerySources.includes(box.value)){for(const other of document.querySelectorAll('[name="querySource"]'))if(other!==box&&externalQuerySources.includes(other.value))other.checked=false;}document.querySelector('#allQuerySources').checked=[...document.querySelectorAll('[name="querySource"]')].filter(item=>['local','dpia','historial'].includes(item.value)).every(item=>item.checked);});

new MutationObserver(()=>{if(currentEmail)queueQueryPreparation();}).observe(document.querySelector('#userBtn'),{childList:true,subtree:true,characterData:true});

for(const id of ['querySalaryMin','querySalaryMax','querySalaryPeriod','querySalaryCurrency'])document.getElementById(id).addEventListener(id.endsWith('Min')||id.endsWith('Max')?'input':'change',syncExploreBudget);
