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

// Régions où l'agence opère. SOURCE UNIQUE, partagée par les deux pages : la
// vitrine y puise la liste du formulaire d'alerte, le portefeuille celle de la
// saisie d'un bien.
//
// Pourquoi ici et pas en double dans chaque page : l'alerte apparie la région
// par égalité EXACTE (region = « Thiès »). Si le portefeuille laissait saisir la
// région en texte libre, un bien enregistré « THIES » ou « Région de Thiès » ne
// correspondrait jamais à un inscrit ayant choisi « Thiès » — et il ne serait
// pas prévenu, sans la moindre erreur visible. Une seule liste garantit que la
// valeur écrite et la valeur cherchée parlent le même vocabulaire.
const REGIONS = ['Dakar', 'Thiès'];

// Construit les <option> d'une liste de régions. `selection` coche la valeur
// courante ; `avecToutes` ajoute « Toutes régions » en tête (côté recherche).
// Une valeur héritée hors liste (ancienne donnée) est ajoutée telle quelle
// plutôt que perdue silencieusement à l'ouverture d'un ancien bien.
function regionOptions(selection, avecToutes){
  const connues = REGIONS.slice();
  if(selection && !connues.includes(selection)) connues.push(selection);
  // Ce fichier sert aussi le portefeuille, qui est monolingue et ne définit
  // pas t(). D'où le test : la vitrine traduit « Toutes régions », l'espace de
  // gestion garde la chaîne telle quelle. Les noms de régions, eux, sont des
  // noms propres et ne se traduisent dans aucun des deux.
  const toutes = typeof t === 'function' ? t('Toutes régions') : 'Toutes régions';
  const tete = avecToutes ? `<option value="">${toutes}</option>` : '';
  return tete + connues.map(r =>
    `<option value="${esc(r)}"${r === selection ? ' selected' : ''}>${esc(r)}</option>`
  ).join('');
}

const fcfa = n => n.toLocaleString('fr-FR') + ' FCFA';
const surfaceUnit = type => type === 'Champ agricole' ? 'ha' : 'm²';

// ---- Équivalence en euros et dollars, pour les acheteurs de la diaspora ----
// Le FCFA (XOF) est arrimé à l'euro à un taux FIXE depuis 1999 (traité entre
// la zone UEMOA et la zone euro) : 655,957 F CFA pour 1 € n'est pas une
// estimation, c'est un taux légalement invariable, quel que soit le marché.
const TAUX_XOF_EUR = 655.957;
// Le dollar, lui, flotte réellement contre le FCFA. Cette valeur est
// indicative (ordre de grandeur au 2 août 2026, dérivé d'un EUR/USD proche de
// 1,09) et doit être corrigée à la main de temps en temps — un taux figé mais
// à jour reste plus honnête qu'un taux « en direct » qu'aucune API gratuite
// ne fournit de façon fiable ici. Modifier UNIQUEMENT cette ligne (et la même
// constante dans outils/generer-pages.py) pour la mettre à jour.
const TAUX_XOF_USD = 600;

// Rendu textuel, utilisé partout où l'équivalence doit s'afficher — jamais
// sur la liste des annonces (trop d'annonces, pas assez de place), mais sur
// le tiroir d'un bien et sur sa fiche générée, où un acheteur qui raisonne en
// euros ou en dollars en a vraiment besoin pour se projeter.
function prixSecondaire(prixFcfa){
  if(!Number.isFinite(prixFcfa)) return '';
  const eur = Math.round(prixFcfa / TAUX_XOF_EUR).toLocaleString('fr-FR');
  const usd = Math.round(prixFcfa / TAUX_XOF_USD).toLocaleString('fr-FR');
  return `≈ ${eur} € · ${usd} $US`;
}

