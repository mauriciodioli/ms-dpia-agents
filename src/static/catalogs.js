// Catalog names come from DPIA. Images remain the existing local artwork.
let catalogAmbitos = [], catalogCategorias = [], catalogPostalCodes = [];
let catalogState = {ambitos: 'loading', categorias: 'loading'};
let catalogGeneration = 0;
const interestSelections = {};
const catalogMessages = {
 es: ['Cargando catálogo…', 'No hay datos disponibles.', 'No se pudo cargar el catálogo.', 'Reintentar', 'Podés continuar y elegir intereses más tarde.'],
 en: ['Loading catalog…', 'No data available.', 'Could not load the catalog.', 'Retry', 'You can continue and choose interests later.'],
 pl: ['Ładowanie katalogu…', 'Brak danych.', 'Nie udało się wczytać katalogu.', 'Spróbuj ponownie', 'Możesz kontynuować i wybrać zainteresowania później.'],
 it: ['Caricamento catalogo…', 'Nessun dato disponibile.', 'Impossibile caricare il catalogo.', 'Riprova', 'Puoi continuare e scegliere gli interessi più tardi.']
};
const catalogLanguage = () => window.DPIAI18N?.language || 'es';
function catalogStatus(container, name) {
 const state = catalogState[name], messages = catalogMessages[catalogLanguage()] || catalogMessages.es;
 if (state === 'ready') return false;
 const text = document.createElement('p'); text.className = 'hint'; text.setAttribute('role', 'status');
 text.textContent = messages[state === 'loading' ? 0 : state === 'empty' ? 1 : 2];
 if (name === 'ambitos' && state !== 'loading') text.textContent += ' ' + messages[4];
 container.append(text);
 if (state === 'error' || state === 'empty') {
  const retry = document.createElement('button'); retry.type = 'button'; retry.textContent = messages[3];
  retry.onclick = () => loadCatalogs(); container.append(retry);
 }
 return true;
}
function renderInterests() {
 const grid = document.querySelector('#interestGrid'); grid.replaceChildren();
 if (step === 2) document.querySelector('#nextBtn').disabled = catalogState.ambitos === 'loading';
 if (catalogStatus(grid, 'ambitos')) return;
 for (const item of catalogAmbitos) {
  const id = String(item.ambito_id), button = document.createElement('button');
  button.className = 'interest' + (selected.has(id) ? ' active' : ''); button.dataset.interest = id;
  const image = DPIACatalogArtwork.create('ambitos', item, {language:catalogLanguage(), country, city});
  const label = document.createElement('span'); label.textContent = item.nombre; label.dataset.catalogName = '';
  const check = document.createElement('i'); check.className = 'interest-check'; check.textContent = selected.has(id) ? '✓' : '+';
  button.append(image, label, check);
  button.onclick = () => { selected.has(id) ? selected.delete(id) : selected.add(id); interestSelections[catalogLanguage()] = [...selected]; renderInterests(); };
  grid.append(button);
 }
}
function selectedNames() {
 return catalogAmbitos.filter(item => selected.has(String(item.ambito_id))).map(item => item.nombre);
}
let activeCatalogScope = null;
function renderCategories() {
 const grid = document.querySelector('#categoryGrid'); grid.replaceChildren();
 const scopes = catalogAmbitos.filter(item => selected.has(String(item.ambito_id)));
 if (!scopes.some(item => String(item.ambito_id) === activeCatalogScope)) activeCatalogScope = null;
 const title = document.querySelector('#catalogHeading');
 const activeScope = scopes.find(item => String(item.ambito_id) === activeCatalogScope);
 title.textContent = activeScope ? activeScope.nombre : 'Tus ámbitos de interés';
 title.toggleAttribute('data-catalog-name', !!activeScope);
 const back = document.querySelector('#backToScopes');
 back.hidden = !activeScope;
 back.onclick = () => { activeCatalogScope = null; renderCategories(); };
 document.querySelector('#changeInterests').hidden = !!activeScope;
 if (catalogStatus(grid, 'ambitos')) return;
 for (const item of activeScope ? [] : scopes) {
  const id = String(item.ambito_id), button = document.createElement('button');
  button.type = 'button'; button.className = 'category'; button.dataset.scope = id;
  button.setAttribute('aria-pressed', String(activeCatalogScope === id));
  const image = DPIACatalogArtwork.create('ambitos', item, {language:catalogLanguage(), country, city});
  const label = document.createElement('span'); label.textContent = item.nombre; label.dataset.catalogName = '';
  button.append(image, label);
  button.onclick = () => { activeCatalogScope = id; renderCategories(); };
  grid.append(button);
 }
 if (!scopes.length) {
  const hint = document.createElement('p'); hint.className = 'hint'; hint.setAttribute('role', 'status');
  hint.textContent = 'Elegí tus ámbitos en Personalizar.'; grid.append(hint); return;
 }
 if (!activeCatalogScope || catalogStatus(grid, 'categorias')) return;
 const items = catalogCategorias.filter(item => item.ambito_ids.some(id => String(id) === activeCatalogScope));
 if (!items.length) {
  const hint = document.createElement('p'); hint.className = 'hint'; hint.setAttribute('role', 'status');
  hint.textContent = 'No hay categorías disponibles para este ámbito.'; grid.append(hint);
 }
 for (const item of items) {
  const button = document.createElement('button'); button.type = 'button'; button.className = 'category'; button.dataset.cat = String(item.categoria_id);
  const image = DPIACatalogArtwork.create('categorias', item, {language:catalogLanguage(), country, city, scopeId:activeCatalogScope, ambitos:catalogAmbitos});
  const label = document.createElement('span'); label.textContent = item.nombre; label.dataset.catalogName = '';
  button.append(image, label);
  button.onclick = () => { chooseQueryCategory(item, Number(activeCatalogScope)); show('consultPage'); document.querySelector('#promptText').value = document.querySelector('#searchText').value.trim(); };
  grid.append(button);
 }
}
async function loadCatalogs() {
 const generation = ++catalogGeneration, language = catalogLanguage();
 activeCatalogScope = null;
 document.querySelector('#queryScope').value='';
 document.querySelector('#queryCategory').value='';
 localCategory = null;
 catalogAmbitos = []; catalogCategorias = []; catalogPostalCodes = [];
 if(typeof refreshQuerySelectors==='function')refreshQuerySelectors();
 catalogState = {ambitos:'loading', categorias:'loading'};
 renderInterests(); renderCategories();
 if(!country || !city){catalogState={ambitos:'empty',categorias:'empty'};renderInterests();renderCategories();return;}
 let locationPayload;
 try {
  const response=await fetch('/api/catalogos/ubicacion?'+new URLSearchParams({pais:country,ciudad:city,idioma:language}),{signal:AbortSignal.timeout(60000)});
  if(!response.ok)throw new Error('location catalog');
  locationPayload=await response.json();
  if(locationPayload.success!==true)throw new Error('location catalog');
 }catch(_){
  if(generation!==catalogGeneration)return;
  catalogState={ambitos:'error',categorias:'error'};renderInterests();renderCategories();return;
 }
 if(generation!==catalogGeneration)return;
 catalogPostalCodes=locationPayload.codigos_postales||[];
 await Promise.all(['ambitos','categorias'].map(async name => {
  try {
   const payload = locationPayload;
   if (payload.success !== true || !Array.isArray(payload[name])) throw new Error('catalog');
   if (generation !== catalogGeneration) return;
   catalogState[name] = payload[name].length ? 'ready' : 'empty';
   if (name === 'ambitos') {
    catalogAmbitos = payload.ambitos;
    const available = new Set(catalogAmbitos.map(item => String(item.ambito_id)));
    // Migrate old demo names once; keep IDs scoped to their catalog language.
    const legacy = new Set((saved?.catalogVersion ? [] : saved?.selected || []).map(n => n.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()));
    selected = new Set([...(interestSelections[language] || [])].filter(id => available.has(id)));
    if (!saved?.catalogVersion) for (const item of catalogAmbitos) {
     if (legacy.has(item.nombre.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase())) selected.add(String(item.ambito_id));
    }
    interestSelections[language] = [...selected];
   } else catalogCategorias = payload.categorias;
  } catch (_) {
   if (generation !== catalogGeneration) return;
   catalogState[name] = 'error';
  }
  renderInterests(); renderCategories();
 }));
 refreshQuerySelectors();if(page==='home')loadHomePublications();
}

