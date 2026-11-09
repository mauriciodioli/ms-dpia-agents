/* Presentation only: existing search, media and discovery handlers remain authoritative. */
(()=>{
 const journey=document.getElementById('situationJourney');
 const choices=document.getElementById('situationChoices');
 const stage=document.getElementById('situationSearchStage');
 const title=document.getElementById('situationSelectedTitle');
 const search=stage.querySelector('.search');
 const quick=stage.querySelector('.quick');
 const skip=document.getElementById('skipSituation');
 const restoreActions=document.getElementById('restoreSituationActions');
 function step(number){journey.querySelectorAll('[data-journey-step]').forEach(item=>{
  const current=Number(item.dataset.journeyStep)===number;
  if(current)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');
  item.classList.toggle('is-complete',Number(item.dataset.journeyStep)<number);
 });}
 journey.querySelectorAll('[data-situation]').forEach(button=>button.addEventListener('click',()=>{
  journey.querySelectorAll('[data-situation]').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));
  setQueryJourney(button.dataset.situation);
  const key=button.querySelector('strong').getAttribute('data-i18n');
  title.setAttribute('data-i18n',key);title.textContent=window.DPIAI18N?.translate(key)||key;
  const importing=button.dataset.situation==='import',employment=button.dataset.situation==='jobs';
  document.getElementById('exploreBtn').hidden=employment;
  stage.querySelector('.quick').classList.toggle('employment-quick',employment);
  const label=document.getElementById('localQuickLabel');
  label.setAttribute('data-i18n',importing?'País':'Local');
  label.textContent=window.DPIAI18N?.translate(importing?'País':'Local')||(importing?'País':'Local');
  document.getElementById('localBtn').onclick=importing?()=>openPublicationRegion('pais'):openMap;
  document.getElementById('exteriorBtn').hidden=!importing;
  stage.querySelector('.quick').classList.toggle('import-quick',importing);
  journey.classList.remove('search-only');search.hidden=true;quick.hidden=false;
  choices.hidden=true;stage.hidden=false;step(2);
  document.getElementById(employment?'novelBtn':'exploreBtn').focus();
 }));
 skip.addEventListener('click',()=>{
  setQueryJourney(null);
  choices.hidden=true;stage.hidden=false;search.hidden=false;quick.hidden=true;
  journey.classList.add('search-only');restoreActions.hidden=false;
  document.getElementById('searchText').focus();
 });
 document.getElementById('exteriorBtn').onclick=()=>openPublicationRegion('exterior');
 function restoreSituation(){
  setQueryJourney(null);
  restoreActions.hidden=true;
  document.getElementById('searchMediaMenu').hidden=true;
  document.getElementById('cameraBtn').setAttribute('aria-expanded','false');
  journey.classList.remove('search-only');search.hidden=true;quick.hidden=true;
  choices.hidden=false;stage.hidden=true;step(1);
  (journey.querySelector('[aria-pressed="true"]')||journey.querySelector('[data-situation]')).focus();
 }
 document.getElementById('changeSituation').addEventListener('click',restoreSituation);
 document.getElementById('restoreSituation').addEventListener('click',restoreSituation);
 // Navigation may be asynchronous (catalog preparation or authentication).
 const home=document.getElementById('home');
 new MutationObserver(()=>{
  if(!stage.hidden)step(home.hidden?3:2);
 }).observe(home,{attributes:true,attributeFilter:['hidden']});
})();
