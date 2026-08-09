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

import hashlib
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
EMAIL = "pab.business221@gmail.com"
AGENCE = "PAB Immo"
# Mentions légales, reprises telles quelles au pied des fiches générées.
NINEA = "012603686"
RCCM = "SN DKR 2025 A 44101"

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
DOSSIER_EN = os.path.join(DOSSIER, "en")
DOSSIER_GUIDES = os.path.join(RACINE, "guides")

# Nombre de descriptions traduites par exécution (voir prechauffer_traductions).
# Le plafond de la fonction Edge est de 10 par heure et par adresse IP ; on
# reste dessous. L'action tournant tous les quarts d'heure, un catalogue de
# vingt biens est entièrement traduit en moins de deux heures.
TRADUCTIONS_PAR_PASSAGE = 8


# --- Vocabulaire anglais ------------------------------------------------------
# Les fiches existent en deux langues. Le français reste la langue source :
# c'est lui qui sert de clé, exactement comme le dictionnaire de la vitrine.
# Seul le texte du GÉNÉRATEUR est ici — la description d'un bien, elle, est
# rédigée par l'agence et traduite par l'IA (colonne description_en).

EN = {
    # Types de biens et opérations
    "Terrain": "Land", "Maison": "House", "Appartement": "Apartment",
    "Studio": "Studio", "Champ agricole": "Farmland",
    "Vente": "Sale", "Location": "Rental",
    "à vendre": "for sale", "à louer": "for rent",
    # Statuts
    "Disponible": "Available", "Réservé": "Under offer",
    "Titre foncier": "Freehold title", "Bail": "Lease",
    "Délibération": "Council deliberation",
    "Meublé": "Furnished", "Non meublé": "Unfurnished",
    # Le champ « cuisine » est saisi librement dans le portefeuille : on couvre
    # les valeurs réellement présentes en base. Une valeur inconnue traverse
    # telle quelle plutôt que de vider la ligne.
    "Équipée": "Equipped", "Simple": "Basic",
    "Américaine": "American style", "Kitchenette": "Kitchenette",
    "Oui": "Yes", "Non": "No",
    # Caractéristiques
    "Chambres": "Bedrooms", "Salons": "Living rooms",
    "Salles de bain": "Bathrooms", "Cuisine": "Kitchen",
    "Étage": "Floor", "Année de construction": "Year built",
    "Charges": "Utility fees", "Caution": "Security deposit",
    "Type": "Type", "Superficie": "Size", "Référence": "Reference",
    "Statut foncier": "Land title status",
    # Chrome de la page
    "Tous les biens": "All properties",
    "Fil d'Ariane": "Breadcrumb",
    "Photos": "Photos",
    "Caractéristiques": "Features",
    "Description": "Description",
    "Intéressé par ce bien ?": "Interested in this property?",
    "Écrire sur WhatsApp": "Message on WhatsApp",
    "Nom": "Name",
    "Votre nom": "Your name",
    "Téléphone ou email": "Phone or email",
    "Pour vous répondre": "So we can reply",
    "Message": "Message",
    "Votre question sur ce bien…": "Your question about this property…",
    "Site web": "Website",
    "Envoyer le message": "Send message",
    "Envoi…": "Sending…",
    "Autres biens qui pourraient vous intéresser": "Other properties you may like",
    "Mentions légales": "Legal notice",
    "Politique de confidentialité": "Privacy policy",
    "visites sur rendez-vous": "visits by appointment",
    "Disponible à partir du": "Available from",
    # Messages du formulaire
    "Message envoyé ! On vous recontacte rapidement.":
        "Message sent! We will get back to you shortly.",
    "Merci de remplir tous les champs.": "Please fill in every field.",
    "Échec de l'envoi. Réessayez, ou écrivez-nous directement sur WhatsApp.":
        "Sending failed. Please try again, or message us on WhatsApp.",
    "Échec de l'envoi. Vérifiez votre connexion, ou écrivez-nous sur WhatsApp.":
        "Sending failed. Check your connection, or message us on WhatsApp.",
}


def tr(texte, lang):
    """Traduit une clé française. Renvoie le français tel quel en français, et
    aussi en anglais si la clé manque — une page dans une langue approximative
    vaut mieux qu'une page cassée."""
    return EN.get(texte, texte) if lang == "en" else texte

# Mémoire du générateur, d'une exécution à l'autre : pour chaque bien, une
# empreinte de ses données, la date où sa fiche est apparue et celle du dernier
# changement réel.
#
# Sans cela, deux dates seraient inventées à chaque passage. Le « lastmod » du
# sitemap vaudrait toujours aujourd'hui — Google finit par ne plus y croire, et
# une exécution automatique produirait un commit chaque nuit même sans rien à
# dire. Et le « datePosted » des données structurées affirmerait que les vingt-
# quatre biens ont été publiés ce matin, ce qui est simplement faux.
#
# Ce fichier doit être versionné : c'est lui qui porte la mémoire.
ETAT = os.path.join(RACINE, "outils", "etat-fiches.json")


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
    attendus = {"Terrain", "Maison", "Appartement", "Studio", "Champ agricole"}
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


def nom_fichier(b, lang="fr"):
    """Nom de la page d'un bien. Une seule définition, appelée aussi bien pour
    écrire le fichier que pour tisser les liens entre pages : deux formules
    parallèles finiraient par diverger et produire des liens morts.

    L'adresse anglaise porte des mots anglais — « land-for-sale-keur-moussa »
    et non « terrain-a-vendre-keur-moussa ». C'est là que se joue une partie du
    référencement : l'adresse d'une page est un des rares endroits où Google
    lit encore les mots-clés. Ces pages étant nouvelles, aucun lien existant
    n'est cassé au passage.
    """
    if lang == "en":
        action = "for-sale" if b["operation"] == "Vente" else "for-rent"
        type_en = EN.get(b["type"], b["type"])
        return f"{slug(type_en)}-{action}-{slug(lieu_court(b['commune']))}-{slug(b['ref'])}.html"
    action = "a-vendre" if b["operation"] == "Vente" else "a-louer"
    return f"{slug(b['type'])}-{action}-{slug(lieu_court(b['commune']))}-{slug(b['ref'])}.html"


def url_fiche(b, lang):
    """Adresse absolue d'une fiche, dans la langue demandée."""
    dossier = "bien/en" if lang == "en" else "bien"
    return f"{SITE}/{dossier}/{nom_fichier(b, lang)}"


