/* Compact composer controls reuse the existing file readers and send handlers. */
function setConsultAudioRecording(recording){
 const button=document.getElementById('consultAudio');button.dataset.recording=String(recording);
 const key=recording?'chat.stopAudio':'chat.recordAudio';
 button.setAttribute('data-i18n-aria-label',key);button.setAttribute('data-i18n-title',key);window.DPIAI18N?.refresh();
}
(()=>{
 const add=document.getElementById('consultAddButton'),menu=document.getElementById('consultAttachmentMenu');
 const choices=[...menu.querySelectorAll('[role="menuitem"]')];
 function close(focus=false){menu.hidden=true;add.setAttribute('aria-expanded','false');if(focus)add.focus();}
 function open(index=0){menu.hidden=false;add.setAttribute('aria-expanded','true');choices[index].focus();}
 add.onclick=()=>menu.hidden?open():close(true);
 add.onkeydown=event=>{if(['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();open(event.key==='ArrowUp'?choices.length-1:0);}};
 for(const button of choices)button.addEventListener('click',()=>close(true));
 menu.onkeydown=event=>{
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);}
  else if(event.key==='Tab')close();
  else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
   event.preventDefault();const index=choices.indexOf(document.activeElement);
   const next=event.key==='Home'?0:event.key==='End'?choices.length-1:(index+(event.key==='ArrowUp'?-1:1)+choices.length)%choices.length;
   choices[next].focus();
  }
 };
 document.addEventListener('pointerdown',event=>{if(!menu.hidden&&!menu.contains(event.target)&&!add.contains(event.target))close();});
 document.addEventListener('focusin',event=>{if(!menu.hidden&&!menu.contains(event.target)&&event.target!==add)close();});
})();
