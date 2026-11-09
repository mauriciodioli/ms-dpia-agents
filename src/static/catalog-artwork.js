// Presentation only: IDs, catalog text and selection handlers remain in catalogs.js.
(() => {
 const base = '/static/images/publication-covers/';
 function locationKey(country, city) {
  const normalize = value => String(value).normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase().trim().replace(/\s+/g,' ');
  return normalize(country) + '|' + normalize(city);
 }
 function mappedImage(kind, item, options) {
  const {language='es',country=null,city=null} = options;
  const manifest = window.DPIAPublicationCovers;
  const groups = country && city ? manifest?.locations[locationKey(country,city)]?.languages : manifest?.languages;
  const id = kind === 'ambitos' ? item.ambito_id : item.categoria_id;
  const entry = groups?.[language]?.[kind]?.[String(id)];
  const filename = entry?.cover?.image;
  return entry && /^[a-f0-9]{24}\.webp$/.test(filename) ? base + filename : null;
 }
 function candidates(kind, item, options = {}) {
  const {scopeId = null, ambitos = []} = options;
  const paths = [mappedImage(kind, item, options)];
  if (kind === 'categorias') {
   const related = (item.ambito_ids || []).map(String);
   const ids = scopeId == null ? related : related.filter(id => id === String(scopeId));
   for (const id of ids) {
    const scope = ambitos.find(row => String(row.ambito_id) === id);
    if (scope) paths.push(mappedImage('ambitos', scope, options));
   }
  }
  return [...new Set(paths.filter(Boolean))];
 }
 function initials(name) {
  return String(name || '').trim().split(/\s+/u).filter(Boolean).slice(0,2)
   .map(word => Array.from(word)[0]).join('').toLocaleUpperCase();
 }
 function create(kind, item, options = {}) {
  const visual = document.createElement('span'); visual.className = 'catalog-artwork';
  visual.setAttribute('aria-hidden','true'); visual.dataset.catalogName = '';
  const monogram = document.createElement('b'); monogram.className = 'catalog-monogram';
  monogram.textContent = initials(item.nombre); visual.append(monogram);
  const key = `${options.language || 'es'}:${kind}:${kind === 'ambitos' ? item.ambito_id : item.categoria_id}`;
  const hash = Array.from(key).reduce((value, char) => (value * 31 + char.charCodeAt(0)) >>> 0, 0);
  visual.style.setProperty('--art-hue', String(220 + hash % 100));
  const paths = candidates(kind, item, options);
  if (!paths.length) { visual.dataset.artwork = 'gradient'; return visual; }
  const image = document.createElement('img'); image.alt = ''; image.width = 480; image.height = 360;
  image.loading = 'lazy'; image.decoding = 'async'; image.style.opacity = '0';
  let index = 0;
  visual.dataset.artwork = 'loading';
  image.onload = () => { image.style.opacity = '1'; monogram.hidden = true; visual.dataset.artwork = 'image'; };
  image.onerror = () => {
   image.style.opacity = '0'; monogram.hidden = false;
   if (++index < paths.length) image.src = paths[index];
   else { image.remove(); visual.dataset.artwork = 'gradient'; }
  };
  visual.append(image); image.src = paths[index];
  return visual;
 }
 window.DPIACatalogArtwork = {candidates, create};
})();
