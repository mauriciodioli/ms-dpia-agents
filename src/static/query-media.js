// Decode locally; send bounded images or video keyframes, never browser file paths.
let queryMediaPending = Promise.resolve();
function mediaFrame(element) {
 const width=element.videoWidth||element.naturalWidth, height=element.videoHeight||element.naturalHeight;
 if(!width||!height)throw new Error('No se pudo leer el adjunto.');
 const scale=Math.min(1,1024/Math.max(width,height));
 const canvas=document.createElement('canvas');canvas.width=Math.round(width*scale);canvas.height=Math.round(height*scale);
 canvas.getContext('2d').drawImage(element,0,0,canvas.width,canvas.height);
 return canvas.toDataURL('image/jpeg',0.8);
}
function mediaEvent(element,event) {
 return new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>done(new Error('El adjunto tardó demasiado en cargar.')),12000);
  const success=()=>done(),error=()=>done(new Error('No se pudo leer el adjunto.'));
  function done(err){clearTimeout(timer);element.removeEventListener(event,success);element.removeEventListener('error',error);err?reject(err):resolve();}
  element.addEventListener(event,success,{once:true});element.addEventListener('error',error,{once:true});
 });
}
async function readQueryMedia(file) {
 if(media.length>=4||file.size>15*1024*1024)throw new Error('Adjuntá hasta 4 archivos de hasta 15 MB.');
 if(!file.type.startsWith('image/')&&!file.type.startsWith('video/'))throw new Error('Usá imágenes o videos; el audio todavía no se interpreta.');
 const url=URL.createObjectURL(file);
 try{
  const frames=[];
  if(file.type.startsWith('image/')){
   const img=new Image();const ready=mediaEvent(img,'load');img.src=url;await ready;frames.push(mediaFrame(img));
  }else{
   const video=document.createElement('video');video.muted=true;video.preload='auto';video.playsInline=true;
   const ready=mediaEvent(video,'loadeddata');video.src=url;await ready;
   if(!Number.isFinite(video.duration)||video.duration>60)throw new Error('Usá videos de hasta 60 segundos.');
   for(const fraction of [0.05,0.35,0.65,0.95]){
    const seeked=mediaEvent(video,'seeked');video.currentTime=Math.max(0.001,video.duration*fraction);await seeked;frames.push(mediaFrame(video));
   }
   video.removeAttribute('src');video.load();
  }
  const existing=media.reduce((n,item)=>n+item.frames.length,0);
  if(existing+frames.length>8)throw new Error('Los adjuntos superan el tamaño permitido.');
  return {type:file.type.startsWith('video/')?'video':'image',name:file.name.slice(0,180),frames};
 }finally{URL.revokeObjectURL(url);}
}
function renderQueryMedia(){
 const container=document.querySelector('#attachments');container.replaceChildren();
 media.forEach((item,index)=>{
  const row=document.createElement('div'),name=document.createElement('span'),remove=document.createElement('button');
  name.textContent='📎 '+item.name+(item.type==='video'?' · Fotogramas sin audio':'');
  remove.type='button';remove.textContent='×';remove.setAttribute('aria-label','Quitar adjunto');
  remove.onclick=()=>{media.splice(index,1);renderQueryMedia();invalidateQuery();};row.append(name,remove);container.append(row);
 });
}
function addQueryMedia(file){
 if(!file)return;show('consultPage');invalidateQuery();
 queryMediaPending=queryMediaPending.then(async()=>{
  document.querySelector('#queryStatus').textContent='Procesando adjunto…';
  try{media.push(await readQueryMedia(file));renderQueryMedia();document.querySelector('#queryStatus').textContent='';}
  catch(error){document.querySelector('#queryStatus').textContent=error.message;}
 });
}