def empreinte(b, photos):
    """Résume tout ce qui, dans les données, détermine le contenu d'une fiche.

    Deux exécutions qui trouvent la même empreinte ont produit la même page :
    inutile d'en changer la date. On empreinte les données plutôt que le HTML
    rendu, parce que le HTML contient justement les dates — on tournerait en
    rond.
    """
    matiere = json.dumps([b, [p["storage_path"] for p in photos]],
                         sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(matiere.encode("utf-8")).hexdigest()


def dates_des_fiches(biens, par_bien):
    """Confronte les données du jour à l'état de la dernière exécution.

    Renvoie, par référence : la date de première apparition (qui sert de date de
    publication) et celle du dernier changement réel (qui sert de lastmod).
    """
    aujourdhui = date.today().isoformat()
    try:
        with open(ETAT, encoding="utf-8") as f:
            ancien = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        ancien = {}

    etat = {}
    for b in biens:
        e = empreinte(b, par_bien.get(b["id"], []))
        precedent = ancien.get(b["ref"], {})
        etat[b["ref"]] = {
            "empreinte": e,
            "premiere": precedent.get("premiere", aujourdhui),
            # Inchangé depuis la dernière fois : on conserve la date d'alors.
            "modifie": (precedent.get("modifie", aujourdhui)
                        if precedent.get("empreinte") == e else aujourdhui),
        }
    return etat, set(ancien) != set(etat)


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


# ---- Équivalence en euros et dollars, pour les acheteurs de la diaspora ----
# Mêmes valeurs que dans commun.js, forcément dupliquées : Python et le
# JavaScript du navigateur ne partagent aucun fichier. Les deux constantes
# doivent être corrigées ensemble.
#
# Le FCFA (XOF) est arrimé à l'euro à un taux FIXE depuis 1999 (traité entre
# la zone UEMOA et la zone euro) : 655,957 F CFA pour 1 € n'est pas une
# estimation, c'est un taux légalement invariable, quel que soit le marché.
TAUX_XOF_EUR = 655.957
# Le dollar, lui, flotte réellement contre le FCFA. Valeur indicative (ordre
# de grandeur au 2 août 2026) à corriger à la main de temps en temps.
TAUX_XOF_USD = 600


def prix_secondaire(prix_fcfa):
    eur = f"{round(float(prix_fcfa) / TAUX_XOF_EUR):,}".replace(",", " ")
    usd = f"{round(float(prix_fcfa) / TAUX_XOF_USD):,}".replace(",", " ")
    return f"≈ {eur} € · {usd} $US"


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


# Dimensions de l'image d'aperçu social, format standard des cartes de partage.
OG_W, OG_H = 1200, 630

def og_image_url(chemin):
    """Image d'aperçu pour WhatsApp et Facebook : un recadrage à taille FIXE
    1200x630. La galerie sert des images en hauteur variable ; un aperçu social,
    lui, doit avoir des dimensions connues et déclarées (og:image:width/height),
    sinon WhatsApp refuse souvent de l'afficher. `resize=cover` remplit le cadre
    sans déformer."""
    return (f"{SUPABASE_URL}/storage/v1/render/image/public/property-photos/{chemin}"
            f"?width={OG_W}&height={OG_H}&resize=cover&quality=75")


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

def titre_bien(b, lang="fr"):
    """Le titre est ce que Google affiche en bleu dans ses résultats. Il doit
    contenir les mots réellement tapés, sans répéter deux fois le même lieu :
    « Appartement à louer à Almadies — Almadies, Dakar » sonne faux."""
    commune = lieu_court(b["commune"])
    quartier = lieu_court(b.get("quartier") or "")
    region = lieu_court(b["region"])

    lieu = f"{quartier}, {commune}" if quartier and slug(quartier) != slug(commune) else commune
    # La région n'est ajoutée que si elle apporte une information : « Terrain à
    # vendre à Gueule Tapée, Dakar (Dakar) » n'aide personne.
    if slug(region) not in {slug(m) for m in (commune, quartier) if m}:
        lieu += f" ({region})"

    if lang == "en":
        action = tr("à vendre" if b["operation"] == "Vente" else "à louer", "en")
        return f'{tr(b["type"], "en")} {action} in {lieu}'
    action = "à vendre" if b["operation"] == "Vente" else "à louer"
    return f'{b["type"]} {action} à {lieu}'


def texte_description(b, lang):
    """La description rédigée par l'agence, dans la langue demandée.

    En anglais : la traduction mise en cache par la fonction Edge
    (description_en). Si elle manque encore — un bien ajouté depuis le dernier
    passage, par exemple — on ne renvoie RIEN plutôt que le texte français :
    un paragraphe en français au milieu d'une page anglaise dessert la page
    autant qu'il dessert le lecteur. Le prochain passage la trouvera traduite
    (voir prechauffer_traductions).
    """
    if lang == "en":
        return (b.get("description_en") or "").strip() or None
    return (b.get("description") or "").strip() or None


def description_bien(b, lang="fr"):
    prix = fcfa(b["price"]) + (("/mo" if lang == "en" else "/mois")
                               if b["operation"] == "Location" else "")
    if lang == "en":
        action = tr("à vendre" if b["operation"] == "Vente" else "à louer", "en")
        bout = [f'{tr(b["type"], "en")} {action} in {lieu_court(b["commune"])}'
                f' ({lieu_court(b["region"])})', surface(b), prix]
        if b.get("chambres"):
            bout.append(f'{b["chambres"]} bedroom' + ("s" if b["chambres"] > 1 else ""))
        txt = " · ".join(bout) + f". Ref. {b['ref']}, {AGENCE}."
    else:
        action = "à vendre" if b["operation"] == "Vente" else "à louer"
        bout = [f'{b["type"]} {action} à {lieu_court(b["commune"])} ({lieu_court(b["region"])})',
                surface(b), prix]
        if b.get("chambres"):
            bout.append(f'{b["chambres"]} chambre' + ("s" if b["chambres"] > 1 else ""))
        txt = " · ".join(bout) + f". Réf. {b['ref']}, {AGENCE}."
    corps = texte_description(b, lang)
    if corps:
        txt += " " + " ".join(corps.split())
    return txt[:300]


def donnees_structurees(b, photos, url, publiee, lang="fr"):
    """Schema.org. RealEstateListing est le type que Google attend pour une
    annonce immobilière ; l'offre porte le prix et la disponibilité."""
    d = {
        "@context": "https://schema.org",
        "@type": "RealEstateListing",
        "name": titre_bien(b, lang),
        "description": description_bien(b, lang),
        "inLanguage": "en" if lang == "en" else "fr",
        "url": url,
        # Date où la fiche est apparue sur le site, et non date du jour : dire
        # que les vingt-quatre biens ont été publiés ce matin serait faux, et
        # Schema.org prend cette date au mot.
        "datePosted": publiee,
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

def vignette(b, photos, lang="fr"):
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
        marque = f'<span class="voisin-type">{esc(tr(b["type"], lang))}</span>'
    suffixe = ('/mo' if lang == "en" else '/mois') if b["operation"] == "Location" else ''
    return f'''
      <a class="voisin" href="{nom_fichier(b, lang)}">
        <span class="voisin-photo" style="{fond}">{marque}</span>
        <span class="voisin-txt">
          <b>{esc(titre_bien(b, lang))}</b>
          <em>{fcfa(b["price"])}{suffixe} · {esc(surface(b))}</em>
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


def page_bien(b, photos, voisins=(), publiee=None, lang="fr"):
    nom = nom_fichier(b, lang)
    url = url_fiche(b, lang)
    url_fr, url_en = url_fiche(b, "fr"), url_fiche(b, "en")
    # Depuis bien/en/, tout ce qui est à la racine est deux crans plus haut.
    prefixe = "../.." if lang == "en" else ".."
    # Lien vers l'autre langue : les deux fiches sont dans des dossiers
    # différents, un simple nom de fichier ne suffit donc pas.
    autre_lang = "fr" if lang == "en" else "en"
    lien_autre = (f"../{nom_fichier(b, 'fr')}" if lang == "en"
                  else f"en/{nom_fichier(b, 'en')}")
    titre = titre_bien(b, lang)
    desc = description_bien(b, lang)
    suffixe_mois = ('/mo' if lang == "en" else '/mois') if b["operation"] == "Location" else ''
    prix = fcfa(b["price"]) + (f"<span> {suffixe_mois}</span>" if suffixe_mois else "")
    # Image d'aperçu au partage : la photo du bien recadrée en 1200x630, ou
    # l'image générique (celle du héros de la vitrine) faute de photo. On
    # garde ses dimensions pour les déclarer, ce qui fiabilise l'aperçu sur
    # WhatsApp et Facebook.
    if photos:
        couverture = og_image_url(photos[0]["storage_path"])
        og_w, og_h = OG_W, OG_H
    else:
        couverture = f"{SITE}/assets/dakar-panorama.jpg"
        og_w, og_h = 1536, 1024

    # Message WhatsApp pré-rempli : le visiteur n'a rien à retaper. Le message
    # part dans SA langue — c'est lui qui l'envoie, et l'agence lit les deux.
    if lang == "en":
        texte_wa = (f"Hello, I am interested in property {b['ref']} — "
                    f"{tr(b['type'], 'en')} in {lieu_court(b['commune'])}.")
    else:
        texte_wa = (f"Bonjour, je suis intéressé(e) par le bien {b['ref']} — "
                    f"{b['type']} à {lieu_court(b['commune'])}.")
    wa = f"https://wa.me/{TEL.lstrip('+')}?text=" + urllib.parse.quote(texte_wa)

    caracs = []
    if b.get("chambres"):    caracs.append(("Chambres", b["chambres"]))
    if b.get("salons"):      caracs.append(("Salons", b["salons"]))
    if b.get("salles_bain"): caracs.append(("Salles de bain", b["salles_bain"]))
    if b.get("cuisine"):     caracs.append(("Cuisine", tr(b["cuisine"], lang)))
    if b.get("etage"):       caracs.append(("Étage", b["etage"]))
    if b.get("annee_construction"): caracs.append(("Année de construction", b["annee_construction"]))
    if b.get("meuble") is not None: caracs.append(("Meublé", tr("Oui" if b["meuble"] else "Non", lang)))
    # Les charges sont mensuelles par nature : leur suffixe ne dépend pas de
    # l'opération, contrairement à celui du prix.
    if b.get("charges"):     caracs.append(("Charges", fcfa(b["charges"]) + ("/mo" if lang == "en" else "/mois")))
    if b.get("caution"):     caracs.append(("Caution", fcfa(b["caution"])))

    # Distinct du statut Disponible/Réservé : ceci dit à partir de quand un
    # locataire peut effectivement emménager. Inutile de l'afficher si la
    # date est déjà passée — le bien est alors simplement disponible.
    disponible_futur = bool(b.get("date_disponibilite")) and b["date_disponibilite"] > date.today().isoformat()

    galerie = "".join(
        f'''
      <figure class="photo">
        <img src="{photo_url(p["storage_path"], 900)}"
             srcset="{photo_url(p["storage_path"], 480)} 480w, {photo_url(p["storage_path"], 900)} 900w, {photo_url(p["storage_path"], 1400)} 1400w"
             sizes="(max-width: 700px) 100vw, 700px"
             width="900" height="600"
             alt="{esc(tr(b["type"], lang))} {esc(tr("à vendre" if b["operation"] == "Vente" else "à louer", lang))} {'in' if lang == 'en' else 'à'} {esc(b["commune"])} — photo {i + 1}"
             loading="{'eager' if i == 0 else 'lazy'}" decoding="async" fetchpriority="{'high' if i == 0 else 'auto'}" />
      </figure>''' for i, p in enumerate(photos))

    voisins_html = ""
    if voisins:
        cartes = "".join(vignette(v, vp, lang) for v, vp in voisins)
        voisins_html = (f'<h2>{tr("Autres biens qui pourraient vous intéresser", lang)}</h2>'
                        f'\n  <div class="voisins">{cartes}\n  </div>')

    return nom, f'''<!DOCTYPE html>
<html lang="{'en' if lang == 'en' else 'fr'}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(titre)} | {AGENCE}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{url}" />
<link rel="alternate" hreflang="fr" href="{url_fr}" />
<link rel="alternate" hreflang="en" href="{url_en}" />
<link rel="alternate" hreflang="x-default" href="{url_fr}" />
{f'<meta name="google-site-verification" content="{GOOGLE_VERIFICATION}" />' if GOOGLE_VERIFICATION else ''}
{'<meta name="robots" content="noindex, follow" />' if EN_MAINTENANCE else '<meta name="robots" content="index, follow, max-image-preview:large" />'}
<meta property="og:type" content="website" />
<meta property="og:site_name" content="{AGENCE}" />
<meta property="og:locale" content="{'en_GB' if lang == 'en' else 'fr_FR'}" />
<meta property="og:title" content="{esc(titre)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:image" content="{esc(couverture)}" />
<meta property="og:image:secure_url" content="{esc(couverture)}" />
<meta property="og:image:type" content="image/jpeg" />
<meta property="og:image:width" content="{og_w}" />
<meta property="og:image:height" content="{og_h}" />
<meta property="og:image:alt" content="{esc(titre)}" />
<meta property="og:url" content="{url}" />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{esc(titre)}" />
<meta name="twitter:description" content="{esc(desc)}" />
<meta name="twitter:image" content="{esc(couverture)}" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="preconnect" href="{SUPABASE_URL}">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefixe}/commun.css" />
<style>
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
  .bandeau{{background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;}}
  .bandeau .lang{{color:rgba(255,255,255,.75);font-size:12.5px;font-weight:700;letter-spacing:.04em;border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:4px 11px;}}
  .bandeau .lang:hover{{color:var(--gold);border-color:var(--gold);}}
  .bandeau a{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a span{{color:var(--accent);}}
  main{{max-width:760px;margin:0 auto;padding:26px 20px 60px;}}
  .fil{{font-size:12.5px;color:var(--ink-soft);margin:0 0 16px;}}
  .fil a{{color:var(--ink-soft);}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;line-height:1.15;margin:0 0 10px;}}
  .lieu{{color:var(--ink-soft);font-size:14.5px;margin:0 0 18px;}}
  .prix{{font-family:'Manrope',sans-serif;font-size:26px;font-weight:800;margin:0 0 4px;}}
  .prix span{{font-size:15px;font-weight:600;color:var(--ink-soft);}}
  .prix-secondaire{{font-size:13px;color:var(--ink-soft);margin:0 0 14px;}}
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
  .contact-form{{margin-top:18px;padding-top:18px;border-top:1px solid rgba(255,255,255,.14);}}
  .contact-form label{{display:block;color:rgba(255,255,255,.82);font-size:12.5px;font-weight:700;margin:0 0 6px;}}
  .contact-form input,.contact-form textarea{{width:100%;box-sizing:border-box;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.22);border-radius:var(--radius-md);color:#fff;font:inherit;font-size:14px;padding:10px 12px;margin:0 0 12px;}}
  .contact-form input::placeholder,.contact-form textarea::placeholder{{color:rgba(255,255,255,.45);}}
  .contact-form textarea{{min-height:80px;resize:vertical;font-family:inherit;}}
  .contact-form button{{width:100%;min-height:48px;border:none;border-radius:999px;background:var(--accent);color:#1E1607;font-weight:800;font-size:14px;cursor:pointer;}}
  .contact-form button:disabled{{opacity:.6;cursor:default;}}
  .cf-msg{{margin:10px 0 0;font-size:13px;font-weight:700;min-height:16px;}}
  .cf-msg.err{{color:#F3A9A0;}} .cf-msg.ok{{color:#8FE0B3;}}
  /* Piège anti-bot : hors écran plutôt que display:none, pour rester "visible"
     aux robots qui vérifient le style calculé avant de tout remplir. */
  .hp-field{{position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;overflow:hidden;opacity:0;}}
{STYLE_VIGNETTES}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.9;}}
  footer a{{color:rgba(255,255,255,.72);text-decoration:none;font-weight:600;}}
  footer a:hover{{color:var(--gold);}}
  footer .reg{{opacity:.65;font-size:11.5px;}}
</style>
<script type="application/ld+json">
{donnees_structurees(b, photos, url, publiee or date.today().isoformat(), lang)}
</script>
</head>
<body>
<header class="bandeau">
  <a href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  <a class="lang" href="{lien_autre}" hreflang="{autre_lang}" lang="{autre_lang}">{'Français' if lang == 'en' else 'English'}</a>
</header>

<main>
  <nav class="fil" aria-label="{tr("Fil d'Ariane", lang)}">
    <a href="./">{tr("Tous les biens", lang)}</a> › {esc(tr(b["type"], lang))} › {esc(lieu_court(b["commune"]))}
  </nav>

  <h1>{esc(titre)}</h1>
  <p class="lieu">{esc((lieu_court(b["quartier"]) + ", ") if b.get("quartier") else "")}{esc(lieu_court(b["commune"]))}, {'region of' if lang == 'en' else 'région de'} {esc(lieu_court(b["region"]))}</p>
  <p class="prix">{prix}</p>
  <p class="prix-secondaire">{prix_secondaire(b["price"])}{suffixe_mois}</p>
  <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:22px;">
    <p class="etat" style="margin:0;background:{'rgba(47,122,78,.12);color:#2F7A4E' if b["status"] == "Disponible" else 'rgba(226,162,44,.15);color:#8F6414'}">{esc(tr(b["status"], lang))}</p>
    {f'<p class="etat" style="margin:0;background:rgba(37,99,235,.12);color:#2854A6;">{esc(tr(b["statut_foncier"], lang))}</p>' if b.get("statut_foncier") and b["statut_foncier"] != "Non renseigné" else ''}
    {f'<p class="etat" style="margin:0;background:rgba(107,70,193,.12);color:#6B46C1;">{tr("Meublé" if b["meuble"] else "Non meublé", lang)}</p>' if b.get("meuble") is not None else ''}
    {f'<p class="etat" style="margin:0;background:rgba(180,83,9,.12);color:#B45309;">{tr("Disponible à partir du", lang)} {esc(b["date_disponibilite"])}</p>' if disponible_futur else ''}
  </div>

  {f'<h2>{tr("Photos", lang)}</h2>' + galerie if photos else ''}

  <h2>{tr("Caractéristiques", lang)}</h2>
  <ul class="faits">
    <li><b>{tr("Type", lang)}</b><span>{esc(tr(b["type"], lang))}</span></li>
    <li><b>{esc(tr(b["operation"], lang))}</b><span>{fcfa(b["price"])}{suffixe_mois}</span></li>
    <li><b>{tr("Superficie", lang)}</b><span>{esc(surface(b))}</span></li>
    <li><b>{tr("Référence", lang)}</b><span>{esc(b["ref"])}</span></li>
    {f'<li><b>{tr("Statut foncier", lang)}</b><span>{esc(tr(b["statut_foncier"], lang))}</span></li>' if b.get("statut_foncier") and b["statut_foncier"] != "Non renseigné" else ''}
    {"".join(f'<li><b>{esc(tr(k, lang))}</b><span>{esc(v)}</span></li>' for k, v in caracs)}
  </ul>

  {f'<h2>{tr("Description", lang)}</h2><p class="texte">' + esc(texte_description(b, lang)) + '</p>' if texte_description(b, lang) else ''}

  <section class="contact">
    <h2>{tr("Intéressé par ce bien ?", lang)}</h2>
    <p>{f'Reference {esc(b["ref"])} — visits by appointment in {esc(lieu_court(b["commune"]))}. We reply quickly.' if lang == 'en' else f'Référence {esc(b["ref"])} — visites sur rendez-vous à {esc(lieu_court(b["commune"]))}. Nous répondons rapidement.'}</p>
    <div class="actions">
      <a class="wa" href="{esc(wa)}" target="_blank" rel="noopener">{tr("Écrire sur WhatsApp", lang)}</a>
      <a class="tel" href="tel:{TEL}">{TEL_AFFICHE}</a>
    </div>

    <form class="contact-form" id="cf" novalidate>
      <label for="cf_name">{tr("Nom", lang)}</label>
      <input id="cf_name" placeholder="{tr("Votre nom", lang)}" autocomplete="name" required/>
      <label for="cf_contact">{tr("Téléphone ou email", lang)}</label>
      <input id="cf_contact" placeholder="{tr("Pour vous répondre", lang)}" autocomplete="tel" required/>
      <label for="cf_message">{tr("Message", lang)}</label>
      <textarea id="cf_message" placeholder="{tr("Votre question sur ce bien…", lang)}" required></textarea>
      <div class="hp-field" aria-hidden="true"><label for="cf_website">{tr("Site web", lang)}</label><input type="text" id="cf_website" name="website" tabindex="-1" autocomplete="off"/></div>
      <button type="submit" id="cfBtn">{tr("Envoyer le message", lang)}</button>
      <p class="cf-msg" id="cfMsg" role="alert"></p>
    </form>
  </section>

  {voisins_html}

  <a class="retour" href="./">{'← See all our properties in Dakar and Thiès' if lang == 'en' else '← Voir tous nos biens à Dakar et Thiès'}</a>
  <a class="retour" href="{prefixe}/{ACCUEIL}" style="margin-left:18px;">{'Search on the map' if lang == 'en' else 'Rechercher sur la carte'}</a>
</main>

<footer>
  {AGENCE} — {'land, houses, apartments and farmland in Dakar &amp; Thiès' if lang == 'en' else 'terrains, maisons, appartements et champs agricoles à Dakar &amp; Thiès'}<br>
  {TEL_AFFICHE} · {EMAIL} · {tr("visites sur rendez-vous", lang)}<br>
  <a href="{prefixe}/mentions-legales.html">{tr("Mentions légales", lang)}</a> · <a href="{prefixe}/confidentialite.html">{tr("Politique de confidentialité", lang)}</a><br>
  <span class="reg">© {date.today().year} {AGENCE} · NINEA {NINEA} · RCCM {RCCM}</span>
</footer>
<script>
// Écrit directement dans contact_messages via l'API REST, sans charger le
// SDK Supabase : cette page reste une fiche légère, pas l'application. La
// clé utilisée est la clé "publishable" — déjà publique dans le code de la
// vitrine, sans danger : la politique de sécurité de la table n'autorise que
// l'ajout (INSERT), jamais la lecture, et un déclencheur limite le nombre
// d'envois par appareil et par heure.
(function(){{
  var SUPABASE_URL = "{SUPABASE_URL}";
  var SUPABASE_KEY = "{SUPABASE_KEY}";
  var PROPERTY_ID = "{b['id']}";
  var form = document.getElementById('cf');
  if(!form) return;
  form.addEventListener('submit', function(ev){{
    ev.preventDefault();
    var msgEl = document.getElementById('cfMsg');
    var btn = document.getElementById('cfBtn');
    // Piège anti-bot : un humain ne remplit jamais ce champ invisible. On
    // simule un succès sans rien envoyer, pour ne pas signaler au robot
    // qu'il a été repéré.
    if(document.getElementById('cf_website').value.trim()){{
      form.innerHTML = '<p class="cf-msg ok">{tr("Message envoyé ! On vous recontacte rapidement.", lang)}</p>';
      return;
    }}
    var name = document.getElementById('cf_name').value.trim();
    var contact = document.getElementById('cf_contact').value.trim();
    var message = document.getElementById('cf_message').value.trim();
    msgEl.className = 'cf-msg';
    msgEl.textContent = '';
    if(!name || !contact || !message){{
      msgEl.className = 'cf-msg err';
      msgEl.textContent = '{tr("Merci de remplir tous les champs.", lang)}';
      return;
    }}
    btn.disabled = true;
    btn.textContent = '{tr("Envoi…", lang)}';
    fetch(SUPABASE_URL + '/rest/v1/contact_messages', {{
      method: 'POST',
      headers: {{
        apikey: SUPABASE_KEY,
        Authorization: 'Bearer ' + SUPABASE_KEY,
        'Content-Type': 'application/json',
        Prefer: 'return=minimal'
      }},
      body: JSON.stringify({{ property_id: PROPERTY_ID, name: name, contact: contact, message: message, is_read: false }})
    }}).then(function(res){{
      if(res.ok){{
        form.innerHTML = '<p class="cf-msg ok">{tr("Message envoyé ! On vous recontacte rapidement.", lang)}</p>';
        return;
      }}
      // Le plafond d'envoi (déclencheur enforce_submission_rate_limit) renvoie
      // un message déjà écrit pour un lecteur humain ; on l'affiche tel quel.
      return res.json().catch(function(){{ return {{}}; }}).then(function(corps){{
        msgEl.className = 'cf-msg err';
        msgEl.textContent = (corps && corps.message) ? corps.message
          : "{tr("Échec de l'envoi. Réessayez, ou écrivez-nous directement sur WhatsApp.", lang)}";
        btn.disabled = false;
        btn.textContent = '{tr("Envoyer le message", lang)}';
      }});
    }}).catch(function(){{
      msgEl.className = 'cf-msg err';
      msgEl.textContent = "{tr("Échec de l'envoi. Vérifiez votre connexion, ou écrivez-nous sur WhatsApp.", lang)}";
      btn.disabled = false;
      btn.textContent = '{tr("Envoyer le message", lang)}';
    }});
  }});
}})();
</script>
</body>
</html>
'''


def page_index(biens, par_bien, lang="fr"):
    """Page d'index statique de toutes les fiches.

    La vitrine construit sa liste en JavaScript : dans son code source, il n'y
    a aucun lien vers les fiches. Google ne peut donc les atteindre que par le
    sitemap, ce qui suffit à les découvrir mais ne dit rien de leur importance
    relative. Cette page, elle, est du HTML pur : un vrai chemin d'exploration
    qui part d'une adresse et mène aux 24 autres.

    Elle sert aussi les visiteurs : arrivés de Google sur une fiche, ils ont
    enfin une vue d'ensemble sans dépendre du chargement de la vitrine.
    """
    prefixe = "../.." if lang == "en" else ".."
    dossier = "bien/en" if lang == "en" else "bien"
    titre = (f"All our properties for sale and for rent in Dakar and Thiès | {AGENCE}"
             if lang == "en" else
             f"Tous nos biens à vendre et à louer à Dakar et Thiès | {AGENCE}")
    # Deux déclarations sur cette page : l'agence elle-même, qui n'était décrite
    # nulle part alors que c'est elle qu'on cherche en tapant « agence
    # immobilière Dakar » ; et la liste des annonces, qui dit à Google que cette
    # page est un catalogue et non un article.
    ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "RealEstateAgent",
                "name": AGENCE,
                "url": f"{SITE}/{ACCUEIL}",
                "telephone": TEL,
                "areaServed": [
                    {"@type": "AdministrativeArea", "name": "Dakar"},
                    {"@type": "AdministrativeArea", "name": "Thiès"},
                ],
                "address": {"@type": "PostalAddress", "addressCountry": "SN",
                            "addressRegion": "Dakar"},
                "knowsLanguage": ["fr", "en", "wo"],
            },
            {
                "@type": "ItemList",
                "name": "Properties available" if lang == "en" else "Biens disponibles",
                "numberOfItems": len(biens),
                "itemListElement": [
                    {"@type": "ListItem", "position": i + 1,
                     "url": url_fiche(b, lang),
                     "name": titre_bien(b, lang)}
                    for i, b in enumerate(biens)
                ],
            },
        ],
    }, ensure_ascii=False, indent=2)
    desc = (f"{len(biens)} plots of land, houses, apartments and farmland for sale "
            f"or rent in Dakar and Thiès. Price, size and photos for every "
            f"property. {AGENCE}, visits by appointment."
            if lang == "en" else
            f"{len(biens)} terrains, maisons, appartements et champs agricoles "
            f"à vendre ou à louer à Dakar et Thiès. Prix, superficie et photos "
            f"pour chaque bien. {AGENCE}, visites sur rendez-vous.")
    url = f"{SITE}/{dossier}/"

    sections = ""
    intitules = ((("Vente", "For sale"), ("Location", "For rent")) if lang == "en"
                 else (("Vente", "À vendre"), ("Location", "À louer")))
    for operation, intitule in intitules:
        lot = [b for b in biens if b["operation"] == operation]
        if not lot:
            continue
        # Les biens avec photo d'abord : une page qui s'ouvre sur onze
        # rectangles sans image donne l'impression d'un catalogue vide.
        lot.sort(key=lambda b: (not par_bien.get(b["id"]), lieu_court(b["region"]),
                                lieu_court(b["commune"]), b["type"]))
        cartes = "".join(vignette(b, par_bien.get(b["id"], []), lang) for b in lot)
        mot = ("propert" + ("ies" if len(lot) > 1 else "y")) if lang == "en" else \
              ("bien" + ("s" if len(lot) > 1 else ""))
        sections += (f'\n  <h2>{intitule} — {len(lot)} {mot}</h2>\n'
                     f'  <div class="voisins">{cartes}\n  </div>\n')

    return f'''<!DOCTYPE html>
<html lang="{'en' if lang == 'en' else 'fr'}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(titre)}</title>
<meta name="description" content="{esc(desc)}" />
<link rel="canonical" href="{url}" />
<link rel="alternate" hreflang="fr" href="{SITE}/bien/" />
<link rel="alternate" hreflang="en" href="{SITE}/bien/en/" />
<link rel="alternate" hreflang="x-default" href="{SITE}/bien/" />
{f'<meta name="google-site-verification" content="{GOOGLE_VERIFICATION}" />' if GOOGLE_VERIFICATION else ''}
{'<meta name="robots" content="noindex, follow" />' if EN_MAINTENANCE else '<meta name="robots" content="index, follow, max-image-preview:large" />'}
<meta property="og:type" content="website" />
<meta property="og:site_name" content="{AGENCE}" />
<meta property="og:locale" content="{'en_GB' if lang == 'en' else 'fr_FR'}" />
<meta property="og:title" content="{esc(titre)}" />
<meta property="og:description" content="{esc(desc)}" />
<meta property="og:url" content="{url}" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefixe}/commun.css" />
<style>
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
  .bandeau{{background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;}}
  .bandeau .lang{{color:rgba(255,255,255,.75);font-size:12.5px;font-weight:700;letter-spacing:.04em;border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:4px 11px;}}
  .bandeau .lang:hover{{color:var(--gold);border-color:var(--gold);}}
  .bandeau a{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a span{{color:var(--accent);}}
  main{{max-width:960px;margin:0 auto;padding:26px 20px 60px;}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;margin:0 0 10px;}}
  .intro{{color:var(--ink-soft);font-size:15px;line-height:1.65;margin:0 0 8px;max-width:60ch;}}
  h2{{font-family:'Manrope',sans-serif;font-size:17px;font-weight:800;margin:32px 0 14px;}}
{STYLE_VIGNETTES}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.9;}}
  footer a{{color:rgba(255,255,255,.72);text-decoration:none;font-weight:600;}}
  footer a:hover{{color:var(--gold);}}
  footer .reg{{opacity:.65;font-size:11.5px;}}
</style>
<script type="application/ld+json">
{ld}
</script>
</head>
<body>
<header class="bandeau">
  <a href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  <a class="lang" href="{'../' if lang == 'en' else 'en/'}" hreflang="{'fr' if lang == 'en' else 'en'}" lang="{'fr' if lang == 'en' else 'en'}">{'Français' if lang == 'en' else 'English'}</a>
</header>

<main>
  <h1>{'All our properties in Dakar and Thiès' if lang == 'en' else 'Tous nos biens à Dakar et Thiès'}</h1>
  <p class="intro">
    {f"{len(biens)} properties available: land, houses, apartments and farmland, for sale or rent across the Dakar and Thiès regions. Every listing shows the price, the size and photos of the property." if lang == 'en' else f"{len(biens)} biens disponibles : terrains, maisons, appartements et champs agricoles, à vendre ou à louer dans les régions de Dakar et de Thiès. Chaque fiche indique le prix, la superficie et les photos du bien."}
  </p>
{sections}
  <a class="retour" href="{prefixe}/{ACCUEIL}">{'← Search on the map' if lang == 'en' else '← Rechercher sur la carte'}</a>
</main>

<footer>
  {AGENCE} — {TEL_AFFICHE} · {EMAIL} · {tr("visites sur rendez-vous", lang)}<br>
  <a href="{prefixe}/mentions-legales.html">{tr("Mentions légales", lang)}</a> · <a href="{prefixe}/confidentialite.html">{tr("Politique de confidentialité", lang)}</a><br>
  <span class="reg">© {date.today().year} {AGENCE} · NINEA {NINEA} · RCCM {RCCM}</span>
</footer>
</body>
</html>
'''


# --- Guides -------------------------------------------------------------
# Pages de fond, généralistes, qui ne dépendent d'aucun bien : sans elles, le
# site ne peut se positionner que sur des requêtes transactionnelles très
# concurrentielles (« terrain à vendre Dakar »). Il reste absent des
# requêtes à forte intention où une agence gagne la confiance en amont
# (« comment vérifier un titre foncier au Sénégal ») — exactement les
# questions qui précèdent un achat, et que se pose particulièrement la
# diaspora.
#
# Contenu écrit à la main, comme le reste du site (pas de CMS). Chaque entrée
# porte sa propre date de publication : contrairement aux fiches de biens,
# rien ne change sous ces pages entre deux exécutions, inutile d'un mécanisme
# d'empreinte pour détecter un changement.
#
# Un seul guide au lancement, volontairement : en écrire cinq ou dix d'un
# coup aurait dilué le soin apporté à chacun, sur un sujet — le droit foncier
# — où une imprécision coûte cher à la crédibilité qu'on cherche justement à
# construire. Celui-ci reste général et renvoie vers un notaire pour tout ce
# qui touche à une transaction réelle : ce n'est pas un avis juridique.
GUIDES = [
    {
        "slug": "verifier-titre-foncier-senegal",
        "titre": "Titre foncier, bail ou délibération : comment vérifier le statut d'un terrain au Sénégal",
        "description": "Titre foncier, bail, délibération : ce que signifie chaque statut, "
                        "pourquoi la différence compte avant d'acheter, et comment le vérifier "
                        "concrètement. Guide à jour pour un achat de terrain au Sénégal.",
        "date_publication": "2026-08-02",
        "corps": """
    <p>Avant le prix, avant la superficie, la première question à se poser devant un terrain
    au Sénégal est juridique&nbsp;: <strong>sur quel statut foncier repose-t-il&nbsp;?</strong>
    C'est elle qui détermine si vous achetez une propriété pleine et transmissible, ou un droit
    plus fragile, parfois contestable. C'est aussi, de loin, la première source de litiges
    immobiliers dans le pays.</p>

    <h2>Les trois statuts que vous rencontrerez</h2>

    <p><strong>Le titre foncier (TF)</strong> est le statut le plus sûr&nbsp;: la parcelle est
    immatriculée au nom de son propriétaire à la Conservation de la Propriété Foncière. Ce
    titre est opposable à tous, transmissible, et peut servir de garantie pour un prêt. C'est
    l'équivalent d'un acte de propriété définitif.</p>

    <p><strong>Le bail</strong> porte sur un terrain qui appartient à l'État ou à une commune,
    et que son titulaire a le droit d'occuper et d'exploiter pour une durée déterminée — parfois
    longue, mais jamais illimitée. Le bailleur reste juridiquement propriétaire du sol. Un bail
    peut, sous certaines conditions, être transformé en titre foncier, mais ce n'en est pas un
    tant que la conversion n'a pas eu lieu.</p>

    <p><strong>La délibération</strong> est une décision d'affectation prise par un conseil
    municipal, qui attribue une parcelle du domaine national à un particulier. C'est le statut
    le plus courant sur les terrains ruraux ou communautaires, et souvent la première étape
    avant une éventuelle immatriculation. Une délibération n'est <strong>pas</strong> un titre
    de propriété&nbsp;: elle peut, dans certains cas, être remise en cause par la commune qui
    l'a délivrée, en particulier si le terrain n'est pas mis en valeur dans les délais prévus.</p>

    <h2>Pourquoi cette différence change tout pour un acheteur</h2>

    <p>Acheter sur la base d'une délibération n'est pas nécessairement une erreur — une grande
    partie du foncier rural sénégalais fonctionne ainsi, et beaucoup de délibérations sont
    parfaitement régulières. Mais le risque n'est pas le même que pour un titre foncier&nbsp;:
    il faut savoir <em>ce que l'on achète</em>, l'accepter en connaissance de cause, et adapter
    sa prudence — et éventuellement son prix — en conséquence. Le problème n'est pas le statut
    en lui-même&nbsp;: c'est de l'apprendre après la signature.</p>

    <h2>Comment vérifier, concrètement</h2>

    <ul>
      <li><strong>Demandez le document original</strong> — titre foncier, bail ou délibération
      — et le nom exact qui y figure. Un vendeur sérieux ne s'y refuse jamais.</li>
      <li><strong>Vérifiez la correspondance</strong> entre la parcelle décrite sur le document
      (numéro, superficie, limites) et le terrain réellement visité. Un bornage par un géomètre
      agréé lève le doute.</li>
      <li><strong>Faites confirmer l'inscription</strong> d'un titre foncier auprès de la
      Conservation de la Propriété Foncière et des Droits Fonciers dont dépend la parcelle, et
      l'absence d'hypothèque ou d'opposition en cours.</li>
      <li><strong>Passez par un notaire</strong> pour l'acte de vente. Une vente « sous seing
      privé » (un simple papier signé entre particuliers) sur un titre foncier n'a pas la même
      valeur juridique qu'un acte notarié, et ne suffit pas à vous rendre propriétaire.</li>
      <li><strong>Pour une délibération</strong>, vérifiez qu'elle a bien été délivrée par la
      commune compétente sur ce terrain, et depuis quand — une délibération ancienne, mise en
      valeur et non contestée, est un signal plus rassurant qu'une délibération toute récente.</li>
    </ul>

    <h2>Les signaux qui doivent alerter</h2>

    <ul>
      <li>Un vendeur qui presse la transaction ou refuse de montrer les documents originaux.</li>
      <li>Un prix nettement inférieur à celui du marché environnant, sans explication claire.</li>
      <li>Une superficie annoncée qui ne correspond pas à celle inscrite sur le document.</li>
      <li>Plusieurs personnes différentes qui se présentent comme vendeur du même terrain.</li>
    </ul>

    <h2>Ce que PAB Immo vérifie avant de publier une annonce</h2>

    <p>Chaque bien publié sur ce site porte un statut foncier déclaré, visible directement sur
    sa fiche. Les annonces marquées « Annonce vérifiée » ont fait l'objet d'un contrôle des
    documents et de l'existence réelle du bien avant publication. Ce badge ne remplace pas les
    vérifications qui restent les vôtres au moment de l'achat — il réduit le nombre de biens sur
    lesquels vous avez à les mener.</p>

    <h2>Questions fréquentes</h2>

    <p><strong>Un bail est-il moins bien qu'un titre foncier&nbsp;?</strong><br>
    Ce n'est pas « moins bien », c'est différent&nbsp;: un bail donne un droit d'occupation et
    d'exploitation limité dans le temps, pas une propriété pleine. Pour un usage personnel sur
    une durée raisonnable, il peut parfaitement convenir&nbsp;; pour un investissement de long
    terme destiné à être transmis, un titre foncier reste préférable.</p>

    <p><strong>Peut-on transformer une délibération en titre foncier&nbsp;?</strong><br>
    Oui, c'est une trajectoire courante, mais elle suit une procédure et des délais propres à
    chaque situation. Elle n'est ni automatique ni garantie&nbsp;: à vérifier avec un notaire
    ou directement auprès des services fonciers avant de compter dessus.</p>

    <p><strong>Un acheteur vivant à l'étranger peut-il vérifier tout cela à distance&nbsp;?</strong><br>
    En grande partie, oui, par procuration notariée confiée à une personne de confiance ou à un
    notaire sur place. C'est justement dans ce cas — acheter sans pouvoir se déplacer — que les
    vérifications ci-dessus comptent le plus&nbsp;: elles se font normalement en personne, et
    leur absence est plus difficile à repérer à distance.</p>

    <p class="avert">Cet article donne des repères généraux&nbsp;; ce n'est pas un avis
    juridique et il ne remplace pas les vérifications d'un notaire pour une transaction réelle.
    Le droit foncier sénégalais évolue&nbsp;; en cas de doute, consultez un professionnel avant
    de vous engager.</p>
""",
        "titre_en": "Freehold Title, Lease, or Council Deliberation: How to Verify a Plot's Legal Status in Senegal",
        "description_en": "Freehold title, lease, council deliberation: what each status means, "
                           "why the difference matters before you buy, and how to verify it in "
                           "practice. An up-to-date guide for buying land in Senegal.",
        "corps_en": """
    <p>Before the price, before the surface area, the first question worth asking about a plot
    in Senegal is a legal one: <strong>what land title status does it rest on?</strong>
    That question decides whether you're buying full, transferable ownership, or a more fragile,
    sometimes contestable right. It is also, by far, the leading source of property disputes in
    the country.</p>

    <h2>The three statuses you will encounter</h2>

    <p><strong>Freehold title (titre foncier, TF)</strong> is the most secure status: the
    plot is registered in its owner's name at the Land Registry (Conservation de la Propriété
    Foncière). This title is enforceable against everyone, transferable, and can serve as
    collateral for a loan. It is the equivalent of a definitive deed of ownership.</p>

    <p><strong>A lease (bail)</strong> applies to land that belongs to the State or a
    municipality, which its holder has the right to occupy and use for a set period — sometimes
    long, but never unlimited. The lessor remains the legal owner of the land. Under certain
    conditions a lease can be converted into freehold title, but it is not one until that
    conversion has actually taken place.</p>

    <p><strong>A council deliberation (délibération)</strong> is an allocation decision made by a
    municipal council, granting a parcel of national land to an individual. It is the most common
    status on rural or community land, and often the first step before eventual registration. A
    deliberation is <strong>not</strong> a title of ownership: it can, in some cases, be
    revoked by the municipality that issued it, particularly if the land is not developed within
    the required timeframe.</p>

    <h2>Why this difference changes everything for a buyer</h2>

    <p>Buying on the basis of a deliberation is not necessarily a mistake — a large share of
    Senegal's rural land operates this way, and many deliberations are perfectly regular. But the
    risk is not the same as with freehold title: you need to know <em>what you are
    buying</em>, accept it knowingly, and adjust your caution — and possibly your price —
    accordingly. The problem isn't the status itself: it's finding out about it after
    signing.</p>

    <h2>How to verify it, in practice</h2>

    <ul>
      <li><strong>Ask for the original document</strong> — freehold title, lease, or
      deliberation — and the exact name it bears. A serious seller never refuses this.</li>
      <li><strong>Check that it matches</strong> the plot actually visited — parcel number,
      surface area, boundaries as described on the document. A survey by a licensed surveyor
      removes any doubt.</li>
      <li><strong>Confirm the registration</strong> of a freehold title with the Land Registry
      office responsible for that parcel, and check for the absence of any mortgage or pending
      dispute.</li>
      <li><strong>Go through a notary</strong> for the deed of sale. A private agreement (a
      simple paper signed between individuals) over land held under freehold title does not carry
      the same legal weight as a notarized deed, and is not enough to make you the owner.</li>
      <li><strong>For a deliberation</strong>, verify that it was indeed issued by the
      municipality with authority over that land, and how long ago — an older deliberation,
      developed and uncontested, is a more reassuring signal than a very recent one.</li>
    </ul>

    <h2>Warning signs</h2>

    <ul>
      <li>A seller who rushes the transaction or refuses to show original documents.</li>
      <li>A price noticeably below the surrounding market, with no clear explanation.</li>
      <li>An advertised surface area that doesn't match the one on the document.</li>
      <li>Several different people presenting themselves as the seller of the same plot.</li>
    </ul>

    <h2>What PAB Immo checks before publishing a listing</h2>

    <p>Every property published on this site carries a declared land title status, visible
    directly on its listing page. Listings marked "Verified listing" have had their documents and
    the property's actual existence checked before publication. This badge doesn't replace the
    checks that remain yours to make at the time of purchase — it reduces the number of
    properties you need to run them on.</p>

    <h2>Frequently asked questions</h2>

    <p><strong>Is a lease worse than freehold title?</strong><br>
    It isn't "worse", it's different: a lease grants a right to occupy and use the land for
    a limited time, not full ownership. For personal use over a reasonable period, it can suit you
    perfectly well; for a long-term investment meant to be passed on, freehold title remains
    preferable.</p>

    <p><strong>Can a deliberation be converted into freehold title?</strong><br>
    Yes, that's a common path, but it follows a procedure and timeline specific to each situation.
    It is neither automatic nor guaranteed: check with a notary or directly with the land
    services before counting on it.</p>

    <p><strong>Can a buyer living abroad verify all of this remotely?</strong><br>
    For the most part, yes, through a notarized power of attorney given to a trusted person or a
    notary on the ground. This is precisely the case — buying without being able to travel —
    where the checks above matter most: they are normally done in person, and their absence
    is harder to spot from a distance.</p>

    <p class="avert">This article provides general guidance; it is not legal advice and
    does not replace a notary's checks for an actual transaction. Senegalese land law evolves;
    if in doubt, consult a professional before committing.</p>
""",
    },
    {
        "slug": "acheter-terrain-senegal-depuis-etranger",
        "titre": "Acheter un terrain au Sénégal depuis l'étranger : procuration, notaire, vérifications",
        "description": "Vivre en France, en Italie ou ailleurs n'empêche pas d'acheter un "
                        "terrain au Sénégal. Voici comment fonctionne la procuration, ce que "
                        "vérifie un notaire, et les précautions propres à un achat à distance.",
        "date_publication": "2026-08-05",
        "corps": """
    <p>Une grande partie des acheteurs de terrain à Dakar et à Thiès ne vit pas au Sénégal.
    C'est une situation ordinaire, pas un obstacle — mais elle change une chose&nbsp;: les
    vérifications qui, sur place, se font naturellement en marchant sur le terrain, doivent être
    organisées différemment. Ce guide explique comment.</p>

    <h2>La procuration&nbsp;: acheter sans être présent</h2>

    <p>La procuration (ou « mandat ») est l'outil central d'un achat à distance. Elle permet de
    donner, par un acte notarié, le pouvoir d'agir en votre nom à une personne de confiance —
    souvent un proche sur place, ou directement un notaire. Trois points à retenir&nbsp;:</p>

    <ul>
      <li><strong>Elle se signe devant notaire</strong>, soit au Sénégal si vous vous y trouvez
      ponctuellement, soit devant un notaire ou l'ambassade/le consulat du Sénégal dans votre
      pays de résidence, qui la transmet ensuite au Sénégal.</li>
      <li><strong>Son étendue doit rester précise</strong>&nbsp;: une procuration limitée à
      « signer l'acte d'achat de la parcelle X, pour un prix maximum de Y » protège bien mieux
      qu'un mandat général et permanent, qui reste utilisable bien après la transaction pour
      laquelle vous l'aviez prévu.</li>
      <li><strong>Elle a une durée</strong>&nbsp;: fixez-en une, et exigez sa révocation
      formelle une fois la transaction conclue.</li>
    </ul>

    <h2>Le rôle du notaire</h2>

    <p>Au Sénégal comme en France, le notaire n'est pas un simple témoin de la signature&nbsp;:
    il vérifie l'identité des parties, l'origine et le statut du bien (voir notre
    <a href="verifier-titre-foncier-senegal.html">guide sur le titre foncier</a>), l'absence
    d'hypothèque ou d'opposition, et rédige l'acte qui vous rend juridiquement propriétaire.
    C'est lui — pas l'agence, pas le vendeur — qui porte la responsabilité de ces vérifications.
    Pour un achat à distance, son rôle est encore plus central&nbsp;: il devient vos yeux sur
    place au moment décisif.</p>

    <h2>Ce qu'il faut vérifier avant d'envoyer le moindre franc</h2>

    <ul>
      <li>Le statut foncier du terrain (titre foncier, bail ou délibération) et sa
      correspondance avec la parcelle réellement visée — par photo, vidéo, ou un geomètre
      mandaté sur place si le montant le justifie.</li>
      <li>L'identité du vendeur, comparée au nom inscrit sur le document de propriété.</li>
      <li>L'existence d'un notaire clairement identifié, joignable directement — pas seulement
      « connu » du vendeur ou de l'intermédiaire.</li>
      <li>Le taux de change utilisé si vous raisonnez en euros ou en dollars&nbsp;: le FCFA est
      arrimé à l'euro à un taux fixe (655,957 F CFA pour 1&nbsp;€), donc jamais soumis aux
      variations qui touchent d'autres devises — un repère utile pour convertir vous-même un
      prix affiché en FCFA.</li>
    </ul>

    <h2>Les précautions propres à l'achat à distance</h2>

    <ul>
      <li><strong>Ne jamais transférer de fonds avant l'acte notarié</strong>, même face à
      l'urgence apparente d'une « offre limitée dans le temps » — une pression classique.</li>
      <li><strong>Privilégier un virement bancaire traçable</strong> plutôt qu'un transfert
      d'argent informel, y compris pour un acompte.</li>
      <li><strong>Demander des preuves visuelles récentes</strong> du terrain (photo datée,
      appel vidéo sur place) plutôt que de se fier uniquement aux photos de l'annonce.</li>
      <li><strong>Se méfier d'un intermédiaire qui décourage le contact direct</strong> avec le
      notaire ou qui propose de « tout gérer » sans jamais vous mettre en relation avec lui.</li>
    </ul>

    <h2>Ce que PAB Immo fait pour les acheteurs à distance</h2>

    <p>Chaque annonce publiée porte un statut foncier déclaré et, pour les biens marqués
    « Annonce vérifiée », un contrôle préalable des documents et de l'existence réelle du
    terrain. Nous répondons par WhatsApp et par téléphone, ce qui couvre la plupart des fuseaux
    horaires sans qu'il soit nécessaire de se déplacer avant d'être prêt à conclure.</p>

    <h2>Questions fréquentes</h2>

    <p><strong>Faut-il obligatoirement passer par un notaire sénégalais&nbsp;?</strong><br>
    Pour l'acte de vente lui-même, oui&nbsp;: c'est lui qui a compétence sur un bien situé au
    Sénégal. Un notaire à l'étranger peut en revanche authentifier la procuration qui permettra
    à votre mandataire d'agir sur place.</p>

    <p><strong>Combien de temps prend une procuration depuis l'étranger&nbsp;?</strong><br>
    Cela dépend du pays et du mode utilisé (notaire local ou consulat), et les délais varient
    trop pour être donnés ici de façon fiable&nbsp;: demandez un délai précis directement à
    l'organisme qui l'établira.</p>

    <p><strong>Peut-on financer l'achat depuis un compte à l'étranger&nbsp;?</strong><br>
    Oui, par virement bancaire international vers un compte au Sénégal — le vôtre ou, une fois
    l'acte prêt, celui indiqué par le notaire. Passer par un compte personnel plutôt que par un
    intermédiaire non identifié reste la règle la plus sûre.</p>

    <p class="avert">Cet article donne des repères généraux&nbsp;; ce n'est pas un avis
    juridique. Les démarches de procuration varient selon votre pays de résidence&nbsp;:
    vérifiez-les auprès d'un notaire ou du consulat du Sénégal compétent avant de vous engager.</p>
""",
        "titre_en": "Buying Land in Senegal from Abroad: Power of Attorney, the Notary's Role, Due Diligence",
        "description_en": "Living in France, Italy, or elsewhere doesn't stop you from buying "
                           "land in Senegal. Here's how power of attorney works, what a notary "
                           "checks, and the precautions specific to a remote purchase.",
        "corps_en": """
    <p>A large share of land buyers in Dakar and Thiès don't live in Senegal. That's an ordinary
    situation, not an obstacle — but it changes one thing: the checks that, on the ground,
    happen naturally by walking the plot, need to be organized differently. This guide explains
    how.</p>

    <h2>Power of attorney: buying without being present</h2>

    <p>A power of attorney (or "mandate") is the central tool for a remote purchase. Through a
    notarized deed, it lets you give a trusted person — often a relative on the ground, or a
    notary directly — the authority to act on your behalf. Three points to keep in mind:</p>

    <ul>
      <li><strong>It is signed before a notary</strong>, either in Senegal if you happen to be
      there, or before a notary or the Senegalese embassy/consulate in your country of residence,
      which then forwards it to Senegal.</li>
      <li><strong>Its scope should stay precise</strong>: a power of attorney limited to
      "sign the deed of purchase for plot X, up to a maximum price of Y" protects you far better
      than a broad, standing mandate, which remains usable long after the transaction it was
      meant for.</li>
      <li><strong>It has a duration</strong>: set one, and require its formal revocation
      once the transaction is complete.</li>
    </ul>

    <h2>The notary's role</h2>

    <p>In Senegal as in France, the notary is not a mere witness to the signature: they
    verify the parties' identity, the property's origin and status (see our
    <a href="verifier-titre-foncier-senegal.html">guide to land title status</a>), the absence of
    any mortgage or dispute, and draft the deed that legally makes you the owner. It is the
    notary — not the agency, not the seller — who bears responsibility for these checks. For a
    remote purchase, their role becomes even more central: they become your eyes on the
    ground at the decisive moment.</p>

    <h2>What to check before sending a single franc</h2>

    <ul>
      <li>The plot's land title status (freehold title, lease, or deliberation) and whether it
      matches the plot actually seen — by photo, video, or a surveyor commissioned on site if the
      amount justifies it.</li>
      <li>The seller's identity, checked against the name on the property document.</li>
      <li>The existence of a clearly identified notary, reachable directly — not merely
      "known" to the seller or intermediary.</li>
      <li>The exchange rate, if you're thinking in euros or dollars: the FCFA is pegged to
      the euro at a fixed rate (655.957 F CFA to 1&nbsp;€), so it is never subject to the swings
      that affect other currencies — a useful anchor for converting a price shown in FCFA
      yourself.</li>
    </ul>

    <h2>Precautions specific to a remote purchase</h2>

    <ul>
      <li><strong>Never transfer funds before the notarized deed</strong>, even under the
      apparent urgency of a "limited-time offer" — a classic pressure tactic.</li>
      <li><strong>Favor a traceable bank transfer</strong> over an informal money transfer, even
      for a deposit.</li>
      <li><strong>Ask for recent visual proof</strong> of the land (a dated photo, a video call on
      site) rather than relying solely on the listing's photos.</li>
      <li><strong>Be wary of an intermediary who discourages direct contact</strong> with the
      notary, or who offers to "handle everything" without ever putting you in touch with one.</li>
    </ul>

    <h2>What PAB Immo does for remote buyers</h2>

    <p>Every listing we publish carries a declared land title status and, for properties marked
    "Verified listing", a prior check of the documents and the land's actual existence. We
    respond on WhatsApp and by phone, which covers most time zones without requiring you to
    travel before you're ready to close.</p>

    <h2>Frequently asked questions</h2>

    <p><strong>Must the deed be signed by a Senegalese notary?</strong><br>
    For the deed of sale itself, yes: they have jurisdiction over property located in
    Senegal. A notary abroad can, however, authenticate the power of attorney that will let your
    representative act on the ground.</p>

    <p><strong>How long does a power of attorney take from abroad?</strong><br>
    It depends on the country and the method used (local notary or consulate), and timelines vary
    too much to give a reliable figure here: ask the office that will issue it for a precise
    estimate.</p>

    <p><strong>Can the purchase be funded from an account abroad?</strong><br>
    Yes, by international bank transfer to an account in Senegal — either yours, or, once the
    deed is ready, the one indicated by the notary. Going through a personal account rather than
    an unidentified intermediary remains the safest rule.</p>

    <p class="avert">This article provides general guidance; it is not legal advice. Power
    of attorney procedures vary by country of residence: check them with a notary or the
    relevant Senegalese consulate before committing.</p>
""",
    },
]


def page_guide(g, lang="fr"):
    """Rend une page de guide, en français ou en anglais. Même habillage que
    les fiches (bandeau, commun.css, pied de page) : un même site, pas deux.

    L'anglais vit dans guides/en/ (un niveau de plus vers la racine du site),
    plutôt qu'un paramètre ?lang= comme la vitrine : ce sont des pages
    statiques indépendantes, jamais retraduites automatiquement (contenu à
    caractère juridique — voir la décision prise pour l'étape 3 du
    multilingue), donc chacune mérite sa propre URL indexable par Google."""
    en = lang == "en"
    prefixe = "../.." if en else ".."
    titre = g["titre_en"] if en else g["titre"]
    description = g["description_en"] if en else g["description"]
    corps = g["corps_en"] if en else g["corps"]
    dossier = "guides/en" if en else "guides"
    url = f"{SITE}/{dossier}/{g['slug']}.html"
    # L'autre langue vit dans le dossier voisin, sous le même nom de fichier :
    # depuis guides/en/, ../<slug>.html ; depuis guides/, en/<slug>.html.
    lien_autre_langue = f"../{g['slug']}.html" if en else f"en/{g['slug']}.html"
    url_fr = f"{SITE}/guides/{g['slug']}.html"
    url_en = f"{SITE}/guides/en/{g['slug']}.html"
    # json.dumps, pas esc() : esc() échappe pour du HTML (& -> &amp;), mais le
    # contenu d'un <script> n'est jamais décodé comme le reste du HTML — un
    # titre qui contiendrait un jour un « & » ou un guillemet se retrouverait
    # donc mal encodé dans les données structurées sans que rien ne le signale.
    ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": titre,
        "description": description,
        "datePublished": g["date_publication"],
        "inLanguage": "en" if en else "fr",
        "author": {"@type": "Organization", "name": AGENCE},
        "publisher": {"@type": "Organization", "name": AGENCE},
        "mainEntityOfPage": url,
    }, ensure_ascii=False, indent=2)
    return f'''<!DOCTYPE html>
<html lang="{"en" if en else "fr"}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(titre)} | {AGENCE}</title>
<meta name="description" content="{esc(description)}" />
<link rel="canonical" href="{url}" />
<link rel="alternate" hreflang="fr" href="{url_fr}" />
<link rel="alternate" hreflang="en" href="{url_en}" />
{'<meta name="robots" content="noindex, follow" />' if EN_MAINTENANCE else '<meta name="robots" content="index, follow" />'}
<meta property="og:type" content="article" />
<meta property="og:site_name" content="{AGENCE}" />
<meta property="og:locale" content="{"en_US" if en else "fr_FR"}" />
<meta property="og:title" content="{esc(titre)}" />
<meta property="og:description" content="{esc(description)}" />
<meta property="og:url" content="{url}" />
<meta name="twitter:card" content="summary" />
<meta name="twitter:title" content="{esc(titre)}" />
<meta name="twitter:description" content="{esc(description)}" />
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefixe}/commun.css" />
<style>
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
  .bandeau{{background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;}}
  .bandeau a.marque{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a.marque span{{color:var(--accent);}}
  .bandeau a.langue{{color:rgba(255,255,255,0.72);text-decoration:underline;font-size:12.5px;font-weight:600;}}
  .bandeau a.langue:hover{{color:#fff;}}
  main{{max-width:720px;margin:0 auto;padding:26px 20px 60px;}}
  .fil{{font-size:12.5px;color:var(--ink-soft);margin:0 0 16px;}}
  .fil a{{color:var(--ink-soft);}}
  .eyebrow{{font-family:'Manrope',sans-serif;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--gold);margin:0 0 8px;}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;line-height:1.15;margin:0 0 10px;}}
  .date{{color:var(--ink-soft);font-size:13px;margin:0 0 26px;}}
  main p{{font-size:15.5px;line-height:1.75;margin:0 0 18px;}}
  main h2{{font-family:'Manrope',sans-serif;font-size:19px;font-weight:800;margin:34px 0 12px;}}
  main ul{{margin:0 0 18px;padding-left:20px;}}
  main ul li{{font-size:15.5px;line-height:1.7;margin-bottom:8px;}}
  main strong{{font-weight:700;}}
  .avert{{background:var(--surface-alt);border-left:3px solid var(--gold);border-radius:0 var(--radius-md) var(--radius-md) 0;padding:14px 16px;font-size:13.5px;color:var(--ink-soft);margin-top:30px;}}
  .contact{{margin-top:36px;background:linear-gradient(140deg,var(--night),var(--night-2));border-radius:var(--radius-lg);padding:24px;}}
  .contact p{{color:rgba(255,255,255,.74);font-size:14px;margin:0 0 16px;line-height:1.6;}}
  .contact h2{{color:#fff;margin:0 0 6px;}}
  .actions{{display:flex;gap:10px;flex-wrap:wrap;}}
  .actions a{{flex:1 1 200px;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;border-radius:999px;font-weight:700;font-size:14px;text-decoration:none;}}
  .wa{{background:#25D366;color:#fff;}} .tel{{background:var(--accent);color:#1E1607;}}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.9;}}
  footer a{{color:rgba(255,255,255,.72);text-decoration:none;font-weight:600;}}
  footer a:hover{{color:var(--gold);}}
  footer .reg{{opacity:.65;font-size:11.5px;}}
</style>
<script type="application/ld+json">
{ld}
</script>
</head>
<body>
<header class="bandeau">
  <a class="marque" href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  <a class="langue" href="{lien_autre_langue}">{"Lire en français" if en else "Read in English"}</a>
</header>

<main>
  <nav class="fil" aria-label="{"Breadcrumb" if en else "Fil d'Ariane"}">
    <a href="./">Guides</a> › {esc(titre)}
  </nav>

  <p class="eyebrow">Guide</p>
  <h1>{esc(titre)}</h1>
  <p class="date">{"Published on" if en else "Publié le"} {esc(g["date_publication"])}</p>

  {corps}

  <section class="contact">
    <h2>{"Have a question about a property?" if en else "Une question sur un bien précis&nbsp;?"}</h2>
    <p>{"We reply quickly, on WhatsApp or by phone." if en else "Nous répondons rapidement, par WhatsApp ou par téléphone."}</p>
    <div class="actions">
      <a class="wa" href="https://wa.me/{TEL.lstrip('+')}" target="_blank" rel="noopener">{"Message us on WhatsApp" if en else "Écrire sur WhatsApp"}</a>
      <a class="tel" href="tel:{TEL}">{TEL_AFFICHE}</a>
    </div>
  </section>

  <a class="retour" href="./">{"← All guides" if en else "← Tous les guides"}</a>
  <a class="retour" href="{prefixe}/{ACCUEIL}" style="margin-left:18px;">{"See available properties" if en else "Voir les biens disponibles"}</a>
</main>

<footer>
  {AGENCE} — {TEL_AFFICHE} · {EMAIL} · {"visits by appointment" if en else "visites sur rendez-vous"}<br>
  <a href="{prefixe}/mentions-legales.html">{"Legal notice" if en else "Mentions légales"}</a> · <a href="{prefixe}/confidentialite.html">{"Privacy policy" if en else "Politique de confidentialité"}</a><br>
  <span class="reg">© {date.today().year} {AGENCE} · NINEA {NINEA} · RCCM {RCCM}</span>
</footer>
</body>
</html>
'''


def page_guides_index(guides, lang="fr"):
    """Page d'index des guides — le point d'entrée lié depuis le pied de page
    de la vitrine, et la seule page de ce dossier que Google découvre sans
    passer par le sitemap. Même choix de dossier que page_guide() : guides/en/
    pour l'anglais."""
    en = lang == "en"
    prefixe = "../.." if en else ".."
    dossier = "guides/en" if en else "guides"
    url = f"{SITE}/{dossier}/"
    lien_autre_langue = "../" if en else "en/"
    cartes = "".join(f'''
    <a class="carte-guide" href="{g['slug']}.html">
      <span class="eyebrow">Guide</span>
      <h2>{esc(g["titre_en"] if en else g["titre"])}</h2>
      <p>{esc(g["description_en"] if en else g["description"])}</p>
    </a>''' for g in guides)
    titre_page = "Guides & tips" if en else "Guides et conseils"
    intro = ("What's worth knowing before you buy, sell, or rent in Dakar and Thiès."
             if en else
             "Ce qu'il est utile de savoir avant d'acheter, de vendre ou de louer à Dakar et à Thiès.")
    return f'''<!DOCTYPE html>
<html lang="{"en" if en else "fr"}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{titre_page} | {AGENCE}</title>
<meta name="description" content="{'Practical advice for buying, selling, or renting property in Dakar and Thiès: land title status, procedures, buying from abroad.' if en else 'Conseils pratiques pour acheter, vendre ou louer un bien à Dakar et Thiès : statut foncier, démarches, achat à distance.'}" />
<link rel="canonical" href="{url}" />
<link rel="alternate" hreflang="fr" href="{SITE}/guides/" />
<link rel="alternate" hreflang="en" href="{SITE}/guides/en/" />
{'<meta name="robots" content="noindex, follow" />' if EN_MAINTENANCE else '<meta name="robots" content="index, follow" />'}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefixe}/commun.css" />
<style>
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:'Inter',sans-serif;-webkit-font-smoothing:antialiased;}}
  .bandeau{{background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;}}
  .bandeau a.marque{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a.marque span{{color:var(--accent);}}
  .bandeau a.langue{{color:rgba(255,255,255,0.72);text-decoration:underline;font-size:12.5px;font-weight:600;}}
  .bandeau a.langue:hover{{color:#fff;}}
  main{{max-width:900px;margin:0 auto;padding:34px 20px 60px;}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;margin:0 0 8px;}}
  main > p{{color:var(--ink-soft);font-size:15px;margin:0 0 30px;}}
  .grille-guides{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:18px;}}
  .carte-guide{{display:block;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:20px;text-decoration:none;color:inherit;transition:box-shadow .2s, transform .2s;}}
  .carte-guide:hover{{box-shadow:var(--shadow-lg);transform:translateY(-2px);}}
  .eyebrow{{font-family:'Manrope',sans-serif;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--gold);}}
  .carte-guide h2{{font-family:'Manrope',sans-serif;font-size:17px;font-weight:800;margin:8px 0 8px;line-height:1.3;}}
  .carte-guide p{{font-size:13.5px;color:var(--ink-soft);line-height:1.6;margin:0;}}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.9;}}
  footer a{{color:rgba(255,255,255,.72);text-decoration:none;font-weight:600;}}
  footer .reg{{opacity:.65;font-size:11.5px;}}