function esc(s){
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ---- Recherche universelle -------------------------------------------------
// Partagée par la vitrine et le portefeuille : auparavant dupliquée, la
// recherche admin ne couvrait que commune/région/référence/quartier alors que
// celle de la vitrine couvrait tout (type, opération, prix, pièces, statut,
// description...). Une seule barre tapait donc deux comportements différents
// selon la page. La comparaison ignore accents et casse ; chaque mot tapé doit
// se retrouver quelque part dans la fiche.
function sansAccents(s){
  return String(s ?? '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
}
function texteRecherche(p){
  if(p._recherche) return p._recherche;
  // STATUS_LABEL (libellés côté vitrine, ex. « Sous offre ») n'existe que sur
  // la vitrine : absent côté admin, on retombe simplement sur le statut brut.
  const libelleStatut = (typeof STATUS_LABEL !== 'undefined' && STATUS_LABEL[p.status]) || '';
  const parts = [
    p.ref, p.type, p.operation,
    p.operation === 'Vente' ? 'à vendre vente achat acheter' : '',
    p.operation === 'Location' ? 'à louer location louer loyer' : '',
    p.commune, p.region, p.quartier, p.departement,
    p.status, libelleStatut,
    // camelCase côté vitrine, snake_case côté admin (voir les deux mapRow) —
    // et déjà retiré à "Non renseigné" par la vitrine, qui ne veut pas de ce
    // mot-clé dans les résultats d'une recherche sur autre chose.
    p.statutFoncier || p.statut_foncier || '',
    p.desc,
    (p.type === 'Champ agricole') ? 'hectare hectares champ agricole terre' : '',
    Number.isFinite(p.surface) ? p.surface + ' ' + surfaceUnit(p.type) : '',
    Number.isFinite(p.price) ? p.price + ' fcfa ' + p.price.toLocaleString('fr-FR') : ''
  ];
  if(p.rooms){
    if(p.rooms.chambres != null) parts.push(p.rooms.chambres + ' chambres chambre');
    if(p.rooms.salons != null) parts.push(p.rooms.salons + ' salon salons séjour');
    if(p.rooms.sdb != null) parts.push(p.rooms.sdb + ' salle de bain douche sdb');
    if(p.rooms.cuisine) parts.push('cuisine');
    if(Array.isArray(p.rooms.autres) && p.rooms.autres.length) parts.push(p.rooms.autres.join(' '));
  }
  p._recherche = sansAccents(parts.filter(Boolean).join(' '));
  return p._recherche;
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

// ---- Rails horizontaux glissables (catégories, biens en vedette…) ---------
// Le tactile fait déjà défiler ces rails nativement. Une souris, elle, ne le
// peut pas sans un clic-glisser explicite — cette fonction l'ajoute à
// n'importe quel conteneur qui défile en x, pour ne pas dupliquer la logique
// à chaque rail. dataset.glisserActif évite un double branchement si la
// fonction est rappelée sur un conteneur déjà équipé (un rail se réécrit
// souvent sans que son élément hôte, lui, ne change).
function activerGlisserPourDefiler(el){
  if(!el || el.dataset.glisserActif) return;
  el.dataset.glisserActif = '1';
  let bas = false, depart = 0, defilDepart = 0, deplace = false;
  el.addEventListener('pointerdown', (e) => {
    if(e.pointerType === 'touch') return; // le tactile défile déjà nativement
    bas = true; deplace = false;
    depart = e.clientX; defilDepart = el.scrollLeft;
    el.classList.add('grabbing');
  });
  el.addEventListener('pointermove', (e) => {
    if(!bas) return;
    const delta = e.clientX - depart;
    if(Math.abs(delta) > 4) deplace = true;
    el.scrollLeft = defilDepart - delta;
  });
  const relacher = () => { bas = false; el.classList.remove('grabbing'); };
  el.addEventListener('pointerup', relacher);
  el.addEventListener('pointerleave', relacher);
  // Un glissement qui a réellement déplacé le rail ne doit pas aussi
  // déclencher le clic de la tuile relâchée dessous, sinon on filtre ou on
  // ouvre une fiche au hasard à chaque glissement à la souris.
  el.addEventListener('click', (e) => { if(deplace){ e.stopPropagation(); e.preventDefault(); } }, true);
}

// ---- Galerie plein écran ---------------------------------------------------
// updateScrollLock est défini par chaque page : la vitrine doit aussi tenir
// compte de son tiroir de fiche, l'espace de gestion de ses trois panneaux.
//
// Élément qui avait le focus avant l'ouverture (la vignette cliquée) : on l'y
// ramène à la fermeture, comme pour le tiroir de fiche.
let elementAvantGalerie = null;

function openPhotoGallery(p, startIndex = 0){
  const photos = getPropertyPhotos(p);
  if(!photos.length) return;
  const modal = document.getElementById('galleryModal');
  let currentIndex = Math.max(0, Math.min(startIndex, photos.length - 1));
  elementAvantGalerie = document.activeElement;

  // foyer indique quel bouton doit reprendre le focus une fois le HTML
  // reconstruit : chaque clic (prev/next/vignette) détruit et recrée tout le
  // contenu, donc le focus se perdrait sinon à chaque image affichée.
  function renderGallery(foyer){
    const current = photos[currentIndex];
    modal.innerHTML = `
      <div class="gallery-shell" role="dialog" aria-modal="true" aria-label="Photo ${currentIndex + 1} sur ${photos.length}">
        <div class="gallery-main">
          <button type="button" class="gallery-nav prev" data-action="prev" ${currentIndex===0?'disabled':''} aria-label="Photo précédente">‹</button>
          <img src="${current.url}" alt="Photo ${currentIndex + 1}" />
          <button type="button" class="gallery-nav next" data-action="next" ${currentIndex===photos.length - 1?'disabled':''} aria-label="Photo suivante">›</button>
          <button type="button" class="gallery-close" data-action="close" aria-label="Fermer la galerie">×</button>
          <div class="gallery-counter">${currentIndex + 1}/${photos.length}</div>
        </div>
        <div class="gallery-thumbs">
          ${photos.map((ph, idx) => `<button type="button" class="${idx===currentIndex?'active':''}" data-index="${idx}" aria-label="Photo ${idx + 1} sur ${photos.length}" aria-current="${idx===currentIndex?'true':'false'}"><img src="${ph.thumb}" alt="" loading="lazy" decoding="async" onerror="photoFallback(this)" /></button>`).join('')}
        </div>
      </div>`;

    modal.querySelector('[data-action="prev"]').onclick = () => { currentIndex = Math.max(0, currentIndex - 1); renderGallery('prev'); };
    modal.querySelector('[data-action="next"]').onclick = () => { currentIndex = Math.min(photos.length - 1, currentIndex + 1); renderGallery('next'); };
    modal.querySelector('[data-action="close"]').onclick = closePhotoGallery;
    modal.querySelectorAll('[data-index]').forEach(btn => {
      btn.onclick = () => { currentIndex = Number(btn.dataset.index); renderGallery('index'); };
    });

    // Glisser pour naviguer — souris et tactile unifiés via les Pointer
    // Events, en plus des flèches (pas à leur place). setPointerCapture
    // garde le geste même si le doigt sort de l'image en cours de route.
    // Une légère résistance sur la première/dernière photo signale qu'on ne
    // peut pas aller plus loin, plutôt que de ne rien montrer du tout.
    const img = modal.querySelector('.gallery-main img');
    let depart = null, largeur = 0;
    img.onpointerdown = (e) => {
      depart = e.clientX;
      largeur = img.getBoundingClientRect().width || 1;
      img.style.transition = 'none';
      try{ img.setPointerCapture(e.pointerId); }catch(err){}
    };
    img.onpointermove = (e) => {
      if(depart === null) return;
      let delta = e.clientX - depart;
      const enButee = (currentIndex === 0 && delta > 0) || (currentIndex === photos.length - 1 && delta < 0);
      if(enButee) delta *= 0.35;
      img.style.transform = `translateX(${delta}px)`;
    };
    const relacherGlissement = (e) => {
      if(depart === null) return;
      const delta = (e.clientX ?? depart) - depart;
      depart = null;
      img.style.transition = 'transform .25s var(--ease)';
      const seuil = largeur * 0.15; // 15 % de la largeur : un vrai geste, pas un tremblement
      if(delta <= -seuil && currentIndex < photos.length - 1){ modal.querySelector('[data-action="next"]').click(); }
      else if(delta >= seuil && currentIndex > 0){ modal.querySelector('[data-action="prev"]').click(); }
      else { img.style.transform = 'translateX(0)'; }
    };
    img.onpointerup = relacherGlissement;
    img.onpointercancel = relacherGlissement;
    img.ondragstart = () => false;

    // Reporter le focus après reconstruction : sur le bouton demandé s'il
    // existe et n'est pas désactivé, sinon sur la fermeture (repli sûr).
    const cible = foyer==='prev' ? modal.querySelector('[data-action="prev"]:not([disabled])')
                : foyer==='next' ? modal.querySelector('[data-action="next"]:not([disabled])')
                : foyer==='index' ? modal.querySelector('[data-index].active')
                : null;
    (cible || modal.querySelector('[data-action="close"]')).focus();
  }

  // Le retrait de « hidden » doit précéder renderGallery() : tant que la
  // modale est display:none, le bouton de fermeture n'est pas réellement
  // focalisable et le .focus() à l'intérieur échoue silencieusement.
  modal.classList.remove('hidden');
  renderGallery(null);
  updateScrollLock();
  modal.onclick = (e) => { if(e.target === modal) closePhotoGallery(); };
}

function closePhotoGallery(){
  const modal = document.getElementById('galleryModal');
  modal.classList.add('hidden');
  modal.innerHTML = '';
  updateScrollLock();
  // Rendre le focus à la vignette qui a ouvert la galerie plutôt que de le
  // laisser retomber en haut de page.
  if(elementAvantGalerie){ elementAvantGalerie.focus(); elementAvantGalerie = null; }
}

// Échap ferme la galerie, les flèches gauche/droite changent de photo, et Tab
// reste piégé à l'intérieur tant qu'elle est ouverte — même raisonnement que
// pour le tiroir de fiche (aria-modal="true" doit être une promesse tenue).
document.addEventListener('keydown', e => {
  const modal = document.getElementById('galleryModal');
  if(!modal || modal.classList.contains('hidden')) return;
  if(e.key === 'Escape'){
    // stopImmediatePropagation et non stopPropagation : le gestionnaire d'Échap
    // du tiroir de fiche est posé sur le MÊME nœud (document), si bien qu'il
    // n'y a aucune propagation à interrompre — seulement une liste d'écouteurs
    // à arrêter. Sans cela, les deux s'exécutaient sur la même touche : la
    // galerie se fermait, puis la fiche aussi, et l'on se retrouvait dans la
    // liste des résultats après avoir simplement regardé une photo. Un
    // utilisateur de souris ne voyait rien de tout cela, le bouton × étant
    // correct ; c'était une perte de repère propre au clavier.
    e.stopImmediatePropagation();
    closePhotoGallery();
    return;
  }
  if(e.key === 'ArrowLeft'){ modal.querySelector('[data-action="prev"]:not([disabled])')?.click(); return; }
  if(e.key === 'ArrowRight'){ modal.querySelector('[data-action="next"]:not([disabled])')?.click(); return; }
  if(e.key !== 'Tab') return;
  const focusables = [...modal.querySelectorAll('button:not([disabled])')].filter(el => el.offsetParent !== null);
  if(!focusables.length) return;
  const premier = focusables[0], dernier = focusables[focusables.length - 1];
  if(e.shiftKey && document.activeElement === premier){ e.preventDefault(); dernier.focus(); }
  else if(!e.shiftKey && document.activeElement === dernier){ e.preventDefault(); premier.focus(); }
});

// ---- Pagination de liste ---------------------------------------------------
// state.page et PER_PAGE appartiennent à chaque page : la vitrine pagine par
// 20 (deux annonces par ligne), le portefeuille par 10 (une par ligne).
function pagerHtml(total, totalPages, start, shown, libelle, lang){
  if(totalPages <= 1) return '';
  // lang est optionnel et ne change rien pour l'espace de gestion (qui ne le
  // passe jamais) : seule la vitrine, qui connaît la langue courante, le
  // fournit pour basculer ce libellé en anglais.
  if(lang === 'en'){
    return `
    <nav class="list-pager" aria-label="${esc(libelle || 'Pagination')}">
      <button type="button" class="pager-btn" data-page-step="-1" ${state.page===1?'disabled':''}>‹ Previous</button>
      <span class="pager-status">Page ${state.page} of ${totalPages}<small>${start+1}–${start+shown} of ${total} properties</small></span>
      <button type="button" class="pager-btn" data-page-step="1" ${state.page===totalPages?'disabled':''}>Next ›</button>
    </nav>`;
  }
  return `
    <nav class="list-pager" aria-label="${esc(libelle || 'Pagination')}">
      <button type="button" class="pager-btn" data-page-step="-1" ${state.page===1?'disabled':''}>‹ Précédent</button>
      <span class="pager-status">Page ${state.page} sur ${totalPages}<small>${start+1}–${start+shown} sur ${total} biens</small></span>
      <button type="button" class="pager-btn" data-page-step="1" ${state.page===totalPages?'disabled':''}>Suivant ›</button>
    </nav>`;
}
