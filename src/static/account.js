/* Account navigation reuses existing authentication, profile and credit controls. */
(()=>{
 const byId=id=>document.getElementById(id);
 function render(){
  const logged=typeof currentEmail==='string'&&!!currentEmail;
  byId('accountGuest').hidden=logged;byId('accountAuthenticated').hidden=!logged;
  byId('accountEmail').textContent=logged?currentEmail:'';
  byId('accountPoints').textContent=logged?byId('balanceNum').textContent:'—';
  byId('accountStatus').textContent=logged?byId('creditStatus').textContent:'';
 }
 byId('accountLogin').onclick=()=>openAuth();
 byId('accountProfile').onclick=()=>window.DPIAPublications?.openProfile('profile');
 byId('accountPublications').onclick=()=>window.DPIAPublications?.openProfile();
 byId('accountRecharge').onclick=()=>byId('openUpgrade').click();
 byId('accountHistory').onclick=()=>{show('creditsPage');byId('creditHistoryAccordion').open=true;byId('creditHistoryAccordion').scrollIntoView({block:'center'});};
 byId('accountLogout').onclick=async()=>{
  const button=byId('accountLogout');if(button.disabled)return;button.disabled=true;
  try{await byId('profileLogout').onclick();render();if(currentEmail)byId('accountStatus').textContent=byId('profileStatus').textContent;}
  finally{button.disabled=false;}
 };
 for(const id of ['userBtn','balanceNum','creditStatus'])new MutationObserver(render).observe(byId(id),{childList:true,subtree:true,characterData:true});
 byId('languageSelect').addEventListener('change',()=>queueMicrotask(render));
 window.DPIAAccount={open:()=>{render();window.DPIACredits?.refresh();}};
 render();
})();
