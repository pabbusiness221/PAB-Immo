// ============================================================================
// PAB Immo — code partagé par la vitrine et l'espace de gestion
// ============================================================================
// Ce fichier existe parce que les deux pages dupliquaient le même code, et que
// les copies avaient fini par diverger : la vitrine connaissait quatre types de
// biens, l'espace de gestion seulement trois. Ajouter un champ agricole faisait
// planter l'ouverture de sa fiche côté gestion, et le même correctif devait
// être appliqué deux fois.
//
// Ne mettre ici que ce qui est VRAIMENT commun. Tout ce qui diverge — rendu des
// listes, fiches, filtres, cartes — reste dans sa page : les fusionner de force
// recréerait le problème sous une autre forme.
//
// Chargé AVANT le script de chaque page. Les fonctions ci-dessous peuvent
// appeler des éléments définis par la page (db, PROPERTIES, render,
// updateScrollLock…) : elles ne s'exécutent qu'après son chargement.
// ============================================================================

// ---- Connexion Supabase ----------------------------------------------------
// Clé « publishable », prévue pour être publique : toute la protection repose
// sur la sécurité au niveau des lignes, jamais sur le secret de cette clé.
const SUPABASE_URL = 'https://avanktgaxepzpqmsiauz.supabase.co';
const SUPABASE_KEY = 'sb_publishable_nAQnS82ru9h-beIDPKMqPA_JO_aSYc-';

// ---- Repères métier --------------------------------------------------------
// L'ordre suit celui de l'énumération en base : Terrain, Maison, Appartement,
// Studio, Champ agricole.
const TYPE_COLOR = { Terrain:'#B24A2C', Maison:'#2E4A61', Appartement:'#1F7A73', Studio:'#6E5480', 'Champ agricole':'#6B8E23' };

const fcfa = n => n.toLocaleString('fr-FR') + ' FCFA';
const surfaceUnit = type => type === 'Champ agricole' ? 'ha' : 'm²';

