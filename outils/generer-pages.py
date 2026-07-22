#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Génère une page statique par bien, plus sitemap.xml et robots.txt.

Pourquoi ce script existe
-------------------------
La vitrine construit ses annonces en JavaScript, après chargement. Google sait
exécuter du JavaScript, mais il le fait plus tard, moins souvent et sans
garantie : dans le code source de la vitrine, il n'y a aujourd'hui aucune
annonce, aucun prix, aucune commune. Rien à indexer, donc rien à positionner.

Ce script lit les biens publiés et écrit, pour chacun, une vraie page HTML :
titre, prix, description, photos avec attribut alt, données structurées
Schema.org. Ces pages sont statiques, légères, et ne dépendent d'aucun
JavaScript pour afficher leur contenu.

Aucun secret n'est nécessaire : la vue public_properties est lisible avec la
clé publique, celle qui figure déjà dans le code source du site. Le script peut
donc tourner n'importe où, y compris dans une action GitHub.

Utilisation
-----------
    python outils/generer-pages.py

Régénérer après chaque publication ou modification de bien.
"""

import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from datetime import date

# --- Réglages ---------------------------------------------------------------

SUPABASE_URL = "https://avanktgaxepzpqmsiauz.supabase.co"
SUPABASE_KEY = "sb_publishable_nAQnS82ru9h-beIDPKMqPA_JO_aSYc-"
SITE = "https://pabbusiness221.github.io/PAB-Immo"

TEL = "+221778494111"
TEL_AFFICHE = "+221 77 849 41 11"
AGENCE = "PAB Immo"

# Jeton de validation Google Search Console. Le récupérer dans Search Console
# (Ajouter une propriété > Préfixe d'URL > Balise HTML), coller ici la valeur
# du champ content, puis relancer le script. Laisser vide tant qu'on ne l'a
# pas : une balise vide serait invalide.
GOOGLE_VERIFICATION = ""

# Tant que la vitrine est derrière la page de maintenance, les pages générées
# ne doivent pas être indexées : elles renverraient vers un site en travaux.
# Passer à False le jour du retour en ligne, puis relancer le script.
EN_MAINTENANCE = True

# Page d'accueil réelle du catalogue, selon l'état du site.
ACCUEIL = "vitrine.html" if EN_MAINTENANCE else "Biens-Immo.html"

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(RACINE, "bien")


# --- Utilitaires ------------------------------------------------------------

def esc(v):
    """Échappe pour insertion dans du HTML."""
    return (str(v if v is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def slug(txt):
    """« Terrain à vendre — Keur Moussa » -> « terrain-a-vendre-keur-moussa »."""
    txt = unicodedata.normalize("NFKD", str(txt))
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = re.sub(r"[^a-zA-Z0-9]+", "-", txt).strip("-").lower()
    return re.sub(r"-{2,}", "-", txt)


def couleurs_types():
    """Les couleurs par type de bien, lues dans commun.js.

    Les recopier ici créerait deux vérités qui divergeraient au premier
    changement de charte. On les extrait donc de la source, et on échoue
    bruyamment si la ligne change de forme — mieux vaut un script qui s'arrête
    qu'une page aux mauvaises couleurs.
    """
    js = open(os.path.join(RACINE, "commun.js"), encoding="utf-8").read()
    ligne = re.search(r"const TYPE_COLOR\s*=\s*\{([^}]*)\}", js)
    assert ligne, "TYPE_COLOR introuvable dans commun.js"
    couleurs = {t.strip(): c for t, c in
                re.findall(r"'?([\w\s]+?)'?\s*:\s*'(#[0-9A-Fa-f]{6})'", ligne.group(1))}
    # Contrôler le nombre d'entrées ne suffit pas : la première version de cette
    # fonction en trouvait bien quatre, mais avec une espace au début de chaque
    # nom — « Maison » devenait « Maison » précédé d'un blanc, aucune
    # correspondance, et toutes les vignettes tombaient sur la couleur de repli.
    # On vérifie donc les clés elles-mêmes.
    attendus = {"Terrain", "Maison", "Appartement", "Champ agricole"}
    manquants = attendus - set(couleurs)
    assert not manquants, f"TYPE_COLOR mal lu, types manquants : {manquants} (lu : {couleurs})"
    return couleurs


TYPE_COLOR = None   # rempli au démarrage, voir main()


def lieu_court(nom):
    """« Commune de Sébikhotane » -> « Sébikhotane », « Région de Dakar » ->
    « Dakar », « THIES » -> « Thiès ».

    Les lieux ont été saisis au fil des années avec des formulations et des
    casses différentes. On normalise à l'affichage uniquement : les données du
    portefeuille ne sont pas touchées, c'est à l'agence d'en décider. Et ce sont
    les formes courtes que les gens tapent réellement dans Google — personne ne
    cherche « terrain Commune de Sébikhotane ».
    """
    nom = re.sub(r"^(commune|r[ée]gion|ville|d[ée]partement)\s+d[eu']\s*", "",
                 str(nom).strip(), flags=re.I)
    usuel = {"thies": "Thiès", "dakar": "Dakar"}
    if slug(nom) in usuel:
        return usuel[slug(nom)]
    # « POUT » et « mbirdiam » ont été saisis tels quels. Le titre d'une page est
    # ce que Google affiche en bleu dans ses résultats : une casse bancale y fait
    # mauvais effet. On ne retouche que les noms entièrement en capitales ou
    # entièrement en minuscules — « Thiès Ouest », déjà correct, reste intact.
    if nom.isupper() or nom.islower():
        nom = nom.title()
    return nom


def nom_fichier(b):
    """Nom de la page d'un bien. Une seule définition, appelée aussi bien pour
    écrire le fichier que pour tisser les liens entre pages : deux formules
    parallèles finiraient par diverger et produire des liens morts."""
    action = "a-vendre" if b["operation"] == "Vente" else "a-louer"
    return f"{slug(b['type'])}-{action}-{slug(lieu_court(b['commune']))}-{slug(b['ref'])}.html"


def similaires(b, tous, n=3):
    """Les trois biens à proposer en fin de fiche.

    Sans eux, une personne arrivée de Google n'a qu'une sortie — le bouton
    retour du navigateur — et chaque fiche est un cul-de-sac pour l'exploration
    de Google. On classe par proximité : même commune d'abord, puis même type,
    puis même opération. Ce sont les trois axes sur lesquels un acheteur élargit
    spontanément sa recherche.
    """
    autres = [x for x in tous if x["id"] != b["id"]]
    return sorted(autres, key=lambda x: (x["commune"] != b["commune"],
                                         x["type"] != b["type"],
                                         x["operation"] != b["operation"]))[:n]


def fcfa(n):
    return f"{int(float(n)):,}".replace(",", " ") + " FCFA"


def unite(type_bien):
    return "ha" if type_bien == "Champ agricole" else "m²"


def surface(b):
    """150.0 -> « 150 m² », 4.7 -> « 4,7 ha ». La décimale n'apparaît que si
    elle porte une information."""
    v = float(b["surface"])
    txt = str(int(v)) if v == int(v) else f"{v:.1f}".replace(".", ",")
    return f'{txt} {unite(b["type"])}'


def photo_url(chemin, largeur=None, qualite=70):
    base = f"{SUPABASE_URL}/storage/v1/object/public/property-photos/{chemin}"
    if not largeur:
        return base
    return (base.replace("/storage/v1/object/public/", "/storage/v1/render/image/public/")
            + f"?width={largeur}&quality={qualite}")


def lire(chemin_api):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{chemin_api}",
        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# --- Rédaction des textes ---------------------------------------------------
# Ces formulations sont ce que Google affichera dans ses résultats. Elles
# doivent contenir les mots qu'une personne tape réellement : « terrain à
# vendre », la commune, la région.

def titre_bien(b):
    """Le titre est ce que Google affiche en bleu dans ses résultats. Il doit
    contenir les mots réellement tapés, sans répéter deux fois le même lieu :
    « Appartement à louer à Almadies — Almadies, Dakar » sonne faux."""
    action = "à vendre" if b["operation"] == "Vente" else "à louer"
    commune = lieu_court(b["commune"])
    quartier = lieu_court(b.get("quartier") or "")
    region = lieu_court(b["region"])

    lieu = f"{quartier}, {commune}" if quartier and slug(quartier) != slug(commune) else commune
    # La région n'est ajoutée que si elle apporte une information : « Terrain à
    # vendre à Gueule Tapée, Dakar (Dakar) » n'aide personne.
    if slug(region) not in {slug(m) for m in (commune, quartier) if m}:
        lieu += f" ({region})"
    return f'{b["type"]} {action} à {lieu}'


def description_bien(b):
    action = "à vendre" if b["operation"] == "Vente" else "à louer"
    prix = fcfa(b["price"]) + ("/mois" if b["operation"] == "Location" else "")
    bout = [f'{b["type"]} {action} à {lieu_court(b["commune"])} ({lieu_court(b["region"])})',
            surface(b), prix]
    if b.get("chambres"):
        bout.append(f'{b["chambres"]} chambre' + ("s" if b["chambres"] > 1 else ""))
    txt = " · ".join(bout) + f". Réf. {b['ref']}, {AGENCE}."
    if b.get("description"):
        txt += " " + " ".join(str(b["description"]).split())
    return txt[:300]


def donnees_structurees(b, photos, url):
    """Schema.org. RealEstateListing est le type que Google attend pour une
    annonce immobilière ; l'offre porte le prix et la disponibilité."""
    d = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": titre_bien(b),
        "description": description_bien(b),
        "url": url,
        "datePosted": str(date.today()),
        "identifier": b["ref"],
        "image": [photo_url(p["storage_path"], 1200) for p in photos] or None,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": lieu_court(b["commune"]),
            "addressRegion": lieu_court(b["region"]),
            "addressCountry": "SN",
        },
        "geo": {"@type": "GeoCoordinates", "latitude": b["lat"], "longitude": b["lng"]},
        "offers": {
            "@type": "Offer",
            "price": int(float(b["price"])),
            "priceCurrency": "XOF",
            "availability": ("https://schema.org/InStock" if b["status"] == "Disponible"
                             else "https://schema.org/LimitedAvailability"),
            "seller": {"@type": "RealEstateAgent", "name": AGENCE,
                       "telephone": TEL, "areaServed": "Dakar, Thiès, Sénégal"},
        },
    }
    if b.get("quartier"):
        d["address"]["streetAddress"] = lieu_court(b["quartier"])
    # Une surface ou un nombre de pièces ne se déclarent que s'ils existent :
    # un champ vide dans les données structurées est pénalisant.
    if b.get("surface"):
        d["floorSize"] = {"@type": "QuantitativeValue", "value": float(b["surface"]),
                          "unitCode": "HAR" if b["type"] == "Champ agricole" else "MTK"}
    if b.get("chambres"):
        d["numberOfBedrooms"] = b["chambres"]
    if b.get("salles_bain"):
        d["numberOfBathroomsTotal"] = b["salles_bain"]
    return json.dumps({k: v for k, v in d.items() if v is not None},
                      ensure_ascii=False, indent=2)


