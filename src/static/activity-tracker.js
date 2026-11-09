/* Visible-time deltas, not cumulative totals. No query text, media or credentials. */
(()=>{
 if(window.DPIAActivityTracker)return;window.DPIAActivityTracker=true;
 let account;
 try{account=sessionStorage.getItem('dpia-activity-session');if(!account){account=crypto.randomUUID();sessionStorage.setItem('dpia-activity-session',account);}}catch(_){account=crypto.randomUUID();}
 let view=typeof page==='string'?page:'onboard',started=document.hidden?null:performance.now();
 function emit(event,deltaView=view){
  const now=performance.now(),elapsed=started===null?0:Math.max(0,Math.round(now-started));
  started=document.hidden?null:now;
  const postal=document.querySelector('#queryPostal')?.selectedOptions[0];
  const record=typeof catalogPostalCodes!=='undefined'?catalogPostalCodes.find(item=>String(item.id)===postal?.value):null;
  const payload={event,view:deltaView,duration_ms:Math.min(elapsed,86400000),session_id:account,
   language:window.DPIAI18N?.language||navigator.language,postal_code:record?.codigoPostal?String(record.codigoPostal):null};
  const blob=new Blob([JSON.stringify(payload)],{type:'application/json'});
  if(event==='page_exit'||document.hidden){if(navigator.sendBeacon?.('/api/activity',blob))return;}
  fetch('/api/activity',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),keepalive:true}).catch(()=>{});
 }
 emit('session_start');
 new MutationObserver(()=>{
  const next=typeof page==='string'?page:view;
  if(next===view)return;
  emit('visibility',view);view=next;emit('page_view');
 }).observe(document.querySelector('main'),{subtree:true,attributes:true,attributeFilter:['hidden']});
 setInterval(()=>{if(!document.hidden)emit('heartbeat');},60000);
 document.addEventListener('visibilitychange',()=>{if(document.hidden)emit('visibility');else started=performance.now();});
 window.addEventListener('pagehide',()=>emit('page_exit'));
 window.addEventListener('pageshow',event=>{if(event.persisted){started=document.hidden?null:performance.now();emit('page_view');}});
})();