function esc(s){
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ---- Icônes par type de bien ----------------------------------------------
// Les tracés sont stockés sans dimension : c'est typeIcon qui pose la taille
// demandée. Auparavant chaque page gardait ses icônes à une taille figée et les
// appelants faisaient un remplacement de chaîne sur `width="20"` — un appelant
// qui se trompait de taille obtenait silencieusement une icône non
// redimensionnée, et un type absent de la table faisait planter le `.replace`.
const ICON_PATHS = {
  Terrain:          '<rect x="3" y="3" width="18" height="18" rx="1"/><line x1="12" y1="3" x2="12" y2="21"/><line x1="3" y1="12" x2="21" y2="12"/>',
  Maison:           '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/>',
  Appartement:      '<rect x="4" y="3" width="16" height="18"/><line x1="9" y1="8" x2="9" y2="8"/><line x1="15" y1="8" x2="15" y2="8"/><line x1="9" y1="13" x2="9" y2="13"/><line x1="15" y1="13" x2="15" y2="13"/>',
  // Une pièce unique meublée : le trait distingue le coin nuit du reste, ce qui
  // évite de confondre l'icône avec celle de l'appartement à petite taille.
  Studio:           '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M3 14h18"/><path d="M7 14v-3h4v3"/>',
  'Champ agricole': '<path d="M12 21V11"/><path d="M12 11Q6 11 6 5Q12 5 12 11Z"/><path d="M12 11Q18 11 18 5Q12 5 12 11Z"/>'
};

// Un type inconnu — ajouté en base sans passer par ici — reçoit un cercle
// plutôt que de faire planter la page.
function typeIcon(type, taille){
  const px = taille || 18;
  const d = ICON_PATHS[type] || '<circle cx="12" cy="12" r="9"/>';
  return `<svg width="${px}" height="${px}" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2">${d}</svg>`;
}

// Marqueur de carte Leaflet, identique des deux côtés.
function markerIcon(p, selected){
  return L.divIcon({
    className: '',
    html:`<div class="custom-marker ${selected?'pulse':''}" style="width:${selected?38:32}px;height:${selected?38:32}px;background:${TYPE_COLOR[p.type]}">${typeIcon(p.type)}</div>`,
    iconSize: selected ? [38,38] : [32,32],
    iconAnchor: selected ? [19,19] : [16,16]
  });
}

// ---- Photos ----------------------------------------------------------------
// Les fichiers sont stockés tels que téléversés : jusqu'à 2 Mo et 2480x3509 px.
// Les servir en taille réelle dans une vignette coûtait ~9,5 Mo au chargement
// d'une liste. Supabase redimensionne à la volée ; on lui demande la taille
// réellement affichée.
//
// Ce redimensionnement dépend de l'offre souscrite. S'il devient indisponible,
// on repasse sur les fichiers d'origine plutôt que d'afficher des images
// cassées : une sonde au démarrage bascule tout le site, et chaque <img>
// retombe seule sur l'original en cas d'échec isolé.
let PHOTO_RESIZE_OK = true;
let photoResizeChecked = false;

function photoUrl(path, width, quality){
  const url = db.storage.from('property-photos').getPublicUrl(path).data.publicUrl;
  if(!width || !PHOTO_RESIZE_OK) return url;
  return url.replace('/storage/v1/object/public/', '/storage/v1/render/image/public/')
    + `?width=${width}&quality=${quality || 65}`;
}

function publicPhotoUrl(path){
  return photoUrl(path);
}

function coverUrl(p, width, quality){
  if(!p.photos || !p.photos.length) return null;
  const cover = p.photos.find(ph=>ph.is_cover) || p.photos[0];
  return photoUrl(cover.storage_path, width, quality);
}

function originalPhotoUrl(u){
  return String(u).split('?')[0]
    .replace('/storage/v1/render/image/public/', '/storage/v1/object/public/');
}

// Filet par image : un fichier isolé peut échouer (format exotique, envoi
// corrompu) sans que le service soit en cause.
function photoFallback(img){
  img.onerror = null;
  const orig = originalPhotoUrl(img.src);
  if(orig !== img.src) img.src = orig;
}

// Sonde unique, sur une miniature minuscule : si le service ne répond pas, on
// bascule et on redessine avec les originaux.
async function checkPhotoResize(){
  if(photoResizeChecked || !PHOTO_RESIZE_OK) return;
  photoResizeChecked = true;
  const withPhoto = PROPERTIES.find(p => p.photos && p.photos.length);
  if(!withPhoto) return;
  try{
    const r = await fetch(photoUrl(withPhoto.photos[0].storage_path, 32, 40), { cache:'no-store' });
    if(r.ok) return;
  }catch(e){ /* service injoignable */ }
  PHOTO_RESIZE_OK = false;
  render();
}

function getPropertyPhotos(p){
  const photos = Array.isArray(p.photos) ? [...p.photos] : [];
  return photos
    .map(ph => ({ ...ph, url: photoUrl(ph.storage_path, 1600, 75), thumb: photoUrl(ph.storage_path, 200, 60) }))
    .sort((a,b) => (a.position ?? 0) - (b.position ?? 0));
}

// ---- Galerie plein écran ---------------------------------------------------
// updateScrollLock est défini par chaque page : la vitrine doit aussi tenir
// compte de son tiroir de fiche, l'espace de gestion de ses trois panneaux.
function openPhotoGallery(p, startIndex = 0){
  const photos = getPropertyPhotos(p);
  if(!photos.length) return;
  const modal = document.getElementById('galleryModal');
  let currentIndex = Math.max(0, Math.min(startIndex, photos.length - 1));

  function renderGallery(){
    const current = photos[currentIndex];
    modal.innerHTML = `
      <div class="gallery-shell">
        <div class="gallery-main">
          <button type="button" class="gallery-nav prev" data-action="prev" ${currentIndex===0?'disabled':''}>‹</button>
          <img src="${current.url}" alt="Photo ${currentIndex + 1}" />
          <button type="button" class="gallery-nav next" data-action="next" ${currentIndex===photos.length - 1?'disabled':''}>›</button>
          <button type="button" class="gallery-close" data-action="close">×</button>
          <div class="gallery-counter">${currentIndex + 1}/${photos.length}</div>
        </div>
        <div class="gallery-thumbs">
          ${photos.map((ph, idx) => `<button type="button" class="${idx===currentIndex?'active':''}" data-index="${idx}"><img src="${ph.thumb}" alt="Miniature ${idx + 1}" loading="lazy" decoding="async" onerror="photoFallback(this)" /></button>`).join('')}
        </div>
      </div>`;

    modal.querySelector('[data-action="prev"]').onclick = () => { currentIndex = Math.max(0, currentIndex - 1); renderGallery(); };
    modal.querySelector('[data-action="next"]').onclick = () => { currentIndex = Math.min(photos.length - 1, currentIndex + 1); renderGallery(); };
    modal.querySelector('[data-action="close"]').onclick = closePhotoGallery;
    modal.querySelectorAll('[data-index]').forEach(btn => {
      btn.onclick = () => { currentIndex = Number(btn.dataset.index); renderGallery(); };
    });
  }

  renderGallery();
  modal.classList.remove('hidden');
  updateScrollLock();
  modal.onclick = (e) => { if(e.target === modal) closePhotoGallery(); };
}

function closePhotoGallery(){
  const modal = document.getElementById('galleryModal');
  modal.classList.add('hidden');
  modal.innerHTML = '';
  updateScrollLock();
}

// ---- Pagination de liste ---------------------------------------------------
// state.page et PER_PAGE appartiennent à chaque page : la vitrine pagine par
// 20 (deux annonces par ligne), le portefeuille par 10 (une par ligne).
function pagerHtml(total, totalPages, start, shown, libelle){
  if(totalPages <= 1) return '';
  return `
    <nav class="list-pager" aria-label="${esc(libelle || 'Pagination')}">
      <button type="button" class="pager-btn" data-page-step="-1" ${state.page===1?'disabled':''}>‹ Précédent</button>
      <span class="pager-status">Page ${state.page} sur ${totalPages}<small>${start+1}–${start+shown} sur ${total} biens</small></span>
      <button type="button" class="pager-btn" data-page-step="1" ${state.page===totalPages?'disabled':''}>Suivant ›</button>
    </nav>`;
}
