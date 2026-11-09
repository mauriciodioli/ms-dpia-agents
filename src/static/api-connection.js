/* One automatic read-only check, then manual retries. Credentials stay in Flask. */
(()=>{
 const component=document.getElementById('apiConnection'),label=document.getElementById('apiConnectionState'),retry=document.getElementById('retryApiConnection');
 if(!component||!label||!retry)return;
 let inFlight=false;
 const errors={timeout:'api.timeout',unauthorized:'api.unauthorized',forbidden:'api.forbidden',not_configured:'api.notConfigured',invalid_response:'api.invalidResponse',service_error:'api.serviceError',unavailable:'api.disconnected'};
 function render(state,key){
  component.dataset.state=state;component.setAttribute('aria-busy',String(state==='checking'));
  label.setAttribute('data-i18n',key);label.setAttribute('data-i18n-title',key);
  retry.disabled=state==='checking';window.DPIAI18N?.refresh();
 }
 async function checkConnection(){
  if(inFlight)return;
  inFlight=true;render('checking','api.checking');
  try{
   const response=await fetch('/api/conexion',{method:'GET',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(10000)});
   let data;
   try{data=await response.json();}catch(_){render('disconnected','api.invalidResponse');return;}
   if(response.status===200&&data?.success===true)render('connected','api.connected');
   else render('disconnected',errors[data?.code]||(response.status===401?'api.unauthorized':response.status===403?'api.forbidden':'api.disconnected'));
  }catch(error){render('disconnected',error.name==='TimeoutError'||error.name==='AbortError'?'api.timeout':'api.disconnected');}
  finally{inFlight=false;retry.disabled=false;}
 }
 retry.addEventListener('click',checkConnection);
 checkConnection();
})();