# --- Gabarit de page --------------------------------------------------------

def vignette(b, photos):
    """La carte d'un bien, utilisée par les fiches et par la page d'index.

    Près de la moitié des biens n'ont aucune photo. Un rectangle gris pour la
    moitié d'une page donne l'impression d'un site cassé ou vide ; la vitrine
    résout déjà cela en affichant l'icône du type sur sa couleur. On reprend le
    même traitement, avec les mêmes couleurs, lues dans commun.js.
    """
    couleur = TYPE_COLOR.get(b["type"], "#5C6470")
    if photos:
        fond = f'''background-image:url('{photo_url(photos[0]["storage_path"], 400)}')'''
        marque = ""
    else:
        fond = f"background:linear-gradient(135deg,{couleur},#161B22)"
        marque = f'<span class="voisin-type">{esc(b["type"])}</span>'
    return f'''
      <a class="voisin" href="{nom_fichier(b)}">
        <span class="voisin-photo" style="{fond}">{marque}</span>
        <span class="voisin-txt">
          <b>{esc(titre_bien(b))}</b>
          <em>{fcfa(b["price"])}{'/mois' if b["operation"] == "Location" else ''} · {esc(surface(b))}</em>
        </span>
      </a>'''


# Styles communs aux cartes des fiches et de la page d'index.
STYLE_VIGNETTES = """
  .voisins{grid-template-columns:repeat(auto-fit,minmax(210px,1fr));display:grid;gap:12px;}
  .voisin{display:block;text-decoration:none;color:inherit;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);overflow:hidden;transition:border-color .2s,transform .2s;}
  .voisin:hover{border-color:var(--accent);transform:translateY(-2px);}
  .voisin-photo{display:flex;align-items:center;justify-content:center;height:112px;background-size:cover;background-position:center;background-repeat:no-repeat;}
  .voisin-type{color:rgba(255,255,255,.85);font-family:'Manrope',sans-serif;font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;}
  .voisin-txt{display:block;padding:11px 13px;}
  .voisin-txt b{display:block;font-size:13.5px;font-weight:700;line-height:1.35;}
  .voisin-txt em{display:block;font-style:normal;font-family:'Manrope',sans-serif;font-weight:800;font-size:13.5px;margin-top:5px;}
"""


