const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];const coords={'Córdoba':[-31.4167,-64.1833],'Buenos Aires':[-34.6037,-58.3816],'Rosario':[-32.9468,-60.6393],'Mendoza':[-32.8895,-68.8458],'Montevideo':[-34.9011,-56.1645],'Punta del Este':[-34.967,-54.95],'Salto':[-31.388,-57.961],'Madrid':[40.4168,-3.7038],'Barcelona':[41.3874,2.1686],'Valencia':[39.4699,-.3763],'Spoleto':[42.74,12.738],'Roma':[41.9028,12.4964],'Milano':[45.4642,9.19],'Wrocław':[51.1079,17.0385],'Varsovia':[52.2297,21.0122],'Poznań':[52.4064,16.9252],'Guadalajara':[20.6597,-103.3496],'Ciudad de México':[19.4326,-99.1332],'Monterrey':[25.6866,-100.3161],'Puebla':[19.0414,-98.2063],'Querétaro':[20.5888,-100.3899],'Mérida':[20.9674,-89.5926],'Cancún':[21.1619,-86.8515],'Tijuana':[32.5149,-117.0382],'León':[21.122,-101.6837],'Toluca':[19.2826,-99.6557],'San Luis Potosí':[22.1565,-100.9855],'Aguascalientes':[21.8853,-102.2916],'Morelia':[19.7008,-101.1844],'Oaxaca':[17.0732,-96.7266],'Veracruz':[19.1738,-96.1342],'Chihuahua':[28.6329,-106.0691],'Hermosillo':[29.0729,-110.9559],'Zapopan':[20.7236,-103.3848]};let step=0,country='',city='',selected=new Set(),page='home',balance=250,media=[],recorder,recordParts=[],recordStream;const notify=t=>{$('#toast').textContent=t;$('#toast').classList.add('show');setTimeout(()=>$('#toast').classList.remove('show'),3200)};const asset=f=>'/static/images/'+f;function show(id){['onboard','home','mapPage','consultPage','creditsPage','accountPage','agentPage'].forEach(x=>$('#'+x).hidden=x!==id);$('#nav').hidden=id==='onboard';page=id;if(id==='home')loadHomePublications();if(id==='consultPage')window.DPIAHistory?.showQuery();$$('nav button').forEach(b=>b.classList.toggle('selected',b.dataset.page===(id==='creditsPage'?'accountPage':id)));window.scrollTo(0,0);if(id==='creditsPage')window.DPIACredits?.refresh();if(id==='accountPage')window.DPIAAccount?.open();if(id==='agentPage')window.DPIAAgent?.open()}function next(){if(step===0){if(!country)return;step=1;$('#onTitle').textContent='Elegí tu ciudad';$('#onSub').textContent=country;$('#countryList').hidden=true;$('#cityStage').hidden=false;loadCities(country)}else if(step===1){city=$('#citySelect').value;loadCatalogs();step=2;$('#onTitle').textContent='¿Qué te gusta?';$('#onSub').textContent='Elegí al menos 3';$('#cityStage').hidden=true;$('#interestsStage').hidden=false;renderInterests();$('#nextBtn').textContent='Empezar a descubrir →'}else{if(catalogState.ambitos==='ready'&&selected.size<Math.min(3,catalogAmbitos.length)){notify('Elegí al menos 3 intereses');return}finish()}}function finish(persist=true){if(persist)localStorage.setItem('dpia-demo',JSON.stringify({country,city,selected:[...selected],catalogVersion:1,language:catalogLanguage(),interestSelections:{...interestSelections,[catalogLanguage()]:[...selected]}}));$('#cityLabel').textContent=city;$('#mapCity').textContent=city;renderCategories();show('home')}$$('[data-country]').forEach(b=>b.onclick=()=>{country=b.dataset.country;$$('[data-country]').forEach(x=>x.classList.toggle('active',x===b));$('#nextBtn').disabled=false});$('#nextBtn').onclick=next;const mapLocationCache=new Map();
let mapLocationRequest=0,mapLocationController;
const normalizeMapName=value=>String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim();
async function openMap(){
 publicationRegion='local';
 $('#localMap').hidden=false;
 const heading=$('#mapPage .page-head h2');heading.setAttribute('data-i18n','Locales cerca tuyo');heading.textContent=window.DPIAI18N?.translate('Locales cerca tuyo')||'Locales cerca tuyo';
 const request=++mapLocationRequest,selectedCity=city,selectedCountry=country;
 mapLocationController?.abort();
 const frame=$('#mapFrame');frame.hidden=true;frame.removeAttribute('src');
 $('#mapDescription').textContent=`${selectedCity}, ${selectedCountry}`;
 show('mapPage');loadLocalPublications();
 const key=normalizeMapName(selectedCountry)+'|'+normalizeMapName(selectedCity);
 let point=mapLocationCache.get(key);
 try{
  if(!point){
   mapLocationController=new AbortController();
   const countries={argentina:'ar',uruguay:'uy',españa:'es',espana:'es',italia:'it',polonia:'pl',poland:'pl',polska:'pl',mexico:'mx'};
   const params=new URLSearchParams({format:'jsonv2',city:selectedCity,country:selectedCountry,limit:'1'});
   const code=countries[normalizeMapName(selectedCountry)];if(code)params.set('countrycodes',code);
   const response=await fetch('https://nominatim.openstreetmap.org/search?'+params,{signal:mapLocationController.signal});
   if(!response.ok)throw new Error('Map location unavailable');
   const results=await response.json(),match=results[0];
   if(!match)throw new Error('City not found');
   point=[Number(match.lat),Number(match.lon)];
   if(!point.every(Number.isFinite)||Math.abs(point[0])>90||Math.abs(point[1])>180)throw new Error('Invalid location');
   mapLocationCache.set(key,point);
  }
  if(request!==mapLocationRequest||city!==selectedCity||country!==selectedCountry)return;
  const [lat,lon]=point,d=.045,bbox=[lon-d,lat-d,lon+d,lat+d].join('%2C');
  frame.src=`https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${lat}%2C${lon}`;frame.hidden=false;
  const notes={es:'OpenStreetMap. Ubicación aproximada de la ciudad.',en:'OpenStreetMap. Approximate city location.',pl:'OpenStreetMap. Przybliżona lokalizacja miasta.',it:'OpenStreetMap. Posizione approssimativa della città.'};
  $('#localMapNote').textContent=notes[catalogLanguage()]||notes.es;
 }catch(error){
  if(error.name==='AbortError'||request!==mapLocationRequest)return;
  // Never substitute an unrelated city when geolocation cannot be resolved.
  frame.hidden=true;
  const messages={es:'No se pudo ubicar esta ciudad en el mapa.',en:'This city could not be located on the map.',pl:'Nie udało się znaleźć tego miasta na mapie.',it:'Impossibile individuare questa città sulla mappa.'};
  $('#localMapNote').textContent=messages[catalogLanguage()]||messages.es;
 }
}
$('#showMap').onclick=openMap;$('#openMap').onclick=openMap;$('#localBtn').onclick=openMap;$('#placeBtn').onclick=()=>{localStorage.removeItem('dpia-demo');step=0;country='';city='';loadCatalogs();$('#countryList').hidden=false;$('#cityStage').hidden=true;$('#interestsStage').hidden=true;$('#onTitle').textContent='¿Dónde estás?';$('#onSub').textContent='Elegí tu país';$('#nextBtn').textContent='Seguir →';$('#nextBtn').disabled=true;show('onboard')};$('#changeInterests').onclick=()=>{step=2;$('#onTitle').textContent='¿Qué te gusta?';$('#onSub').textContent='Elegí al menos 3';$('#countryList').hidden=true;$('#cityStage').hidden=true;$('#interestsStage').hidden=false;$('#nextBtn').textContent='Guardar intereses →';renderInterests();show('onboard')};function credits(){show('creditsPage')}$('#balanceBtn').onclick=credits;$('#homeLogo').onclick=()=>show('home');$$('nav button').forEach(b=>b.onclick=()=>b.dataset.page==='mapPage'?openMap():show(b.dataset.page));$$('[data-back]').forEach(b=>b.onclick=()=>show(b.closest('#creditsPage')?'accountPage':'home'));$('#exploreBtn').onclick=openExploreQuery;$('#novelBtn').onclick=openNovelQuery;$$('[data-points]').forEach(b=>b.onclick=()=>{$('#paymentNote').textContent=`Plan ${b.dataset.points} puntos seleccionado. Pago no disponible en esta demostración.`});function addMedia(file){addQueryMedia(file)}$('#consultPhoto').onclick=()=>$('#photoFile').click();$('#photoFile').onchange=e=>addMedia(e.target.files[0]);$('#consultVideo').onclick=()=>$('#videoFile').click();$('#videoFile').onchange=e=>addMedia(e.target.files[0]);async function audio(){if(recorder&&recorder.state==='recording'){recorder.stop();$('#audioBtn').textContent='🎙';setConsultAudioRecording(false);return}if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){notify('Grabación no disponible: requiere HTTPS o localhost');return}try{recordStream=await navigator.mediaDevices.getUserMedia({audio:true});recordParts=[];recorder=new MediaRecorder(recordStream);recorder.ondataavailable=e=>{if(e.data.size)recordParts.push(e.data)};recorder.onstop=()=>{const blob=new Blob(recordParts,{type:recorder.mimeType});addMedia(new File([blob],`audio-${Date.now()}.webm`,{type:blob.type}));recordStream.getTracks().forEach(t=>t.stop())};recorder.start();$('#audioBtn').textContent='⏹';setConsultAudioRecording(true);notify('Grabando audio. Volvé a tocar para detener.')}catch(e){notify('No se pudo acceder al micrófono')}}$('#audioBtn').onclick=audio;$('#consultAudio').onclick=audio;function prepare(){submitConsultQuery()}$('#sendBtn').onclick=startHomeQuery;$('#preparePrompt').onclick=prepare;$('#searchText').onkeydown=e=>{if(e.key==='Enter')startHomeQuery()};// Tema guardado y sesión validada por el servidor.
let currentEmail=null,googleClientId='';
function setTheme(t){document.documentElement.dataset.theme=t;localStorage.setItem('dpia-theme',t);$('#themeToggle').textContent=t==='dark'?'☀':'☾';}
setTheme(localStorage.getItem('dpia-theme')||'dark');
$('#themeToggle').onclick=()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark');
function updateUser(email){currentEmail=email||null;$('#userBtn').textContent=currentEmail||'Ingresar';$('#userBtn').title=currentEmail?'Mi perfil':'Iniciar sesión';}
function openAuth(){$('#authOverlay').hidden=false;syncCookieConsent();}
function closeAuth(){$('#authOverlay').hidden=true;}
$('#closeAuth').onclick=closeAuth;
$('#authOverlay').onclick=e=>{if(e.target===$('#authOverlay'))closeAuth()};
$('#userBtn').onclick=()=>{if(currentEmail)window.DPIAPublications?.openProfile();else openAuth()};
function syncCookieConsent(){
 $('#googleSignIn').hidden=!$('#authCookieConsent').checked;
}
try{$('#authCookieConsent').checked=localStorage.getItem('dpia-session-cookies')==='accepted-v1';}catch(_){}
syncCookieConsent();
$('#authCookieConsent').onchange=()=>{
 try{if($('#authCookieConsent').checked)localStorage.setItem('dpia-session-cookies','accepted-v1');else localStorage.removeItem('dpia-session-cookies');}catch(_){}
 syncCookieConsent();
};
let googleLoginPending=false;
async function completeGoogleLogin({credential}){
 if(!$('#authCookieConsent').checked){openAuth();$('#authHelp').textContent='Aceptá las cookies de sesión para continuar.';$('#authCookieConsent').focus();return;}
 if(googleLoginPending)return;
 googleLoginPending=true;
 const help=$('#authHelp');
 help.setAttribute('role','status');
 help.textContent='Verificando tu cuenta y guardando el usuario…';
 try{
  const res=await fetch('/api/auth/google',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({credential}),signal:AbortSignal.timeout(30000)});
  const data=await res.json().catch(()=>null);
  if(!res.ok){help.textContent=data?.error||'No se pudo completar el acceso en DPIA. Reintentá.';return;}
  if(!data?.authenticated||!data.email){help.textContent='DPIA no confirmó el inicio de sesión. Reintentá.';return;}
  const sessionResponse=await fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
  const me=await sessionResponse.json();
  if(!sessionResponse.ok||!me.authenticated||me.email!==data.email){help.textContent='La sesión no se pudo conservar. Revisá que el navegador permita las cookies del sitio y reintentá.';return;}
  updateUser(me.email);closeAuth();notify('Sesión iniciada');
 }catch(_){help.textContent='No se pudo completar la conexión con DPIA. Reintentá.';}
 finally{googleLoginPending=false;}
}
function renderGoogleSignIn(){
 if(!googleClientId||!window.google?.accounts?.id)return;
 $('#googleSignIn').replaceChildren();
 google.accounts.id.renderButton($('#googleSignIn'),{theme:document.documentElement.dataset.theme==='dark'?'filled_black':'outline',size:'large',width:290,text:'signin_with',locale:window.DPIAI18N?.language||'es'});
}
async function initAuth(){
 try{
  const [me,cfg]=await Promise.all([fetch('/api/auth/me').then(r=>r.json()),fetch('/api/auth/config').then(r=>r.json())]);
  updateUser(me.email);googleClientId=cfg.client_id||'';
  if(!googleClientId){$('#authHelp').textContent='Configurá GOOGLE_CLIENT_ID para habilitar el acceso real con Google.';return;}
  const render=()=>{if(!window.google?.accounts?.id){setTimeout(render,200);return;}
   google.accounts.id.initialize({client_id:googleClientId,callback:completeGoogleLogin});
   renderGoogleSignIn();
   $('#authHelp').textContent='Google verifica tu identidad. DPIA muestra el email de tu cuenta.';
  };render();
 }catch(e){$('#authHelp').textContent='No se pudo consultar la configuración de autenticación.';}
}
initAuth();
let saved=null;try{saved=JSON.parse(localStorage.getItem('dpia-demo')||'null')}catch(_){};if(saved?.city){country=saved.country;city=saved.city;Object.assign(interestSelections,saved.interestSelections||{});if(saved.catalogVersion&&!saved.interestSelections)interestSelections[saved.language||'es']=saved.selected||[];selected=new Set(interestSelections[catalogLanguage()]||[]);finish(false)}else show('onboard');
// Keep language choice persistent and translate dynamically rendered UI.
window.DPIAI18N?.refresh();

$('#languageSelect').addEventListener('change',()=>queueMicrotask(()=>{renderGoogleSignIn();loadCatalogs();if(step===1)loadCities(country)}));
loadCatalogs();
