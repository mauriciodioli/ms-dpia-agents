/* Only chooses the existing photo/video inputs; ingestion stays in app.js. */
(()=>{
 const camera=document.getElementById('cameraBtn'),menu=document.getElementById('searchMediaMenu');
 const choices=[document.getElementById('searchPhotoChoice'),document.getElementById('searchVideoChoice')];
 function close(restoreFocus=false){menu.hidden=true;camera.setAttribute('aria-expanded','false');if(restoreFocus)camera.focus();}
 function open(index=0){menu.hidden=false;camera.setAttribute('aria-expanded','true');choices[index].focus();}
 camera.onclick=()=>menu.hidden?open():close(true);
 camera.onkeydown=event=>{
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();open(event.key==='ArrowUp'?choices.length-1:0);}
 };
 choices.forEach((button,index)=>button.onclick=()=>{
  close(true);document.getElementById(index===0?'photoFile':'videoFile').click();
 });
 menu.onkeydown=event=>{
  if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);}
  else if(event.key==='Tab')close();
  else if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
   event.preventDefault();const current=choices.indexOf(document.activeElement);
   const next=event.key==='Home'?0:event.key==='End'?choices.length-1:(current+(event.key==='ArrowUp'?-1:1)+choices.length)%choices.length;
   choices[next].focus();
  }
 };
 document.addEventListener('pointerdown',event=>{if(!menu.hidden&&!menu.contains(event.target)&&!camera.contains(event.target))close();});
 document.addEventListener('focusin',event=>{if(!menu.hidden&&!menu.contains(event.target)&&event.target!==camera)close();});
})();