def page_bien(b, photos, voisins=()):
    nom = nom_fichier(b)
    url = f"{SITE}/bien/{nom}"
    titre = titre_bien(b)
    desc = description_bien(b)
    prix = fcfa(b["price"]) + ("<span> /mois</span>" if b["operation"] == "Location" else "")
    couverture = photo_url(photos[0]["storage_path"], 1200) if photos else f"{SITE}/assets/dakar-aerienne.jpg"

    # Message WhatsApp pré-rempli : le visiteur n'a rien à retaper.
    wa = f"https://wa.me/{TEL.lstrip('+')}?text=" + urllib.parse.quote(
        f"Bonjour, je suis intéressé(e) par le bien {b['ref']} — {b['type']} à {lieu_court(b['commune'])}.")

    caracs = []
    if b.get("chambres"):    caracs.append(("Chambres", b["chambres"]))
    if b.get("salons"):      caracs.append(("Salons", b["salons"]))
    if b.get("salles_bain"): caracs.append(("Salles de bain", b["salles_bain"]))
    if b.get("cuisine"):     caracs.append(("Cuisine", b["cuisine"]))

    galerie = "".join(
        f'''
      <figure class="photo">
        <img src="{photo_url(p["storage_path"], 900)}"
             srcset="{photo_url(p["storage_path"], 480)} 480w, {photo_url(p["storage_path"], 900)} 900w, {photo_url(p["storage_path"], 1400)} 1400w"
             sizes="(max-width: 700px) 100vw, 700px"
             width="900" height="600"
             alt="{esc(b["type"])} {esc("à vendre" if b["operation"] == "Vente" else "à louer")} à {esc(b["commune"])} — photo {i + 1}"
             loading="{'eager' if i == 0 else 'lazy'}" decoding="async" fetchpriority="{'high' if i == 0 else 'auto'}" />
      </figure>''' for i, p in enumerate(photos))

    voisins_html = ""
    if voisins:
        cartes = "".join(vignette(v, vp) for v, vp in voisins)
        voisins_html = f'<h2>Autres biens qui pourraient vous intéresser</h2>\n  <div class="voisins">{cartes}\n  </div>'

    return nom, f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(titre)} | {AGENCE}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{url}" />
{f'<meta name="google-site-verification" content="{GOOGLE_VERIFICATION}" />' if GOOGLE_VERIFICATION else ''}
{'<meta name="robots" content="noindex, follow" />' if EN_MAINTENANCE else '<meta name="robots" content="index, follow, max-image-preview:large" />'}
<meta property="og:type" content="website" />
<meta property="og:site_name" content="{AGENCE}" />
<meta property="og:locale" content="fr_FR" />
<meta property="og:title" content="{esc(titre)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:image" content="{esc(couverture)}" />
<meta property="og:url" content="{url}" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{esc(titre)}" />
<meta name="twitter:description" content="{esc(desc)}" />
<meta name="twitter:image" content="{esc(couverture)}" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../commun.css" />
<style>
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
  .bandeau{{background:var(--night);padding:14px 20px;}}
  .bandeau a{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a span{{color:var(--accent);}}
  main{{max-width:760px;margin:0 auto;padding:26px 20px 60px;}}
  .fil{{font-size:12.5px;color:var(--ink-soft);margin:0 0 16px;}}
  .fil a{{color:var(--ink-soft);}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;line-height:1.15;margin:0 0 10px;}}
  .lieu{{color:var(--ink-soft);font-size:14.5px;margin:0 0 18px;}}
  .prix{{font-family:'Manrope',sans-serif;font-size:26px;font-weight:800;margin:0 0 4px;}}
  .prix span{{font-size:15px;font-weight:600;color:var(--ink-soft);}}
  .etat{{display:inline-block;font-size:11.5px;font-weight:800;padding:5px 12px;border-radius:999px;margin-bottom:22px;}}
  .photo{{margin:0 0 10px;}}
  .photo img{{width:100%;height:auto;display:block;border-radius:var(--radius-md);background:var(--surface-alt);}}
  h2{{font-family:'Manrope',sans-serif;font-size:17px;font-weight:800;margin:30px 0 12px;}}
  .faits{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:0;padding:0;list-style:none;}}
  .faits li{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px 14px;}}
  .faits b{{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-soft);font-weight:700;}}
  .faits span{{font-size:15px;font-weight:800;}}
  .texte{{font-size:15px;line-height:1.7;}}
  .contact{{margin-top:32px;background:linear-gradient(140deg,var(--night),var(--night-2));border-radius:var(--radius-lg);padding:24px;}}
  .contact p{{color:rgba(255,255,255,.74);font-size:14px;margin:0 0 16px;line-height:1.6;}}
  .contact h2{{color:#fff;margin:0 0 6px;}}
  .actions{{display:flex;gap:10px;flex-wrap:wrap;}}
  .actions a{{flex:1 1 200px;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;border-radius:999px;font-weight:700;font-size:14px;text-decoration:none;}}
  .wa{{background:#25D366;color:#fff;}} .tel{{background:var(--accent);color:#1E1607;}}
{STYLE_VIGNETTES}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.7;}}
</style>
<script type="application/ld+json">
{donnees_structurees(b, photos, url)}
</script>
</head>
<body>
<header class="bandeau"><a href="../{ACCUEIL}">PAB <span>Immo</span></a></header>

<main>
  <nav class="fil" aria-label="Fil d'Ariane">
    <a href="./">Tous les biens</a> › {esc(b["type"])} › {esc(lieu_court(b["commune"]))}
  </nav>

  <h1>{esc(titre)}</h1>
  <p class="lieu">{esc((lieu_court(b["quartier"]) + ", ") if b.get("quartier") else "")}{esc(lieu_court(b["commune"]))}, région de {esc(lieu_court(b["region"]))}</p>
  <p class="prix">{prix}</p>
  <p class="etat" style="background:{'rgba(47,122,78,.12);color:#2F7A4E' if b["status"] == "Disponible" else 'rgba(226,162,44,.15);color:#8F6414'}">{esc(b["status"])}</p>

  {'<h2>Photos</h2>' + galerie if photos else ''}

  <h2>Caractéristiques</h2>
  <ul class="faits">
    <li><b>Type</b><span>{esc(b["type"])}</span></li>
    <li><b>{esc(b["operation"])}</b><span>{fcfa(b["price"])}{'/mois' if b["operation"] == "Location" else ''}</span></li>
    <li><b>Superficie</b><span>{esc(surface(b))}</span></li>
    <li><b>Référence</b><span>{esc(b["ref"])}</span></li>
    {"".join(f'<li><b>{esc(k)}</b><span>{esc(v)}</span></li>' for k, v in caracs)}
  </ul>

  {'<h2>Description</h2><p class="texte">' + esc(b["description"]) + '</p>' if b.get("description") else ''}

  <section class="contact">
    <h2>Intéressé par ce bien ?</h2>
    <p>Référence {esc(b["ref"])} — visites sur rendez-vous à {esc(lieu_court(b["commune"]))}. Nous répondons rapidement.</p>
    <div class="actions">
      <a class="wa" href="{esc(wa)}" target="_blank" rel="noopener">Écrire sur WhatsApp</a>
      <a class="tel" href="tel:{TEL}">{TEL_AFFICHE}</a>
    </div>
  </section>

  {voisins_html}

  <a class="retour" href="./">← Voir tous nos biens à Dakar et Thiès</a>
  <a class="retour" href="../{ACCUEIL}" style="margin-left:18px;">Rechercher sur la carte</a>
</main>

<footer>
  {AGENCE} — terrains, maisons, appartements et champs agricoles à Dakar &amp; Thiès<br>
  {TEL_AFFICHE} · visites sur rendez-vous
</footer>
</body>
</html>
'''


def page_index(biens, par_bien):
    """Page d'index statique de toutes les fiches.

    La vitrine construit sa liste en JavaScript : dans son code source, il n'y
    a aucun lien vers les fiches. Google ne peut donc les atteindre que par le
    sitemap, ce qui suffit à les découvrir mais ne dit rien de leur importance
    relative. Cette page, elle, est du HTML pur : un vrai chemin d'exploration
    qui part d'une adresse et mène aux 24 autres.

    Elle sert aussi les visiteurs : arrivés de Google sur une fiche, ils ont
    enfin une vue d'ensemble sans dépendre du chargement de la vitrine.
    """
    titre = f"Tous nos biens à vendre et à louer à Dakar et Thiès | {AGENCE}"
    desc = (f"{len(biens)} terrains, maisons, appartements et champs agricoles "
            f"à vendre ou à louer à Dakar et Thiès. Prix, superficie et photos "
            f"pour chaque bien. {AGENCE}, visites sur rendez-vous.")
    url = f"{SITE}/bien/"

    sections = ""
    for operation, intitule in (("Vente", "À vendre"), ("Location", "À louer")):
        lot = [b for b in biens if b["operation"] == operation]
        if not lot:
            continue
        # Les biens avec photo d'abord : une page qui s'ouvre sur onze
        # rectangles sans image donne l'impression d'un catalogue vide.
        lot.sort(key=lambda b: (not par_bien.get(b["id"]), lieu_court(b["region"]),
                                lieu_court(b["commune"]), b["type"]))
        cartes = "".join(vignette(b, par_bien.get(b["id"], [])) for b in lot)
        sections += (f'\n  <h2>{intitule} — {len(lot)} bien'
                     f'{"s" if len(lot) > 1 else ""}</h2>\n'
                     f'  <div class="voisins">{cartes}\n  </div>\n')

    return f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(titre)}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{url}" />
{f'<meta name="google-site-verification" content="{GOOGLE_VERIFICATION}" />' if GOOGLE_VERIFICATION else ''}
{'<meta name="robots" content="noindex, follow" />' if EN_MAINTENANCE else '<meta name="robots" content="index, follow, max-image-preview:large" />'}
<meta property="og:type" content="website" />
<meta property="og:site_name" content="{AGENCE}" />
<meta property="og:locale" content="fr_FR" />
<meta property="og:title" content="{esc(titre)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:url" content="{url}" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../commun.css" />
<style>
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
  .bandeau{{background:var(--night);padding:14px 20px;}}
  .bandeau a{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a span{{color:var(--accent);}}
  main{{max-width:960px;margin:0 auto;padding:26px 20px 60px;}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;margin:0 0 10px;}}
  .intro{{color:var(--ink-soft);font-size:15px;line-height:1.65;margin:0 0 8px;max-width:60ch;}}
  h2{{font-family:'Manrope',sans-serif;font-size:17px;font-weight:800;margin:32px 0 14px;}}
{STYLE_VIGNETTES}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.7;}}
</style>
</head>
<body>
<header class="bandeau"><a href="../{ACCUEIL}">PAB <span>Immo</span></a></header>

<main>
  <h1>Tous nos biens à Dakar et Thiès</h1>
  <p class="intro">
    {len(biens)} biens disponibles : terrains, maisons, appartements et champs
    agricoles, à vendre ou à louer dans les régions de Dakar et de Thiès.
    Chaque fiche indique le prix, la superficie et les photos du bien.
  </p>
{sections}
  <a class="retour" href="../{ACCUEIL}">← Rechercher sur la carte</a>
</main>

<footer>
  {AGENCE} — {TEL_AFFICHE} · visites sur rendez-vous
</footer>
</body>
</html>
'''


# --- Programme --------------------------------------------------------------

def main():
    global TYPE_COLOR
    TYPE_COLOR = couleurs_types()

    print("Lecture des biens publiés…")
    biens = lire("public_properties?select=*")
    photos = lire("public_property_photos?select=*&order=position.asc")
    par_bien = {}
    for p in photos:
        par_bien.setdefault(p["property_id"], []).append(p)

    os.makedirs(DOSSIER, exist_ok=True)
    # On repart d'un dossier propre : un bien dépublié ne doit pas laisser
    # une page fantôme derrière lui.
    for ancien in os.listdir(DOSSIER):
        if ancien.endswith(".html"):
            os.remove(os.path.join(DOSSIER, ancien))

    urls = []
    manifeste = {}
    for b in biens:
        voisins = [(v, par_bien.get(v["id"], [])) for v in similaires(b, biens)]
        nom, html = page_bien(b, par_bien.get(b["id"], []), voisins)
        with open(os.path.join(DOSSIER, nom), "w", encoding="utf-8") as f:
            f.write(html)
        manifeste[b["ref"]] = nom
        urls.append(f"{SITE}/bien/{nom}")
    print(f"  {len(urls)} pages écrites dans bien/")

    # --- bien/index.json ----------------------------------------------------
    # La vitrine s'en sert pour pointer vers la fiche d'un bien. Elle pourrait
    # recalculer le nom du fichier en JavaScript, mais elle fabriquerait alors
    # des liens vers des pages pas encore générées — un bien publié ce matin
    # n'a pas de fiche tant que ce script n'a pas tourné. Ce fichier ne liste
    # que ce qui existe vraiment : pas de lien mort possible.
    with open(os.path.join(DOSSIER, "index.json"), "w", encoding="utf-8") as f:
        json.dump(manifeste, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"  bien/index.json : {len(manifeste)} références")

    with open(os.path.join(DOSSIER, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_index(biens, par_bien))
    print("  bien/index.html : page d'index statique")

    # --- sitemap.xml --------------------------------------------------------
    aujourdhui = date.today().isoformat()
    lignes = [f"  <url><loc>{SITE}/{ACCUEIL}</loc><lastmod>{aujourdhui}</lastmod>"
              f"<changefreq>daily</changefreq><priority>1.0</priority></url>",
              f"  <url><loc>{SITE}/bien/</loc><lastmod>{aujourdhui}</lastmod>"
              f"<changefreq>daily</changefreq><priority>0.9</priority></url>"]
    lignes += [f"  <url><loc>{u}</loc><lastmod>{aujourdhui}</lastmod>"
               f"<changefreq>weekly</changefreq><priority>0.8</priority></url>" for u in urls]
    with open(os.path.join(RACINE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "\n".join(lignes) + "\n</urlset>\n")
    print(f"  sitemap.xml : {len(lignes)} adresses")

    # --- robots.txt ---------------------------------------------------------
    # ATTENTION : sur GitHub Pages, ce fichier n'est PAS lu par les robots.
    # Ils ne consultent que https://pabbusiness221.github.io/robots.txt, à la
    # racine du domaine, qui appartient à un autre dépôt. Vérifié : 404.
    # Ce fichier ne deviendra effectif qu'avec un nom de domaine propre.
    #
    # C'est pourquoi la suspension d'indexation repose sur les balises
    # noindex des pages, et non sur ce fichier. C'est de toute façon le bon
    # outil : un robots.txt bloquant empêcherait Google de LIRE le noindex,
    # et il pourrait alors indexer l'adresse malgré tout, sur la foi d'un
    # lien externe.
    regles = [
        "# Ce fichier ne prend effet qu'avec un nom de domaine propre.",
        "# Sur github.io, seul le robots.txt de la racine du domaine est lu.",
        "",
        "User-agent: *",
        "Disallow: /Portefeuille-Immo.html",   # l'espace de gestion n'a rien à faire dans un index
        "Allow: /",
        "",
        f"Sitemap: {SITE}/sitemap.xml",
        "",
    ]
    with open(os.path.join(RACINE, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(regles))
    print("  robots.txt  : écrit (sans effet sur github.io — voir le commentaire)")
    if EN_MAINTENANCE:
        print("  indexation  : suspendue par les balises noindex des pages")

    print("\nTerminé. Relancer ce script après chaque publication ou modification de bien.")


if __name__ == "__main__":
    sys.exit(main())