let cityGeneration=0;
async function loadCities(chosenCountry){
 const generation=++cityGeneration, select=document.querySelector('#citySelect'), status=document.querySelector('#cityStatus'), retry=document.querySelector('#retryCities');
 select.replaceChildren();select.disabled=true;document.querySelector('#nextBtn').disabled=true;
 status.textContent={es:'Cargando ciudades…',en:'Loading cities…',pl:'Ładowanie miast…',it:'Caricamento città…'}[catalogLanguage()];retry.hidden=true;
 try{
  const response=await fetch('/api/catalogos/ciudades?'+new URLSearchParams({pais:chosenCountry}),{signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw new Error('cities');
  const payload=await response.json();
  if(payload.success!==true||!Array.isArray(payload.ciudades))throw new Error('cities');
  if(generation!==cityGeneration||country!==chosenCountry||step!==1)return;
  for(const item of payload.ciudades){const option=document.createElement('option');option.value=item.nombre;option.textContent=item.nombre;select.append(option);}
  select.disabled=!select.options.length;document.querySelector('#nextBtn').disabled=!select.options.length;
  status.textContent=select.options.length?'':({es:'No hay ciudades disponibles para este país.',en:'No cities available for this country.',pl:'Brak miast dla tego kraju.',it:'Nessuna città disponibile per questo Paese.'}[catalogLanguage()]);
  retry.hidden=!!select.options.length;
 }catch(_){
  if(generation!==cityGeneration||country!==chosenCountry||step!==1)return;
  status.textContent={es:'No se pudieron cargar las ciudades. Reintentá.',en:'Could not load cities. Try again.',pl:'Nie udało się wczytać miast. Spróbuj ponownie.',it:'Impossibile caricare le città. Riprova.'}[catalogLanguage()];retry.hidden=false;
 }
 retry.textContent=(catalogMessages[catalogLanguage()]||catalogMessages.es)[3];retry.onclick=()=>loadCities(country);
}
