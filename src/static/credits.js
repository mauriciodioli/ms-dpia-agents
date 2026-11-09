/* Server-authoritative six-execution allowance. No fake purchases or local balances. */
(()=>{
 const $=id=>document.getElementById(id),tr=text=>window.DPIAI18N?.translate(text)||text;
 let testEnabled=false,selfEnabled=false,selfBusy=false,selfPending=null,selfGeneration=0;
 let credits=null,account=null,generation=0,chosen=300,returnToQuery=false;
 const states={reserved:'Reservada',dispatching:'En curso o pendiente',pending:'Pendiente de confirmación',consumed:'Consumida',released:'Liberada'};
 function render(){
  const logged=typeof currentEmail==='string'&&!!currentEmail;
  const available=credits?.available??'—',reserved=credits?.reserved??'—',consumed=credits?.consumed??'—',initial=credits?.initial??'—';
  $('walletNum').textContent=available;$('balanceNum').textContent=available;$('scrapingBalanceUnit').textContent=tr('pts');
  $('balanceLabel').textContent=tr('Puntos disponibles');$('freeCaption').textContent=tr('Puntos cargados');$('freeRemaining').textContent=initial;
  $('freeRenew').textContent=tr('Por usuario autenticado');$('paidCaption').textContent=tr('Reservados o pendientes');$('paidRemaining').textContent=reserved;
  $('paidDetail').textContent=tr('Retenidos hasta confirmar el resultado');$('consumedExecutions').textContent=consumed;$('availableExecutions').textContent=available;
  $('usageTitle').textContent=tr('Puntos consumidos');const percent=credits?Math.round(100*credits.consumed/credits.initial):0;
  $('usagePct').textContent=credits?percent+'%':'—';$('usageUsed').textContent=consumed+' '+tr('puntos consumidos');$('usageTotal').textContent=initial+' '+tr('puntos cargados');
  $('creditMeterFill').style.width=percent+'%';$('creditMeterFill').style.background=percent<50?'#30d49a':percent<80?'#ffaf35':'#ff5668';$('creditMeter').setAttribute('aria-valuenow',String(percent));
  $('creditDemoHint').textContent=tr(logged?'Un solo saldo: 1 punto por scraping iniciado y 5 puntos por destacar durante 5 días.':'Iniciá sesión para consultar tus puntos.');
  $('creditOperations').replaceChildren();
  for(const operation of credits?.operations||[]){
   if(operation.source==='recarga'){const row=document.createElement('li');row.textContent=tr('Recarga sin pago')+' · +'+operation.amount+' '+tr('pts');row.dataset.catalogName='';$('creditOperations').append(row);continue;}
   const row=document.createElement('li'),name=document.createElement('span'),button=document.createElement('button');button.className='action-button';
   name.textContent=(operation.source==='promocion'?tr('Publicación destacada'):operation.source)+' · '+tr(states[operation.state]||'Pendiente de confirmación')+' · '+(operation.cost||(operation.source==='promocion'?5:1))+' '+tr('pts');button.type='button';button.textContent=tr(operation.source==='promocion'?'Ver publicación':'Ver resultado');
   button.onclick=()=>operation.source==='promocion'?window.DPIAPublications?.openProfile():loadQueryOperation(operation.operation_id);row.append(name,button);$('creditOperations').append(row);
  }
  $('addTestCredits').hidden=!logged||!testEnabled||selfEnabled;
  $('creditHistorySummary').textContent=tr('Historial de puntos');
  choose(chosen);
 }
 async function refresh(){
  const current=typeof currentEmail==='string'?currentEmail:null,serial=++generation;
  if(account!==current){credits=null;testEnabled=false;selfEnabled=false;selfBusy=false;selfGeneration++;account=current;selfPending=readPending();$('selfCreditStatus').textContent='';}
  if(!current){credits=null;render();return;}
  try{
   const response=await fetch('/api/consultas/creditos',{cache:'no-store'}),data=await response.json();
   if(serial!==generation||currentEmail!==current)return;
   if(!response.ok||!data.success||!data.credits)throw new Error(data.error||'No se pudieron consultar los puntos.');
   credits=data.credits;testEnabled=!!data.test_credits_enabled;selfEnabled=data.self_topup_enabled===true;$('creditStatus').textContent='';
  }catch(error){if(serial!==generation)return;credits=null;testEnabled=false;selfEnabled=false;$('creditStatus').textContent=tr(error.message);}
  render();
 }
 function choose(points){
  chosen=points;document.querySelectorAll('[data-upgrade]').forEach(button=>button.classList.toggle('active',Number(button.dataset.upgrade)===points));
  $('upgradeContinue').textContent=tr('Pagos no habilitados');$('upgradeContinue').disabled=true;
  $('selfCreditPanel').hidden=!currentEmail||!selfEnabled;
  $('selfCreditAmount').textContent='6';
  $('grantSelfCredits').disabled=selfBusy;
  const grantLabel=selfBusy?'Agregando puntos…':selfPending?'Reintentar recarga':'Agregar 6 puntos sin pago';
  $('grantSelfCredits').dataset.i18n=grantLabel;$('grantSelfCredits').textContent=tr(grantLabel);
  document.querySelectorAll('[data-upgrade]').forEach(button=>button.disabled=selfBusy);
  document.querySelectorAll('.upgrade-plan b').forEach(price=>price.hidden=selfEnabled);
  $('upgradeContinue').hidden=selfEnabled;
  $('upgradeSubtitle').textContent=tr(selfEnabled?'Podés agregar 6 puntos por recarga sin realizar un pago.':'Paquetes de demostración. No acreditan ejecuciones.');
  $('upgradeNote').textContent=tr(selfEnabled?'La recarga suma puntos al saldo compartido. No se realizará ningún pago.':'Precios de referencia. Sin cobros ni acreditaciones.');
 }
 function open(insufficient=false,data=null){
  if(!currentEmail){openAuth();return;}
  returnToQuery=insufficient;$('upgradeTitle').textContent=tr(insufficient?'Crédito insuficiente':'Agregar crédito');
  $('upgradeSubtitle').textContent=tr('Paquetes de demostración. No acreditan ejecuciones.');
  $('insufficientCreditSummary').hidden=!insufficient;$('cancelCreditUpgrade').hidden=!insufficient;
  if(insufficient){$('insufficientAvailable').textContent=data?.credits?.available??0;$('insufficientRequired').textContent=data?.required??1;$('insufficientMissing').textContent=data?.missing??1;}
  $('upgradeNote').textContent=tr('Precios de referencia. Sin cobros ni acreditaciones.');$('upgradeOverlay').hidden=false;render();refresh();
 }
 function close(){
  $('upgradeOverlay').hidden=true;
  if(returnToQuery){show('consultPage');returnToQuery=false;}
 }
 function pendingKey(){return 'dpia-self-credit:'+account;}
 function readPending(){try{const value=JSON.parse(sessionStorage.getItem(pendingKey())||'null');return value&&value.amount===6&&typeof value.request_id==='string'&&/^[0-9a-f-]{36}$/i.test(value.request_id)?value:null;}catch(_){return null;}}
 function storePending(){try{if(selfPending)sessionStorage.setItem(pendingKey(),JSON.stringify(selfPending));else sessionStorage.removeItem(pendingKey());}catch(_){}}
 $('grantSelfCredits').onclick=async()=>{
  if(selfBusy||!selfEnabled||!currentEmail)return;
  const owner=currentEmail,serial=++selfGeneration;
  if(!selfPending)selfPending={amount:6,request_id:crypto.randomUUID()};
  storePending();selfBusy=true;$('selfCreditStatus').textContent='';choose(chosen);
  let status=0;
  try{
   const response=await fetch('/api/consultas/creditos/recargar',{method:'POST',headers:{'Content-Type':'application/json','X-DPIA-Action':'self-credit'},body:JSON.stringify(selfPending),signal:AbortSignal.timeout(20000)});
   status=response.status;const data=await response.json();
   if(owner!==currentEmail||serial!==selfGeneration)return;
   if(!response.ok||data.success!==true)throw Error(data.error||'No se confirmó la recarga. Reintentá la misma recarga.');
   selfPending=null;storePending();credits=data.credits;render();
   $('selfCreditStatus').textContent=tr('Puntos agregados correctamente.');
   await refresh();
  }catch(error){
   if(owner===currentEmail&&serial===selfGeneration){
    if(status>=400&&status<500){selfPending=null;storePending();}
    $('selfCreditStatus').textContent=tr(error.name==='Error'?error.message:'No se confirmó la recarga. Reintentá la misma recarga.');
   }
  }finally{if(owner===currentEmail&&serial===selfGeneration){selfBusy=false;choose(chosen);}}
 };
 $('addTestCredits').onclick=async()=>{
  const button=$('addTestCredits');if(button.disabled)return;button.disabled=true;
  try{
   const response=await fetch('/api/consultas/creditos/prueba',{method:'POST',headers:{'Content-Type':'application/json','X-DPIA-Test-Credits':'1'},body:'{}'}),data=await response.json();
   if(!response.ok||!data.success)throw new Error(data.error||'No se pudieron agregar puntos.');
   await refresh();
  }catch(error){$('creditStatus').textContent=error.message;}
  finally{button.disabled=false;}
 };
 $('openUpgrade').onclick=()=>open();$('closeUpgrade').onclick=close;$('cancelCreditUpgrade').onclick=close;
 $('upgradeOverlay').onclick=event=>{if(event.target===$('upgradeOverlay'))close();};
 document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('upgradeOverlay').hidden)close();});
 document.querySelectorAll('[data-upgrade]').forEach(button=>button.onclick=()=>choose(Number(button.dataset.upgrade)));
 document.querySelectorAll('.plans [data-points]').forEach(button=>button.onclick=()=>{choose(Number(button.dataset.points));open();});
 $('languageSelect').addEventListener('change',()=>queueMicrotask(render));
 new MutationObserver(()=>refresh()).observe($('userBtn'),{childList:true,subtree:true,characterData:true});
 window.DPIACredits={refresh,insufficient:data=>{refresh();open(true,data);}};
 render();refresh();
})();