</style>
</head>
<body>
<header class="bandeau">
  <a class="marque" href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  <a class="langue" href="{lien_autre_langue}">{"Lire en français" if en else "Read in English"}</a>
</header>

<main>
  <h1>{titre_page}</h1>
  <p>{intro}</p>
  <div class="grille-guides">{cartes}
  </div>
  <a class="retour" href="{prefixe}/{ACCUEIL}">{"← See available properties" if en else "← Voir les biens disponibles"}</a>
</main>

<footer>
  {AGENCE} — {TEL_AFFICHE} · {EMAIL} · {"visits by appointment" if en else "visites sur rendez-vous"}<br>
  <a href="{prefixe}/mentions-legales.html">{"Legal notice" if en else "Mentions légales"}</a> · <a href="{prefixe}/confidentialite.html">{"Privacy policy" if en else "Politique de confidentialité"}</a><br>
  <span class="reg">© {date.today().year} {AGENCE} · NINEA {NINEA} · RCCM {RCCM}</span>
</footer>
</body>
</html>
'''


# --- Programme --------------------------------------------------------------

def prechauffer_traductions(biens):
    """Demande la traduction anglaise des descriptions qui n'en ont pas encore.

    La fonction Edge traduire-description met sa réponse en cache dans
    properties.description_en. Elle est normalement déclenchée par le premier
    visiteur anglophone qui ouvre la fiche — mais une page statique n'a pas de
    visiteur : sans ce préchauffage, la fiche anglaise d'un bien fraîchement
    saisi paraîtrait sans description tant que personne ne l'aurait consultée
    sur la vitrine.

    Plafonné à TRADUCTIONS_PAR_PASSAGE pour rester sous la limite de la
    fonction (10 par heure et par IP). L'action tournant tous les quarts
    d'heure, le catalogue se remplit tout seul en une à deux heures.

    Tolérant à l'échec : une traduction qui ne vient pas laisse simplement la
    fiche anglaise sans paragraphe de description ce tour-ci. Rien ne casse,
    et le passage suivant réessaiera.
    """
    manquantes = [b for b in biens
                  if (b.get("description") or "").strip()
                  and not (b.get("description_en") or "").strip()]
    if not manquantes:
        return 0

    faites = 0
    for b in manquantes[:TRADUCTIONS_PAR_PASSAGE]:
        corps = json.dumps({"ref": b["ref"]}).encode("utf-8")
        req = urllib.request.Request(
            f"{SUPABASE_URL}/functions/v1/traduire-description",
            data=corps, method="POST",
            headers={"apikey": SUPABASE_KEY,
                     "Authorization": f"Bearer {SUPABASE_KEY}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                traduit = json.loads(r.read().decode("utf-8")).get("description_en")
            if traduit:
                b["description_en"] = traduit
                faites += 1
        except Exception as e:
            print(f"    traduction de {b['ref']} remise à plus tard ({str(e)[:60]})")
    reste = len(manquantes) - faites
    print(f"  {faites} description(s) traduite(s)"
          + (f", {reste} au prochain passage" if reste > 0 else ""))
    return faites


def main():
    global TYPE_COLOR
    TYPE_COLOR = couleurs_types()

    print("Lecture des biens publiés…")
    biens = lire("public_properties?select=*")
    photos = lire("public_property_photos?select=*&order=position.asc")
    par_bien = {}
    for p in photos:
        par_bien.setdefault(p["property_id"], []).append(p)

    # Traductions manquantes, avant de générer : ce qui revient est utilisé
    # dans la foulée par les fiches anglaises de ce même passage.
    prechauffer_traductions(biens)

    os.makedirs(DOSSIER, exist_ok=True)
    os.makedirs(DOSSIER_EN, exist_ok=True)
    # On repart d'un dossier propre : un bien dépublié ne doit pas laisser
    # une page fantôme derrière lui. Les deux langues sont concernées.
    for dossier in (DOSSIER, DOSSIER_EN):
        for ancien in os.listdir(dossier):
            if ancien.endswith(".html"):
                os.remove(os.path.join(dossier, ancien))

    etat, catalogue_modifie = dates_des_fiches(biens, par_bien)

    urls = []
    manifeste = {}
    for b in biens:
        voisins = [(v, par_bien.get(v["id"], [])) for v in similaires(b, biens)]
        noms = {}
        for lang, dossier in (("fr", DOSSIER), ("en", DOSSIER_EN)):
            nom, html = page_bien(b, par_bien.get(b["id"], []), voisins,
                                  etat[b["ref"]]["premiere"], lang)
            with open(os.path.join(dossier, nom), "w", encoding="utf-8") as f:
                f.write(html)
            noms[lang] = nom
            urls.append((url_fiche(b, lang), etat[b["ref"]]["modifie"]))
        manifeste[b["ref"]] = noms
    changes = sum(1 for v in etat.values() if v["modifie"] == date.today().isoformat())
    print(f"  {len(urls)} pages écrites dans bien/ et bien/en/ ({changes} avec du nouveau)")

    # --- bien/index.json ----------------------------------------------------
    # La vitrine s'en sert pour pointer vers la fiche d'un bien. Elle pourrait
    # recalculer le nom du fichier en JavaScript, mais elle fabriquerait alors
    # des liens vers des pages pas encore générées — un bien publié ce matin
    # n'a pas de fiche tant que ce script n'a pas tourné. Ce fichier ne liste
    # que ce qui existe vraiment : pas de lien mort possible.
    # Depuis l'ajout des fiches anglaises, la valeur est un objet {fr, en} et
    # non plus un simple nom de fichier. La vitrine accepte les deux formes :
    # le temps qu'une nouvelle génération soit publiée, l'ancien index reste
    # lisible et les liens continuent de fonctionner.
    with open(os.path.join(DOSSIER, "index.json"), "w", encoding="utf-8") as f:
        json.dump(manifeste, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"  bien/index.json : {len(manifeste)} références (fr + en)")

    with open(os.path.join(DOSSIER, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_index(biens, par_bien, "fr"))
    with open(os.path.join(DOSSIER_EN, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_index(biens, par_bien, "en"))
    print("  bien/index.html + bien/en/index.html : pages d'index statiques")

    # --- guides/ --------------------------------------------------------------
    # Contenu de fond, indépendant des biens : ne dépend d'aucune donnée de la
    # base, donc jamais nettoyé au début de cette fonction comme bien/ — un
    # guide qui disparaîtrait à chaque exécution serait absurde.
    os.makedirs(DOSSIER_GUIDES, exist_ok=True)
    # Anglais dans un sous-dossier voisin plutôt qu'un ?lang= : ce sont des
    # pages statiques indépendantes (voir page_guide()), chacune avec sa
    # propre URL indexable — pas une traduction automatique à la volée comme
    # les descriptions de biens, un contenu à caractère juridique se rédige
    # directement dans les deux langues.
    dossier_guides_en = os.path.join(DOSSIER_GUIDES, "en")
    os.makedirs(dossier_guides_en, exist_ok=True)
    urls_guides = []
    for g in GUIDES:
        with open(os.path.join(DOSSIER_GUIDES, f"{g['slug']}.html"), "w", encoding="utf-8") as f:
            f.write(page_guide(g, "fr"))
        with open(os.path.join(dossier_guides_en, f"{g['slug']}.html"), "w", encoding="utf-8") as f:
            f.write(page_guide(g, "en"))
        urls_guides.append((f"{SITE}/guides/{g['slug']}.html", g["date_publication"]))
        urls_guides.append((f"{SITE}/guides/en/{g['slug']}.html", g["date_publication"]))
    with open(os.path.join(DOSSIER_GUIDES, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_guides_index(GUIDES, "fr"))
    with open(os.path.join(dossier_guides_en, "index.html"), "w", encoding="utf-8") as f:
        f.write(page_guides_index(GUIDES, "en"))
    print(f"  {len(GUIDES)} guide(s) écrit(s) dans guides/ (fr + en)")

    # --- sitemap.xml --------------------------------------------------------
    # Chaque adresse porte la date de son dernier changement réel, pas celle du
    # jour. Un sitemap qui déclare tout modifié à chaque passage perd sa raison
    # d'être : Google cesse de s'y fier et explore à son propre rythme.
    aujourdhui = date.today().isoformat()
    # L'accueil et la page d'index changent dès qu'un bien entre ou sort du
    # catalogue, ou dès que l'un d'eux bouge.
    dates_biens = [d for _, d in urls]
    accueil_modifie = (aujourdhui if catalogue_modifie
                       else max(dates_biens, default=aujourdhui))
    lignes = [f"  <url><loc>{SITE}/{ACCUEIL}</loc><lastmod>{accueil_modifie}</lastmod>"
              f"<changefreq>daily</changefreq><priority>1.0</priority></url>",
              f"  <url><loc>{SITE}/bien/</loc><lastmod>{accueil_modifie}</lastmod>"
              f"<changefreq>daily</changefreq><priority>0.9</priority></url>",
              f"  <url><loc>{SITE}/bien/en/</loc><lastmod>{accueil_modifie}</lastmod>"
              f"<changefreq>daily</changefreq><priority>0.9</priority></url>"]
    lignes += [f"  <url><loc>{u}</loc><lastmod>{d}</lastmod>"
               f"<changefreq>weekly</changefreq><priority>0.8</priority></url>"
               for u, d in urls]
    if urls_guides:
        derniere_maj_guides = max(d for _, d in urls_guides)
        lignes.append(f"  <url><loc>{SITE}/guides/</loc>"
                       f"<lastmod>{derniere_maj_guides}</lastmod>"
                       f"<changefreq>monthly</changefreq><priority>0.7</priority></url>")
        lignes.append(f"  <url><loc>{SITE}/guides/en/</loc>"
                       f"<lastmod>{derniere_maj_guides}</lastmod>"
                       f"<changefreq>monthly</changefreq><priority>0.7</priority></url>")
    lignes += [f"  <url><loc>{u}</loc><lastmod>{d}</lastmod>"
               f"<changefreq>monthly</changefreq><priority>0.7</priority></url>"
               for u, d in urls_guides]
    with open(os.path.join(RACINE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                + "\n".join(lignes) + "\n</urlset>\n")
    print(f"  sitemap.xml : {len(lignes)} adresses")

    # L'état est écrit en dernier : si quelque chose échoue avant, la prochaine
    # exécution repart des dates précédentes plutôt que d'une mémoire à moitié
    # réécrite.
    with open(ETAT, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1, sort_keys=True)

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
