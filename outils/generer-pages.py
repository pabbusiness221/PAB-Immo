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
    # Navigation
    "Revenir à l'accueil": "Back to home", "Accueil": "Home",
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
    "7j/7, 24h/24": "24/7",
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

# Google coupe le titre autour de 60 caractères et la description autour de
# 155. Au-delà, la fin est remplacée par des points de suspension : la phrase
# se termine sur un mot tronqué, ce qui donne une impression de négligence
# précisément là où il faut inspirer confiance.
LIMITE_TITRE = 60
LIMITE_DESCRIPTION = 155


def couper_proprement(texte, limite, suffixe="…"):
    """Coupe sur une frontière de mot, jamais au milieu. Renvoie le texte tel
    quel s'il tient déjà, sans ajouter de points de suspension inutiles."""
    texte = " ".join((texte or "").split())
    if len(texte) <= limite:
        return texte
    coupe = texte[:limite - len(suffixe)]
    espace = coupe.rfind(" ")
    if espace > limite * 0.6:          # on ne remonte pas jusqu'à tout perdre
        coupe = coupe[:espace]
    return coupe.rstrip(" ,;:·—-") + suffixe


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
    region_utile = slug(region) not in {slug(m) for m in (commune, quartier) if m}

    def assembler(avec_region, avec_quartier=True):
        base = commune
        if avec_quartier and quartier and slug(quartier) != slug(commune):
            base = f"{quartier}, {commune}"
        if avec_region and region_utile:
            base += f" ({region})"
        if lang == "en":
            action = tr("à vendre" if b["operation"] == "Vente" else "à louer", "en")
            return f'{tr(b["type"], "en")} {action} in {base}'
        action = "à vendre" if b["operation"] == "Vente" else "à louer"
        return f'{b["type"]} {action} à {base}'

    # Le titre affiché par Google porte en plus « | PAB Immo ». On raccourcit
    # donc en sacrifiant d'abord la région, puis le quartier — les éléments les
    # moins recherchés — plutôt qu'en tronquant la fin, ce qui amputerait le
    # nom de la commune, c'est-à-dire le mot que les gens tapent.
    marge = len(f" | {AGENCE}")
    for candidat in (assembler(True), assembler(False), assembler(False, False)):
        if len(candidat) + marge <= LIMITE_TITRE:
            return candidat
    return couper_proprement(assembler(False, False), LIMITE_TITRE - marge)


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
    # La coupe brutale à 300 caractères finissait au milieu d'un mot — « d'une
    # superfic… » — et dépassait de toute façon ce que Google affiche.
    return couper_proprement(txt, LIMITE_DESCRIPTION)


# « Maison » est le seul type féminin du catalogue. Sans cette table, les
# phrases composées donnaient « ce maison » et « comment est-il agencé » sur
# les fiches de maisons — une faute d'accord en toutes lettres, sur la page
# même où l'agence demande qu'on lui fasse confiance.
FEMININ = {"Maison"}


def accords(b):
    """Renvoie les formes accordées utilisées dans les phrases composées."""
    f = b["type"] in FEMININ
    return {
        "ce": "cette" if f else "ce",
        "il": "elle" if f else "il",
        "Il": "Elle" if f else "Il",
        "e": "e" if f else "",        # proposé / proposée, situé / située
    }


def prix_unitaire(b):
    """Prix au m² (ou à l'hectare pour un champ). Calculé, jamais inventé :
    c'est la première chose que compare un acheteur, et la fiche l'obligeait
    jusqu'ici à sortir sa calculatrice."""
    try:
        s = float(b["surface"])
        p = float(b["price"])
    except (TypeError, ValueError, KeyError):
        return None
    if s <= 0 or p <= 0 or b["operation"] != "Vente":
        return None
    return int(round(p / s))


def faq_bien(b, lang="fr"):
    """Questions-réponses composées à partir des seules données du bien.

    Deux bénéfices, pour un même texte. D'abord la page passe de cent
    quarante mots à un contenu qui répond vraiment : « combien coûte le m² »,
    « est-ce encore disponible » sont les questions réellement tapées. Ensuite
    ces questions autorisent le balisage FAQPage, que Google déplie parfois
    directement dans ses résultats.

    Aucune réponse n'invente quoi que ce soit : chacune se déduit d'un champ
    renseigné, et les questions sans donnée derrière sont simplement omises.
    """
    en = lang == "en"
    lieu = lieu_court(b["commune"])
    type_txt = tr(b["type"], lang)
    q = []

    prix_txt = fcfa(b["price"]) + (("/mo" if en else "/mois")
                                   if b["operation"] == "Location" else "")
    unitaire = prix_unitaire(b)
    if unitaire:
        unite_txt = "hectare" if b["type"] == "Champ agricole" else "m²"
        detail = (f" That works out to about {fcfa(unitaire)} per {unite_txt}."
                  if en else
                  f" Cela représente environ {fcfa(unitaire)} le {unite_txt}.")
    else:
        detail = ""
    a = accords(b)
    q.append((
        f"How much does this {type_txt.lower()} in {lieu} cost?" if en
        else f"Quel est le prix de {a['ce'] if a['ce'] == 'cette' else 'ce'} {type_txt.lower()} à {lieu} ?",
        (f"This property is listed at {prix_txt}.{detail} Reference {b['ref']}."
         if en else
         f"Ce bien est proposé à {prix_txt}.{detail} Référence {b['ref']}.")))

    q.append((
        f"How big is it?" if en else "Quelle est la superficie ?",
        (f"{surface(b)}." if en else f"Ce bien fait {surface(b)}.")))

    if b.get("chambres"):
        pieces = []
        if b.get("chambres"):    pieces.append(f'{b["chambres"]} ' + ("bedrooms" if en and b["chambres"] > 1 else "bedroom" if en else "chambres" if b["chambres"] > 1 else "chambre"))
        if b.get("salons"):      pieces.append(f'{b["salons"]} ' + ("living rooms" if en and b["salons"] > 1 else "living room" if en else "salons" if b["salons"] > 1 else "salon"))
        if b.get("salles_bain"): pieces.append(f'{b["salles_bain"]} ' + ("bathrooms" if en and b["salles_bain"] > 1 else "bathroom" if en else "salles de bain" if b["salles_bain"] > 1 else "salle de bain"))
        q.append((
            "How is it laid out?" if en
            else f"Comment est-{a['il']} agencé{a['e']} ?",
            ("It has " if en else "Le bien comprend ") + ", ".join(pieces) + "."))

    if b.get("statut_foncier") and b["statut_foncier"] != "Non renseigné":
        statut = tr(b["statut_foncier"], lang)
        q.append((
            "What is the land title status?" if en else "Quel est le statut foncier ?",
            (f"This property is held under: {statut}. Our guide explains what "
             f"each status means and how to check it before you commit."
             if en else
             f"Ce bien est sous le statut suivant : {statut}. Notre guide "
             f"détaille ce que recouvre chaque statut et comment le vérifier "
             f"avant de s'engager.")))

    dispo = b.get("status") or "Disponible"
    q.append((
        "Is it still available?" if en else "Ce bien est-il encore disponible ?",
        (f"Status at the last update: {tr(dispo, lang)}. Availability is "
         f"checked regularly, and we confirm it by phone or WhatsApp before "
         f"any visit." if en else
         f"Statut à la dernière mise à jour : {tr(dispo, lang)}. La "
         f"disponibilité est vérifiée régulièrement, et nous la confirmons par "
         f"téléphone ou WhatsApp avant toute visite.")))

    q.append((
        f"How can I visit this property in {lieu}?" if en
        else f"Comment visiter ce bien à {lieu} ?",
        (f"Visits are by appointment. Send reference {b['ref']} on WhatsApp at "
         f"{TEL_AFFICHE} or call us, and we will arrange a time — including "
         f"evenings and weekends." if en else
         f"Les visites se font sur rendez-vous. Envoyez la référence "
         f"{b['ref']} par WhatsApp au {TEL_AFFICHE} ou appelez-nous, et nous "
         f"conviendrons d'un créneau — y compris en soirée et le week-end.")))

    return q


def resume_bien(b, lang="fr"):
    """Un paragraphe de synthèse, composé des seuls champs renseignés.

    Il existe pour deux raisons. Un visiteur arrivé de Google veut savoir en
    une phrase de quoi il s'agit, sans lire un tableau. Et une page qui ne
    contient qu'une liste de valeurs ne dit rien à un moteur : ce sont les
    phrases, pas les cellules, qui portent les mots qu'on tape.
    """
    en = lang == "en"
    lieu = lieu_court(b["commune"])
    quartier = lieu_court(b.get("quartier") or "")
    region = lieu_court(b["region"])
    type_txt = tr(b["type"], lang).lower()
    action = tr("à vendre" if b["operation"] == "Vente" else "à louer", lang)
    prix_txt = fcfa(b["price"]) + (("/mo" if en else "/mois")
                                   if b["operation"] == "Location" else "")

    situe = f"{quartier}, {lieu}" if quartier and slug(quartier) != slug(lieu) else lieu
    if en:
        p = (f"This {type_txt} is {action} in {situe}, in the region of "
             f"{region}. It covers {surface(b)} and is listed at {prix_txt}.")
    else:
        a = accords(b)
        p = (f"{a['ce'].capitalize()} {type_txt} est {action} à {situe}, dans "
             f"la région de {region}. {a['Il']} fait {surface(b)} et est "
             f"proposé{a['e']} à {prix_txt}.")

    unitaire = prix_unitaire(b)
    if unitaire:
        unite_txt = "hectare" if b["type"] == "Champ agricole" else "m²"
        p += (f" That is roughly {fcfa(unitaire)} per {unite_txt}, a figure worth "
              f"comparing with other listings in the same area."
              if en else
              f" Soit environ {fcfa(unitaire)} le {unite_txt}, un repère utile "
              f"pour comparer avec d'autres biens du même secteur.")

    if b.get("chambres"):
        p += (f" It has {b['chambres']} bedroom" + ("s" if b["chambres"] > 1 else "") + "."
              if en else
              f" {accords(b)['Il']} compte {b['chambres']} chambre"
              + ("s" if b["chambres"] > 1 else "") + ".")

    p += (f" Reference {b['ref']}, visits by appointment."
          if en else f" Référence {b['ref']}, visites sur rendez-vous.")
    return p


def etapes_suivantes(b, lang="fr"):
    """Ce qui se passe après un premier contact. Le parcours est réellement
    différent selon qu'on achète ou qu'on loue ; le décrire évite la question
    que tout le monde pose au téléphone, et donne à la page le contenu utile
    qui lui manquait."""
    en = lang == "en"
    lieu = lieu_court(b["commune"])
    if b["operation"] == "Location":
        if en:
            return [
                (f"Visit the property in {lieu}",
                 "We arrange a time that suits you, including evenings and weekends."),
                ("Review the lease",
                 "Duration, deposit, advance rent and charges are agreed in writing before signature."),
                ("Inventory and handover",
                 "A written inventory protects both sides at move-in and at move-out."),
            ]
        return [
            (f"Visiter le bien à {lieu}",
             "Nous convenons d'un créneau qui vous arrange, y compris en soirée et le week-end."),
            ("Examiner le bail",
             "Durée, caution, avance de loyers et charges sont fixées par écrit avant toute signature."),
            ("État des lieux et remise des clés",
             "Un état des lieux écrit protège les deux parties, à l'entrée comme à la sortie."),
        ]
    if en:
        return [
            (f"Visit the property in {lieu}",
             "By appointment, with someone who knows the file and can answer on site."),
            ("Check the documents",
             "Land title, boundary survey and deeds are verified before any commitment, at the notary."),
            ("Work out the full cost",
             "Registration duties and notary fees come on top of the asking price."),
            ("Sign at the notary",
             "The sale is completed before a notary — the only act that makes the transfer enforceable."),
        ]
    return [
        (f"Visiter le bien à {lieu}",
         "Sur rendez-vous, avec quelqu'un qui connaît le dossier et répond aux questions sur place."),
        ("Vérifier les documents",
         "Statut foncier, bornage et titre sont contrôlés avant tout engagement, chez le notaire."),
        ("Chiffrer le coût total",
         "Au prix affiché s'ajoutent les droits d'enregistrement et les frais de notaire."),
        ("Signer chez le notaire",
         "La vente se conclut devant notaire, seul acte qui rend le transfert opposable."),
    ]


def guides_lies(b, lang="fr"):
    """Les deux ou trois guides qui répondent aux questions que pose CE bien.

    Un terrain à vendre appelle le statut foncier et les frais d'achat ; un
    logement à louer appelle le bail et la caution. Ces liens servent autant le
    visiteur, qui trouve la suite de sa question, que le référencement : ils
    font circuler l'autorité entre les fiches et les guides, aujourd'hui reliés
    dans un seul sens.
    """
    en = lang == "en"
    choix = []
    if b["operation"] == "Location":
        choix = ["louer-logement-dakar-bail-caution", "questions-frequentes"]
    elif b["type"] in ("Terrain", "Champ agricole"):
        choix = ["verifier-titre-foncier-senegal", "frais-achat-immobilier-senegal",
                 "construire-terrain-senegal-permis"]
    else:
        choix = ["frais-achat-immobilier-senegal", "verifier-titre-foncier-senegal",
                 "acheter-terrain-senegal-depuis-etranger"]
    par_slug = {g["slug"]: g for g in GUIDES}
    sortie = []
    for s in choix:
        g = par_slug.get(s)
        if not g:
            continue
        titre = g.get("titre_seo_en" if en else "titre_seo") or (g["titre_en"] if en else g["titre"])
        chemin = f"../guides/en/{s}.html" if en else f"../guides/{s}.html"
        sortie.append((chemin, titre))
    return sortie


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

    # Fil d'Ariane. Il était déjà affiché en haut de la fiche, mais nulle part
    # déclaré : faute de ce balisage, Google montre l'adresse brute sous le
    # titre — « pabbusiness221.github.io › bien › appartement-a-louer… » — au
    # lieu du chemin lisible « Tous les biens › Appartement › Mermoz ».
    #
    # Les trois échelons reprennent mot pour mot ceux du <nav class="fil"> :
    # une piste de navigation déclarée qui ne correspond pas à celle qu'on voit
    # est une erreur signalée par Google, et à juste titre.
    # L'échelon du milieu — le type de bien — n'a pas encore de page à lui.
    # Il restera sans adresse tant que les pages « terrains à vendre à Thiès »
    # n'existent pas ; le jour où elles seront générées, c'est ici qu'elles se
    # brancheront. Le dernier échelon pointe la fiche elle-même, ce qui évite
    # de laisser deux maillons sans destination.
    racine = f"{SITE}/bien/en/" if lang == "en" else f"{SITE}/bien/"
    fil = [
        {"@type": "ListItem", "position": 1,
         "name": tr("Tous les biens", lang), "item": racine},
        {"@type": "ListItem", "position": 2, "name": tr(b["type"], lang)},
        {"@type": "ListItem", "position": 3,
         "name": lieu_court(b["commune"]), "item": url},
    ]
    # Les questions déclarées ici sont exactement celles affichées plus bas sur
    # la page. Déclarer une FAQ absente de l'écran est une infraction que Google
    # sanctionne, et c'est de toute façon inutile : ce qu'on veut, c'est que la
    # réponse visible soit celle qui remonte.
    questions = faq_bien(b, lang)
    graphe = {
        "@context": "https://schema.org",
        "@graph": [
            {k: v for k, v in d.items() if v is not None and k != "@context"},
            {"@type": "BreadcrumbList", "itemListElement": fil},
            {"@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": q,
                 "acceptedAnswer": {"@type": "Answer", "text": r}}
                for q, r in questions
            ]},
        ],
    }
    return json.dumps(graphe, ensure_ascii=False, indent=2)


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
  /* Bandeau collant : un visiteur arrive ici depuis Google ou un partage
     WhatsApp, pas depuis la vitrine. Statique, il disparaissait des le
     premier defilement et l'on se retrouvait sur une page sans aucun moyen
     de revenir au catalogue ni de changer de langue. z-index modeste : rien
     d'autre ne se superpose sur ces pages. */
  .bandeau{{position:sticky;top:0;z-index:50;background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;}}
  .bandeau .lang{{color:rgba(255,255,255,.75);font-size:12.5px;font-weight:700;letter-spacing:.04em;border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:4px 11px;}}
  .bandeau .lang:hover{{color:var(--gold);border-color:var(--gold);}}
  .bandeau a{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a span{{color:var(--accent);}}
  .bandeau-gauche{{display:flex;align-items:center;gap:10px;}}
  .bandeau a.accueil{{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;flex:none;border:1px solid rgba(255,255,255,.28);border-radius:9px;}}
  .bandeau a.accueil:hover{{border-color:var(--gold);color:var(--gold);}}
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
  /* Questions fréquentes. Repliées par défaut : la fiche doit rester courte à
     l'œil, alors que la réponse doit exister dans la page pour être lue par
     Google — <details> réunit les deux, sans JavaScript. */
  .resume{{font-size:15px;line-height:1.7;color:var(--ink);margin:0 0 6px;}}
  .etapes{{margin:0;padding:0;list-style:none;counter-reset:etape;display:grid;gap:10px;}}
  .etapes li{{counter-increment:etape;position:relative;padding-left:44px;}}
  .etapes li::before{{content:counter(etape);position:absolute;left:0;top:0;width:30px;height:30px;
    border-radius:50%;background:var(--night);color:#fff;display:grid;place-items:center;
    font-weight:800;font-size:13px;}}
  .etapes li b{{display:block;font-size:14px;color:var(--night);margin-bottom:2px;}}
  .etapes li span{{font-size:13.5px;line-height:1.6;color:var(--ink-soft);}}
  .faq-bien details{{border:1px solid var(--border);border-radius:10px;background:var(--surface);margin-bottom:8px;}}
  .faq-bien summary{{cursor:pointer;padding:13px 16px;font-weight:700;font-size:14px;color:var(--night);list-style:none;}}
  .faq-bien summary::-webkit-details-marker{{display:none;}}
  .faq-bien summary::after{{content:'+';float:right;color:var(--accent);font-size:18px;line-height:1;}}
  .faq-bien details[open] summary::after{{content:'\\2212';}}
  .faq-bien summary:hover{{color:var(--accent-dark);}}
  .faq-bien summary:focus-visible{{outline:3px solid var(--accent);outline-offset:2px;}}
  .faq-bien p{{margin:0;padding:0 16px 14px;font-size:13.5px;line-height:1.65;color:var(--ink-soft);}}
  .guides-lies ul{{margin:0;padding:0;list-style:none;display:grid;gap:8px;}}
  .guides-lies li a{{display:block;padding:12px 16px;border:1px solid var(--border);border-radius:10px;background:var(--surface);color:var(--night);text-decoration:none;font-weight:600;font-size:13.5px;}}
  .guides-lies li a:hover{{border-color:var(--accent);color:var(--accent-dark);}}
  .faits li{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-md);padding:12px 14px;}}
  .faits b{{display:block;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-soft);font-weight:700;}}
  .faits span{{font-size:15px;font-weight:800;}}
  .texte{{font-size:15px;line-height:1.7;}}
  .contact{{margin-top:32px;background:linear-gradient(140deg,var(--night),var(--night-2));border-radius:var(--radius-lg);padding:24px;}}
  .contact p{{color:rgba(255,255,255,.74);font-size:14px;margin:0 0 16px;line-height:1.6;}}
  .contact h2{{color:#fff;margin:0 0 6px;}}
  .actions{{display:flex;gap:10px;flex-wrap:wrap;}}
  .actions a{{flex:1 1 200px;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;border-radius:999px;font-weight:700;font-size:14px;text-decoration:none;}}
  /* Vert WhatsApp assombri : le #25D366 de la marque ne donne que 1,98:1 avec
     du texte blanc, très en dessous du minimum AA de 4,5:1. Cette teinte reste
     dans la famille des verts WhatsApp (proche du #128C7E de leur charte) et
     passe à plus de 5:1. */
  .wa{{background:#0E7A6B;color:#fff;}} .tel{{background:var(--accent);color:#1E1607;}}
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
  /* Pas d'opacity : elle ramenait les mentions légales à 2,84:1 sur le bleu
     nuit, très en dessous du minimum AA. La taille réduite suffit à les
     distinguer du reste du pied de page. */
  footer .reg{{font-size:11.5px;}}
</style>
<script type="application/ld+json">
{donnees_structurees(b, photos, url, publiee or date.today().isoformat(), lang)}
</script>
</head>
<body>
<header class="bandeau">
  <div class="bandeau-gauche">
    <!-- Le même bouton accueil que dans l'en-tête de la vitrine : depuis une
         fiche, la marque seule ne se lit pas comme « retour ». -->
    <a class="accueil" href="{prefixe}/{ACCUEIL}" aria-label="{tr('Revenir à l\'accueil', lang)}" title="{tr('Accueil', lang)}">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>
    </a>
    <a href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  </div>
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
    <!-- Vert assombri : #2F7A4E sur son propre fond à 12 % ne donnait que
         4,28:1, sous le minimum AA pour un texte de 11,5 px. -->
    <p class="etat" style="margin:0;background:{'rgba(47,122,78,.12);color:#26663F' if b["status"] == "Disponible" else 'rgba(226,162,44,.15);color:#8F6414'}">{esc(tr(b["status"], lang))}</p>
    {f'<p class="etat" style="margin:0;background:rgba(37,99,235,.12);color:#2854A6;">{esc(tr(b["statut_foncier"], lang))}</p>' if b.get("statut_foncier") and b["statut_foncier"] != "Non renseigné" else ''}
    {f'<p class="etat" style="margin:0;background:rgba(107,70,193,.12);color:#6B46C1;">{tr("Meublé" if b["meuble"] else "Non meublé", lang)}</p>' if b.get("meuble") is not None else ''}
    {f'<p class="etat" style="margin:0;background:rgba(180,83,9,.12);color:#B45309;">{tr("Disponible à partir du", lang)} {esc(b["date_disponibilite"])}</p>' if disponible_futur else ''}
  </div>

  {f'<h2>{tr("Photos", lang)}</h2>' + galerie if photos else ''}

  <p class="resume">{esc(resume_bien(b, lang))}</p>

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

  <h2>{'What happens next' if lang == 'en' else 'Comment se passe la suite'}</h2>
  <ol class="etapes">
    {"".join(f'<li><b>{esc(t)}</b><span>{esc(d)}</span></li>' for t, d in etapes_suivantes(b, lang))}
  </ol>

  <h2>{'Frequently asked questions' if lang == 'en' else 'Questions fréquentes sur ce bien'}</h2>
  <div class="faq-bien">
    {"".join(f'<details><summary>{esc(q)}</summary><p>{esc(r)}</p></details>' for q, r in faq_bien(b, lang))}
  </div>

  <section class="guides-lies">
    <h2>{'Before you commit' if lang == 'en' else 'Avant de vous engager'}</h2>
    <p>{'Practical guides on the questions this kind of property usually raises.' if lang == 'en' else 'Nos guides pratiques sur les questions que pose ce type de bien.'}</p>
    <ul>
      {"".join(f'<li><a href="{esc(c)}">{esc(t)}</a></li>' for c, t in guides_lies(b, lang))}
    </ul>
  </section>

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
  {TEL_AFFICHE} · {EMAIL} · {tr("7j/7, 24h/24", lang)} · {tr("visites sur rendez-vous", lang)}<br>
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
    # Resserré pour tenir dans les 60 caractères affichés par Google. « Dakar »
    # et « Thiès » restent en tête : ce sont les mots qui décident du clic.
    titre = (f"Immobilier à Dakar et Thiès | {AGENCE}" if lang != "en" else
             f"Property in Dakar and Thiès | {AGENCE}")
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
                # L'email manquait : c'est, avec le téléphone, l'un des deux
                # moyens de contact que Google rapproche d'une fiche
                # d'établissement pour juger qu'il s'agit d'une vraie entreprise.
                "email": EMAIL,
                "image": f"{SITE}/assets/logo.png",
                "logo": f"{SITE}/assets/logo.png",
                # Numéros officiels : ils distinguent une agence enregistrée
                # d'un particulier, sur un marché où la question se pose.
                "taxID": NINEA,
                "identifier": {"@type": "PropertyValue", "name": "RCCM",
                               "value": RCCM},
                "currenciesAccepted": "XOF",
                "areaServed": [
                    {"@type": "AdministrativeArea", "name": "Dakar"},
                    {"@type": "AdministrativeArea", "name": "Thiès"},
                ],
                # addressLocality manquait. Sans ville, une adresse ne dit rien
                # à un moteur qui cherche à rattacher l'agence à un endroit —
                # c'est précisément ce que fait une recherche « agence
                # immobilière Dakar ». Pas de rue déclarée : l'agence reçoit sur
                # rendez-vous, et inventer une adresse postale serait pire que
                # de n'en pas donner.
                "address": {"@type": "PostalAddress", "addressCountry": "SN",
                            "addressRegion": "Dakar", "addressLocality": "Dakar"},
                # Joignable en permanence : c'est ce que Google lit pour
                # afficher « Ouvert 24h/24 » dans un résultat local.
                "openingHoursSpecification": {
                    "@type": "OpeningHoursSpecification",
                    "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday",
                                  "Friday", "Saturday", "Sunday"],
                    "opens": "00:00",
                    "closes": "23:59",
                },
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
    desc = couper_proprement(desc, LIMITE_DESCRIPTION)
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
  /* Bandeau collant : un visiteur arrive ici depuis Google ou un partage
     WhatsApp, pas depuis la vitrine. Statique, il disparaissait des le
     premier defilement et l'on se retrouvait sur une page sans aucun moyen
     de revenir au catalogue ni de changer de langue. z-index modeste : rien
     d'autre ne se superpose sur ces pages. */
  .bandeau{{position:sticky;top:0;z-index:50;background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;gap:12px;}}
  .bandeau .lang{{color:rgba(255,255,255,.75);font-size:12.5px;font-weight:700;letter-spacing:.04em;border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:4px 11px;}}
  .bandeau .lang:hover{{color:var(--gold);border-color:var(--gold);}}
  .bandeau a{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a span{{color:var(--accent);}}
  .bandeau-gauche{{display:flex;align-items:center;gap:10px;}}
  .bandeau a.accueil{{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;flex:none;border:1px solid rgba(255,255,255,.28);border-radius:9px;}}
  .bandeau a.accueil:hover{{border-color:var(--gold);color:var(--gold);}}
  main{{max-width:960px;margin:0 auto;padding:26px 20px 60px;}}
  h1{{font-family:'Manrope',sans-serif;font-size:clamp(24px,4.5vw,32px);font-weight:800;letter-spacing:-0.02em;margin:0 0 10px;}}
  .intro{{color:var(--ink-soft);font-size:15px;line-height:1.65;margin:0 0 8px;max-width:60ch;}}
  h2{{font-family:'Manrope',sans-serif;font-size:17px;font-weight:800;margin:32px 0 14px;}}
{STYLE_VIGNETTES}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.9;}}
  footer a{{color:rgba(255,255,255,.72);text-decoration:none;font-weight:600;}}
  footer a:hover{{color:var(--gold);}}
  /* Pas d'opacity : elle ramenait les mentions légales à 2,84:1 sur le bleu
     nuit, très en dessous du minimum AA. La taille réduite suffit à les
     distinguer du reste du pied de page. */
  footer .reg{{font-size:11.5px;}}
</style>
<script type="application/ld+json">
{ld}
</script>
</head>
<body>
<header class="bandeau">
  <div class="bandeau-gauche">
    <!-- Le même bouton accueil que dans l'en-tête de la vitrine : depuis une
         fiche, la marque seule ne se lit pas comme « retour ». -->
    <a class="accueil" href="{prefixe}/{ACCUEIL}" aria-label="{tr('Revenir à l\'accueil', lang)}" title="{tr('Accueil', lang)}">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>
    </a>
    <a href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  </div>
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
  {AGENCE} — {TEL_AFFICHE} · {EMAIL} · {tr("7j/7, 24h/24", lang)} · {tr("visites sur rendez-vous", lang)}<br>
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
        "titre_seo": "Vérifier le statut foncier d'un terrain au Sénégal",
        "titre_seo_en": "Checking Land Title Status in Senegal",
        "description": "Titre foncier, bail, délibération : ce que signifie chaque statut, "
                        "pourquoi la différence compte avant d'acheter, et comment le vérifier "
                        "concrètement. Guide à jour pour un achat de terrain au Sénégal.",
        "date_publication": "2026-08-02",
        "corps": """
    <p>Devant un terrain, on regarde d'abord le prix et la superficie. La question qui compte
    vient pourtant avant&nbsp;: <strong>sur quel statut foncier ce terrain repose-t-il&nbsp;?</strong>
    De la réponse dépend ce que vous achetez réellement, une propriété pleine et transmissible
    ou un droit d'occupation plus fragile. Au Sénégal, cette confusion alimente l'essentiel des
    litiges immobiliers.</p>

    <h2>Les trois statuts que vous rencontrerez</h2>

    <p><strong>Le titre foncier (TF)</strong> est le statut le plus sûr&nbsp;: la parcelle est
    immatriculée au nom de son propriétaire à la Conservation de la Propriété Foncière. Ce
    titre est opposable à tous, transmissible, et peut servir de garantie pour un prêt. C'est
    l'équivalent d'un acte de propriété définitif.</p>

    <p><strong>Le bail</strong> porte sur un terrain qui appartient à l'État ou à une commune.
    Son titulaire a le droit de l'occuper et de l'exploiter pendant une durée déterminée. Cette
    durée peut être longue&nbsp;; elle n'est jamais illimitée, et le bailleur reste
    juridiquement propriétaire du sol. Un bail peut, sous certaines conditions, être transformé
    en titre foncier. Tant que cette conversion n'a pas eu lieu, il n'en est pas un.</p>

    <p><strong>La délibération</strong> est une décision d'affectation prise par un conseil
    municipal, qui attribue une parcelle du domaine national à un particulier. C'est le statut
    le plus courant sur les terrains ruraux ou communautaires, et souvent la première étape
    avant une éventuelle immatriculation. Une délibération n'est <strong>pas</strong> un titre
    de propriété&nbsp;: elle peut, dans certains cas, être remise en cause par la commune qui
    l'a délivrée, en particulier si le terrain n'est pas mis en valeur dans les délais prévus.</p>

    <h2>Ce que la différence change pour un acheteur</h2>

    <p>Acheter sur la base d'une délibération n'a rien d'une erreur en soi. Une grande partie du
    foncier rural sénégalais fonctionne ainsi, et beaucoup de délibérations sont parfaitement
    régulières. Le risque encouru n'est simplement pas celui d'un titre foncier. Il faut donc
    savoir <em>ce que l'on achète</em>, l'accepter en connaissance de cause, et ajuster sa
    prudence en conséquence. Souvent aussi son prix. Ce qui pose problème, ce n'est pas le
    statut lui-même&nbsp;: c'est de le découvrir une fois la signature passée.</p>

    <h2>Comment vérifier, concrètement</h2>

    <ul>
      <li><strong>Demandez le document original</strong> (titre foncier, bail ou délibération)
      ainsi que le nom exact qui y figure. Un vendeur sérieux ne s'y refuse jamais.</li>
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
      commune compétente sur ce terrain, et depuis quand. Une délibération ancienne, mise en
      valeur et jamais contestée, rassure davantage qu'une délibération toute récente.</li>
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
    documents et de l'existence réelle du bien avant publication. Ce badge ne vous dispense
    d'aucune vérification au moment de l'achat. Il réduit seulement le nombre de biens sur
    lesquels vous aurez à les mener.</p>

    <h2>Questions fréquentes</h2>

    <p><strong>Un bail est-il moins bien qu'un titre foncier&nbsp;?</strong><br>
    Les deux ne répondent pas au même besoin. Un bail donne un droit d'occupation et
    d'exploitation limité dans le temps, non une propriété pleine. Pour un usage personnel sur
    une durée raisonnable, il convient parfaitement. Pour un investissement de long terme
    destiné à être transmis, un titre foncier reste préférable.</p>

    <p><strong>Peut-on transformer une délibération en titre foncier&nbsp;?</strong><br>
    Oui, le cas est courant. La procédure et les délais varient toutefois d'une situation à
    l'autre, et rien n'est automatique ni garanti. Renseignez-vous auprès d'un notaire ou
    directement des services fonciers avant de compter dessus.</p>

    <p><strong>Un acheteur vivant à l'étranger peut-il vérifier tout cela à distance&nbsp;?</strong><br>
    En grande partie, oui, par procuration notariée confiée à une personne de confiance ou à un
    notaire sur place. C'est d'ailleurs dans cette situation que les vérifications ci-dessus
    comptent le plus. Elles se font normalement en personne, et lorsqu'elles sont bâclées, on
    s'en aperçoit beaucoup moins facilement depuis l'étranger.</p>

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
    <p>Most buyers look at the price and the surface area first. The question that matters comes
    earlier: <strong>what land title status does the plot rest on?</strong> The answer decides
    what you are actually buying, either full transferable ownership or a far more fragile right
    of occupation. In Senegal, confusion on this point drives most property disputes.</p>

    <h2>The three statuses you will encounter</h2>

    <p><strong>Freehold title (titre foncier, TF)</strong> is the most secure status: the
    plot is registered in its owner's name at the Land Registry (Conservation de la Propriété
    Foncière). This title is enforceable against everyone, transferable, and can serve as
    collateral for a loan. It is the equivalent of a definitive deed of ownership.</p>

    <p><strong>A lease (bail)</strong> applies to land that belongs to the State or a
    municipality. Its holder has the right to occupy and use that land for a set period. The
    period may be long; it is never unlimited, and the lessor remains the legal owner of the
    ground. Under certain conditions a lease can be converted into freehold title. Until that
    conversion takes place, it is not one.</p>

    <p><strong>A council deliberation (délibération)</strong> is an allocation decision made by a
    municipal council, granting a parcel of national land to an individual. It is the most common
    status on rural or community land, and often the first step before eventual registration. A
    deliberation is <strong>not</strong> a title of ownership: it can, in some cases, be
    revoked by the municipality that issued it, particularly if the land is not developed within
    the required timeframe.</p>

    <h2>What the difference means for a buyer</h2>

    <p>Buying on the basis of a deliberation is not a mistake in itself. A large share of
    Senegal's rural land works this way, and many deliberations are perfectly regular. The risk
    you take on simply is not the risk of a freehold title. So you need to know <em>what you are
    buying</em>, accept it knowingly, and adjust your caution accordingly. Often your price too.
    The trouble is rarely the status itself. It is discovering it once you have signed.</p>

    <h2>How to verify it, in practice</h2>

    <ul>
      <li><strong>Ask for the original document</strong> (freehold title, lease, or
      deliberation) and the exact name it bears. A serious seller never refuses this.</li>
      <li><strong>Check that it matches</strong> the plot you actually visited: parcel number,
      surface area and boundaries as described on the document. A survey by a licensed surveyor
      removes any doubt.</li>
      <li><strong>Confirm the registration</strong> of a freehold title with the Land Registry
      office responsible for that parcel, and check for the absence of any mortgage or pending
      dispute.</li>
      <li><strong>Go through a notary</strong> for the deed of sale. A private agreement (a
      simple paper signed between individuals) over land held under freehold title does not carry
      the same legal weight as a notarized deed, and is not enough to make you the owner.</li>
      <li><strong>For a deliberation</strong>, verify that it was indeed issued by the
      municipality with authority over that land, and how long ago. An older deliberation,
      developed and never contested, reassures far more than a very recent one.</li>
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
    the property's actual existence checked before publication. The badge excuses you from no
    verification at the time of purchase. It only reduces the number of properties you will need
    to run those checks on.</p>

    <h2>Frequently asked questions</h2>

    <p><strong>Is a lease worse than freehold title?</strong><br>
    The two answer different needs. A lease grants a right to occupy and use the land for a
    limited time, not full ownership. For personal use over a reasonable period it suits
    perfectly well. For a long-term investment meant to be passed on, freehold title remains
    preferable.</p>

    <p><strong>Can a deliberation be converted into freehold title?</strong><br>
    Yes, and it happens often. The procedure and the timeline vary from one case to the next,
    though, and nothing is automatic or guaranteed. Ask a notary, or the land services directly,
    before counting on it.</p>

    <p><strong>Can a buyer living abroad verify all of this remotely?</strong><br>
    For the most part, yes, through a notarized power of attorney given to a trusted person or a
    notary on the ground. This is in fact the situation where the checks above matter most. They
    are normally done in person, and when they are skimped on, you are far less likely to notice
    from abroad.</p>

    <p class="avert">This article provides general guidance; it is not legal advice and
    does not replace a notary's checks for an actual transaction. Senegalese land law evolves;
    if in doubt, consult a professional before committing.</p>
""",
    },
    {
        "slug": "acheter-terrain-senegal-depuis-etranger",
        "titre": "Acheter un terrain au Sénégal depuis l'étranger : procuration, notaire, vérifications",
        "titre_seo": "Acheter un terrain au Sénégal depuis l'étranger",
        "titre_seo_en": "Buying Land in Senegal from Abroad",
        "description": "Vivre en France, en Italie ou ailleurs n'empêche pas d'acheter un "
                        "terrain au Sénégal. Voici comment fonctionne la procuration, ce que "
                        "vérifie un notaire, et les précautions propres à un achat à distance.",
        "date_publication": "2026-08-05",
        "corps": """
    <p>Une grande partie des acheteurs de terrain à Dakar et à Thiès ne vit pas au Sénégal.
    La situation est courante et ne constitue pas un obstacle. Elle change une chose, en
    revanche&nbsp;: les vérifications qui se font naturellement en marchant sur le terrain
    doivent ici être organisées autrement. Ce guide explique comment.</p>

    <h2>La procuration&nbsp;: acheter sans être présent</h2>

    <p>La procuration (ou « mandat ») est l'outil central d'un achat à distance. Par acte
    notarié, elle donne à une personne de confiance le pouvoir d'agir en votre nom&nbsp;:
    souvent un proche sur place, ou le notaire lui-même. Trois points à retenir&nbsp;:</p>

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
    La responsabilité de ces vérifications lui revient à lui seul, ni à l'agence ni au vendeur.
    Pour un achat à distance, son rôle pèse encore davantage&nbsp;: il devient vos yeux sur
    place au moment décisif.</p>

    <h2>Ce qu'il faut vérifier avant d'envoyer le moindre franc</h2>

    <ul>
      <li>Le statut foncier du terrain (titre foncier, bail ou délibération) et sa
      correspondance avec la parcelle réellement visée, par photo, par vidéo, ou par un géomètre
      mandaté sur place si le montant le justifie.</li>
      <li>L'identité du vendeur, comparée au nom inscrit sur le document de propriété.</li>
      <li>L'existence d'un notaire clairement identifié et joignable directement, pas seulement
      « connu » du vendeur ou de l'intermédiaire.</li>
      <li>Le taux de change, si vous raisonnez en euros ou en dollars. Le FCFA est arrimé à
      l'euro à un taux fixe (655,957 F CFA pour 1&nbsp;€) et échappe donc aux variations qui
      touchent les autres devises. Vous pouvez convertir vous-même sans mauvaise surprise.</li>
    </ul>

    <h2>Les précautions propres à l'achat à distance</h2>

    <ul>
      <li><strong>Ne jamais transférer de fonds avant l'acte notarié</strong>, même pressé par
      une « offre limitée dans le temps ». C'est une pression classique.</li>
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
    Oui, par virement bancaire international vers un compte au Sénégal&nbsp;: le vôtre, ou celui
    que le notaire vous indiquera une fois l'acte prêt. Passer par un compte personnel plutôt
    que par un intermédiaire non identifié reste la règle la plus sûre.</p>

    <p class="avert">Cet article donne des repères généraux&nbsp;; ce n'est pas un avis
    juridique. Les démarches de procuration varient selon votre pays de résidence&nbsp;:
    vérifiez-les auprès d'un notaire ou du consulat du Sénégal compétent avant de vous engager.</p>
""",
        "titre_en": "Buying Land in Senegal from Abroad: Power of Attorney, the Notary's Role, Due Diligence",
        "description_en": "Living in France, Italy, or elsewhere doesn't stop you from buying "
                           "land in Senegal. Here's how power of attorney works, what a notary "
                           "checks, and the precautions specific to a remote purchase.",
        "corps_en": """
    <p>A large share of land buyers in Dakar and Thiès don't live in Senegal. The situation is
    common and no obstacle in itself. It does change one thing: the checks that happen naturally
    when you walk the plot have to be organized another way. This guide explains how.</p>

    <h2>Power of attorney: buying without being present</h2>

    <p>A power of attorney (or "mandate") is the central tool for a remote purchase. Through a
    notarized deed, it gives a trusted person the authority to act on your behalf: often a
    relative on the ground, or the notary directly. Three points to keep in mind:</p>

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
    any mortgage or dispute, and draft the deed that legally makes you the owner. Responsibility
    for these checks rests with the notary alone, not with the agency and not with the seller.
    For a remote purchase that role weighs even heavier: the notary becomes your eyes on the
    ground at the decisive moment.</p>

    <h2>What to check before sending a single franc</h2>

    <ul>
      <li>The plot's land title status (freehold title, lease, or deliberation) and whether it
      matches the plot actually seen, by photo, by video, or through a surveyor commissioned on
      site if the amount justifies it.</li>
      <li>The seller's identity, checked against the name on the property document.</li>
      <li>The existence of a clearly identified notary you can reach directly, not merely one
      "known" to the seller or intermediary.</li>
      <li>The exchange rate, if you're thinking in euros or dollars. The FCFA is pegged to the
      euro at a fixed rate (655.957 F CFA to 1&nbsp;€) and so escapes the swings that affect
      other currencies. You can convert a price yourself without surprises.</li>
    </ul>

    <h2>Precautions specific to a remote purchase</h2>

    <ul>
      <li><strong>Never transfer funds before the notarized deed</strong>, however urgent a
      "limited-time offer" is made to sound. That is a classic pressure tactic.</li>
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
    Yes, by international bank transfer to an account in Senegal: either yours, or, once the
    deed is ready, the one indicated by the notary. Going through a personal account rather than
    an unidentified intermediary remains the safest rule.</p>

    <p class="avert">This article provides general guidance; it is not legal advice. Power
    of attorney procedures vary by country of residence: check them with a notary or the
    relevant Senegalese consulate before committing.</p>
""",
    },
    {
        "slug": "frais-achat-immobilier-senegal",
        "titre": "Ce que coûte vraiment un achat immobilier au Sénégal, au-delà du prix affiché",
        "titre_seo": "Frais d'achat immobilier au Sénégal",
        "titre_seo_en": "Property Purchase Costs in Senegal",
        "description": "Droits d'enregistrement, émoluments du notaire, publicité foncière, "
                        "bornage : le détail des frais qui s'ajoutent au prix de vente d'un "
                        "terrain ou d'une maison au Sénégal, et comment les chiffrer à l'avance.",
        "date_publication": "2026-08-09",
        "corps": """
    <p>Un acheteur qui a mis de côté le montant exact d'une annonce se trouve rarement au bout de
    son budget. Le prix de vente ne représente qu'une partie de la dépense. S'y ajoutent des frais
    obligatoires, prélevés par l'État et par le notaire, qui se règlent au moment de la signature
    et non pas plus tard. Les découvrir à ce moment-là oblige à emprunter dans l'urgence ou à
    renoncer. Voici de quoi ils se composent.</p>

    <h2>Les quatre postes à prévoir</h2>

    <p><strong>Les droits d'enregistrement</strong> sont un impôt sur la mutation, versé à
    l'administration fiscale pour que la vente soit officiellement enregistrée. C'est
    généralement le poste le plus lourd après le prix lui-même. Le taux dépend de la nature du
    bien et de l'opération, et il évolue avec les lois de finances. Aucun chiffre trouvé sur
    internet ne remplace le taux applicable le jour de votre acte&nbsp;: demandez-le au notaire
    ou aux services fiscaux.</p>

    <p><strong>Les émoluments du notaire</strong> rémunèrent son travail de vérification et de
    rédaction. Ils suivent un barème réglementé, calculé sur le prix de vente, auquel s'ajoutent
    des débours (les sommes qu'il avance pour votre compte). Un notaire vous communique ce
    montant avant la signature si vous le lui demandez.</p>

    <p><strong>Les frais de publicité foncière</strong> couvrent l'inscription de votre nom à la
    Conservation de la Propriété Foncière. Sans cette formalité, la vente existe entre vous et le
    vendeur mais reste invisible pour les tiers, ce qui vous laisse exposé.</p>

    <p><strong>Le bornage</strong> par un géomètre agréé n'est pas systématiquement obligatoire,
    mais il devient vite indispensable sur un terrain dont les limites ne sont pas matérialisées.
    Son coût est sans commune mesure avec celui d'un litige de voisinage quelques années plus
    tard.</p>

    <h2>Comment chiffrer avant de s'engager</h2>

    <p>La méthode fiable tient en une phrase&nbsp;: demandez un devis écrit au notaire, sur la
    base du prix convenu, avant de verser quoi que ce soit. Un notaire établit ce décompte
    couramment. Il y fera figurer les droits, ses émoluments, les débours et la publicité
    foncière, ligne par ligne.</p>

    <p>Prévoyez cette enveloppe en plus du prix, jamais dedans. Un budget total de vingt millions
    consacré entièrement au prix de vente laisse zéro pour les frais, et la transaction se bloque
    au dernier moment.</p>

    <h2>Les frais côté vendeur</h2>

    <p>Le vendeur n'est pas exempté. Selon sa situation et la durée de détention du bien, une
    imposition sur la plus-value peut s'appliquer, et certains documents fiscaux lui sont
    demandés avant la vente. Un vendeur qui découvre cela au moment de signer retarde toute la
    transaction. Si vous vendez, anticipez ce point avec votre notaire dès la mise en vente.</p>

    <h2>Les erreurs qui coûtent cher</h2>

    <ul>
      <li><strong>Payer avant l'acte notarié.</strong> Une somme versée de la main à la main,
      sans acte, ne vous rend propriétaire de rien.</li>
      <li><strong>Sous-déclarer le prix</strong> pour réduire les droits. La pratique existe,
      elle est illégale, et elle se retourne contre l'acheteur le jour où il revend&nbsp;: sa
      plus-value apparente devient énorme.</li>
      <li><strong>Oublier la publicité foncière</strong> une fois l'acte signé, en pensant que
      tout est réglé.</li>
      <li><strong>Confondre l'acompte et les frais.</strong> L'acompte s'impute sur le prix, les
      frais s'y ajoutent.</li>
    </ul>

    <h2>Questions fréquentes</h2>

    <p><strong>Peut-on négocier les frais de notaire&nbsp;?</strong><br>
    Les émoluments suivent un barème, ils ne se négocient donc pas librement. Le prix de vente,
    lui, se négocie, et il fait mécaniquement baisser les frais calculés dessus.</p>

    <p><strong>Qui paie les frais, l'acheteur ou le vendeur&nbsp;?</strong><br>
    L'usage veut que l'acheteur supporte les droits d'enregistrement et les frais d'acte. Cet
    usage peut être aménagé par accord entre les parties, à condition que ce soit écrit dans le
    compromis et non convenu oralement.</p>

    <p><strong>Faut-il ces frais aussi pour un terrain sous délibération&nbsp;?</strong><br>
    Les formalités diffèrent de celles d'un titre foncier, et leur coût aussi. Le
    <a href="verifier-titre-foncier-senegal.html">statut foncier du terrain</a> détermine la
    procédure applicable, donc la facture. Vérifiez-le avant de bâtir votre budget.</p>

    <p class="avert">Cet article décrit la structure des frais, pas leur montant&nbsp;: les taux
    et barèmes changent, et seul un notaire peut vous donner le chiffre applicable à votre
    transaction. Ce n'est pas un conseil fiscal.</p>
""",
        "titre_en": "What a Property Purchase in Senegal Really Costs, Beyond the Asking Price",
        "description_en": "Registration duties, notary fees, land registration, surveying: the "
                          "costs that come on top of the sale price of land or a house in "
                          "Senegal, and how to budget for them in advance.",
        "corps_en": """
    <p>A buyer who has set aside exactly the amount shown in a listing is rarely at the end of
    their spending. The sale price covers only part of the outlay. Mandatory charges come on top,
    collected by the State and by the notary, and they fall due at signature rather than later.
    Discovering them at that point forces you to borrow in a hurry or walk away. Here is what
    they consist of.</p>

    <h2>Four items to budget for</h2>

    <p><strong>Registration duties</strong> are a transfer tax paid to the revenue authorities so
    that the sale is officially recorded. This is usually the heaviest item after the price
    itself. The rate depends on the type of property and transaction, and it changes with each
    finance act. No figure found online replaces the rate that applies on the day of your deed:
    ask the notary or the tax office.</p>

    <p><strong>The notary's fees</strong> pay for the verification and drafting work. They follow
    a regulated scale based on the sale price, plus disbursements (sums the notary advances on
    your behalf). Any notary will give you that figure before signature if you ask.</p>

    <p><strong>Land registration costs</strong> cover entering your name at the Land Registry.
    Without that formality the sale exists between you and the seller but stays invisible to
    third parties, which leaves you exposed.</p>

    <p><strong>Surveying</strong> by a licensed surveyor is not always compulsory. It becomes
    close to essential on a plot whose boundaries are not physically marked. What it costs bears
    no comparison with a boundary dispute a few years later.</p>

    <h2>How to budget before committing</h2>

    <p>The reliable method fits in one sentence: ask the notary for a written estimate, based on
    the agreed price, before paying anything. Notaries prepare these routinely. The estimate will
    set out duties, fees, disbursements and registration costs, line by line.</p>

    <p>Plan that envelope on top of the price, never inside it. A total budget of twenty million
    spent entirely on the sale price leaves nothing for the costs, and the transaction stalls at
    the last moment.</p>

    <h2>Costs on the seller's side</h2>

    <p>Sellers are not exempt. Depending on their situation and how long they have held the
    property, capital gains tax may apply, and certain tax documents will be required before the
    sale. A seller who discovers this at signature delays the whole transaction. If you are
    selling, raise the point with your notary as soon as you list.</p>

    <h2>Expensive mistakes</h2>

    <ul>
      <li><strong>Paying before the notarized deed.</strong> Money handed over without a deed
      makes you the owner of nothing.</li>
      <li><strong>Under-declaring the price</strong> to reduce duties. The practice exists, it is
      illegal, and it rebounds on the buyer at resale: their apparent gain becomes enormous.</li>
      <li><strong>Forgetting land registration</strong> once the deed is signed, assuming
      everything is settled.</li>
      <li><strong>Confusing the deposit with the costs.</strong> A deposit counts towards the
      price; the costs come on top of it.</li>
    </ul>

    <h2>Frequently asked questions</h2>

    <p><strong>Can notary fees be negotiated?</strong><br>
    The fees follow a scale, so they cannot be freely negotiated. The sale price can be, and
    lowering it mechanically lowers the fees calculated on it.</p>

    <p><strong>Who pays, the buyer or the seller?</strong><br>
    By custom the buyer bears the registration duties and the cost of the deed. That custom can
    be varied by agreement, provided it is written into the preliminary contract rather than
    agreed verbally.</p>

    <p><strong>Do these costs apply to land held under a deliberation?</strong><br>
    The formalities differ from those for freehold title, and so does their cost. The
    <a href="verifier-titre-foncier-senegal.html">land title status</a> determines the procedure
    and therefore the bill. Check it before you build your budget.</p>

    <p class="avert">This article describes the structure of the costs, not their amount: rates
    and scales change, and only a notary can give you the figure that applies to your
    transaction. It is not tax advice.</p>
""",
    },
    {
        "slug": "louer-logement-dakar-bail-caution",
        "titre": "Louer un logement à Dakar : bail, caution, avance de loyers et état des lieux",
        "titre_seo": "Louer un logement à Dakar : bail et caution",
        "titre_seo_en": "Renting a Home in Dakar: Lease and Deposit",
        "description": "Ce que contient un bail au Sénégal, ce qu'on peut vous demander comme "
                        "caution et avance, comment se passe l'état des lieux et comment "
                        "récupérer son dépôt. Repères pratiques pour louer à Dakar et Thiès.",
        "date_publication": "2026-08-09",
        "corps": """
    <p>La plupart des litiges entre bailleur et locataire à Dakar ne portent pas sur le loyer.
    Ils portent sur ce qui n'a pas été écrit au départ&nbsp;: le montant réellement versé à
    l'entrée, l'état du logement, qui paie quelles réparations. Une location se joue en grande
    partie le jour de la signature. Voici ce qu'il faut y regarder.</p>

    <h2>Le bail écrit, même entre gens de confiance</h2>

    <p>Un bail verbal existe juridiquement, mais il ne prouve rien. Sans écrit, il n'y a plus de
    trace du montant convenu, de la durée, ni de ce que couvrent les charges. Exigez un document
    signé par les deux parties, en deux exemplaires, et gardez le vôtre.</p>

    <p>Il doit au minimum mentionner l'identité du bailleur et du locataire, l'adresse et la
    description du logement, le montant du loyer et sa date de paiement, la durée, le montant du
    dépôt de garantie, et ce que recouvrent les charges. Une clause floue sur les charges se
    transforme presque toujours en désaccord au bout de quelques mois.</p>

    <h2>Caution, avance, dépôt&nbsp;: trois choses différentes</h2>

    <p>Le vocabulaire courant les mélange, alors que les sommes n'ont pas la même nature.</p>

    <ul>
      <li><strong>Le dépôt de garantie</strong> (souvent appelé caution) est une somme immobilisée
      pendant toute la location, destinée à couvrir d'éventuels dégâts ou impayés. Elle vous est
      rendue à la sortie si le logement est en bon état.</li>
      <li><strong>L'avance de loyers</strong> correspond à des mois payés d'avance. Cette somme
      n'est pas une garantie&nbsp;: elle s'impute sur vos loyers. La pratique de demander
      plusieurs mois d'avance est répandue à Dakar. Faites préciser par écrit combien de mois
      sont couverts et lesquels.</li>
      <li><strong>La commission d'agence</strong>, quand il y en a une, rémunère l'intermédiaire.
      Elle ne se récupère pas.</li>
    </ul>

    <p>Additionnez les trois avant de vous engager. Le vrai coût d'entrée dans un logement est
    souvent bien supérieur à un mois de loyer, et c'est là que les budgets se cassent.</p>

    <h2>L'état des lieux, votre meilleure protection</h2>

    <p>Faites le tour du logement avec le bailleur avant d'emménager, et notez tout&nbsp;: fissures,
    robinetterie, prises, état des peintures, fonctionnement des serrures. Photographiez, datez,
    faites signer le document par les deux parties. Cela prend une heure.</p>

    <p>Sans état des lieux d'entrée, un bailleur de mauvaise foi peut vous imputer à la sortie des
    dégradations antérieures à votre arrivée, et vous n'aurez rien à opposer. Refaites le même
    exercice au départ.</p>

    <h2>Récupérer son dépôt de garantie</h2>

    <p>Prévenez votre départ dans les formes et les délais prévus au bail. Rendez le logement
    propre, dans l'état de l'entrée, usure normale mise à part. Présentez-vous à l'état des lieux
    de sortie plutôt que de laisser les clés à un tiers. Demandez un reçu de restitution des
    clés.</p>

    <p>Si une retenue vous est annoncée, demandez qu'elle soit justifiée par écrit, avec les
    devis ou factures correspondants. Une retenue sans justificatif se conteste.</p>

    <h2>Les signaux qui doivent alerter</h2>

    <ul>
      <li>On vous demande de l'argent pour <em>visiter</em> un logement.</li>
      <li>Le bailleur refuse tout document écrit, ou promet de « régulariser plus tard ».</li>
      <li>La personne qui vous fait visiter ne prouve ni qu'elle est propriétaire, ni qu'elle est
      mandatée.</li>
      <li>Le montant demandé à l'entrée change entre la visite et la signature.</li>
      <li>Un loyer nettement sous le marché du quartier, avec une pression pour payer vite.</li>
    </ul>

    <h2>Questions fréquentes</h2>

    <p><strong>Combien de mois d'avance peut-on me demander&nbsp;?</strong><br>
    Les usages varient selon le quartier et le type de bien, et un encadrement légal existe.
    Plutôt que de vous fier à ce qui se pratique autour de vous, faites écrire le détail dans le
    bail et renseignez-vous sur la règle en vigueur avant de payer.</p>

    <p><strong>Le bailleur peut-il augmenter le loyer en cours de bail&nbsp;?</strong><br>
    Pas librement. Une augmentation en cours de bail suppose une clause prévue au contrat ou un
    accord entre les parties. Un bail écrit, là encore, est votre protection.</p>

    <p><strong>Qui paie les réparations&nbsp;?</strong><br>
    L'entretien courant revient en général au locataire, les grosses réparations et le clos et
    couvert au propriétaire. La frontière se discute&nbsp;: plus le bail est précis sur ce point,
    moins vous aurez à en débattre.</p>

    <p class="avert">Cet article donne des repères pratiques et ne constitue pas un avis
    juridique. La réglementation des loyers au Sénégal évolue&nbsp;; en cas de désaccord sérieux,
    rapprochez-vous d'un professionnel du droit.</p>
""",
        "titre_en": "Renting a Home in Dakar: Lease, Deposit, Advance Rent and Inventory",
        "description_en": "What a lease should contain in Senegal, what you can be asked for as "
                          "a deposit and advance rent, how the inventory works and how to get "
                          "your deposit back. Practical guidance for Dakar and Thiès.",
        "corps_en": """
    <p>Most disputes between landlord and tenant in Dakar are not about the rent. They are about
    what nobody wrote down at the start: how much was actually paid on entry, the condition of
    the property, who pays for which repairs. A tenancy is largely decided on the day you sign.
    Here is what to look at.</p>

    <h2>A written lease, even between people who trust each other</h2>

    <p>A verbal lease exists in law, but it proves nothing. With nothing in writing, there is no
    record of the agreed amount, the term, or what the charges cover. Insist on a document signed
    by both parties, in two copies, and keep yours.</p>

    <p>At a minimum it should state the identity of landlord and tenant, the address and
    description of the property, the rent and its due date, the term, the security deposit, and
    what the charges include. A vague clause about charges nearly always turns into a
    disagreement a few months in.</p>

    <h2>Deposit, advance rent and commission are three different things</h2>

    <p>Everyday language blurs them, yet the sums are not of the same nature.</p>

    <ul>
      <li><strong>The security deposit</strong> is money held for the length of the tenancy to
      cover possible damage or arrears. You get it back when you leave if the property is in good
      order.</li>
      <li><strong>Advance rent</strong> is months paid up front. It is not a guarantee: it counts
      against your rent. Asking for several months in advance is widespread in Dakar. Have it put
      in writing how many months are covered, and which ones.</li>
      <li><strong>Agency commission</strong>, where there is one, pays the intermediary. You do
      not get it back.</li>
    </ul>

    <p>Add all three together before committing. The real cost of moving in is often well above a
    single month's rent, and that is where budgets break.</p>

    <h2>The inventory is your best protection</h2>

    <p>Walk through the property with the landlord before moving in and note everything: cracks,
    taps, sockets, paintwork, whether the locks work. Photograph it, date it, have both parties
    sign. It takes an hour.</p>

    <p>Without an entry inventory, a landlord acting in bad faith can charge you on the way out
    for damage that predates your arrival, and you will have nothing to point to. Repeat the same
    exercise when you leave.</p>

    <h2>Getting your deposit back</h2>

    <p>Give notice in the manner and within the time the lease requires. Return the property
    clean and in its entry condition, fair wear and tear aside. Attend the exit inventory rather
    than leaving the keys with a third party. Ask for a receipt for the keys.</p>

    <p>If a deduction is announced, ask for it to be justified in writing, with the matching
    quotes or invoices. A deduction with no supporting document can be challenged.</p>

    <h2>Warning signs</h2>

    <ul>
      <li>You are asked for money simply to <em>view</em> a property.</li>
      <li>The landlord refuses anything in writing, or promises to "sort it out later".</li>
      <li>The person showing you round proves neither ownership nor authority to act.</li>
      <li>The amount required on entry changes between the viewing and the signature.</li>
      <li>A rent noticeably below the local market, with pressure to pay quickly.</li>
    </ul>

    <h2>Frequently asked questions</h2>

    <p><strong>How many months in advance can I be asked for?</strong><br>
    Practice varies by neighbourhood and property type, and legal limits do exist. Rather than
    relying on what people around you do, have the detail written into the lease and check the
    rule in force before paying.</p>

    <p><strong>Can the landlord raise the rent during the lease?</strong><br>
    Not freely. An increase mid-term requires a clause in the contract or an agreement between
    the parties. Once again, a written lease is your protection.</p>

    <p><strong>Who pays for repairs?</strong><br>
    Day-to-day upkeep generally falls to the tenant, major repairs and the structure to the
    owner. The line between them is arguable, and the more precise the lease is on this point,
    the less you will have to argue.</p>

    <p class="avert">This article offers practical guidance and is not legal advice. Rental
    regulation in Senegal changes; if a serious disagreement arises, consult a legal
    professional.</p>
""",
    },
    {
        "slug": "vendre-son-bien-senegal",
        "titre": "Vendre un terrain ou une maison au Sénégal : documents, prix, délais",
        "titre_seo": "Vendre un terrain ou une maison au Sénégal",
        "titre_seo_en": "Selling Land or a House in Senegal",
        "description": "Les documents à réunir avant de mettre en vente, comment fixer un prix "
                        "défendable, le rôle du notaire et les délais réalistes d'une vente "
                        "immobilière au Sénégal.",
        "date_publication": "2026-08-09",
        "corps": """
    <p>Une vente qui traîne coûte de l'argent au vendeur, et pas seulement en temps. Un bien resté
    trop longtemps en ligne finit par inquiéter les acheteurs, qui supposent un problème caché et
    négocient en conséquence. La plupart des ventes lentes le sont pour une raison simple&nbsp;:
    le dossier n'était pas prêt au moment de la mise en vente.</p>

    <h2>Réunir les documents avant de publier</h2>

    <p>Rassemblez tout avant la première visite, pas au moment où un acheteur se décide. Un
    acheteur sérieux qui attend trois semaines un document se met à douter, ou trouve autre
    chose.</p>

    <ul>
      <li><strong>Le document de propriété</strong>&nbsp;: titre foncier, bail ou délibération,
      dans sa version originale. Le <a href="verifier-titre-foncier-senegal.html">statut
      foncier</a> conditionne toute la suite de la procédure.</li>
      <li><strong>Votre pièce d'identité</strong>, et le nom exact tel qu'il figure sur le titre.
      Une différence d'orthographe entre les deux se règle, mais cela prend du temps.</li>
      <li><strong>Le plan et le bornage</strong> s'il s'agit d'un terrain.</li>
      <li><strong>Les justificatifs fiscaux</strong> demandés au vendeur. Votre notaire vous dira
      lesquels s'appliquent à votre situation.</li>
      <li><strong>L'accord des co-indivisaires</strong> en cas de succession ou de propriété
      partagée. C'est de loin la première cause de vente bloquée.</li>
    </ul>

    <h2>Fixer un prix qui tienne</h2>

    <p>Un prix trop haut ne se corrige pas tout seul&nbsp;: il fait fuir les acheteurs pendant des
    mois, puis oblige à baisser sous la valeur réelle pour rattraper le retard. Un prix trop bas
    se remarque aussi, et fait naître le soupçon d'un vice.</p>

    <p>Appuyez-vous sur des ventes comparables&nbsp;: même commune, même type de bien, surface
    proche, transactions récentes. Les annonces en ligne donnent un premier ordre de grandeur, à
    condition de comparer ce qui l'est vraiment. L'état du bien, son emplacement exact et le
    moment du marché font le reste. Écrivez-nous pour une évaluation de votre bien&nbsp;: nous
    connaissons les prix pratiqués dans nos communes.</p>

    <h2>Ce qui fait vendre, concrètement</h2>

    <p>Des photos nettes, prises de jour, en montrant les pièces vides ou rangées. Une annonce qui
    dit la surface, le nombre de pièces, le statut foncier et le quartier précis. Une adresse
    joignable, et une réponse dans la journée.</p>

    <p>Le statut foncier affiché dès l'annonce fait gagner du temps à tout le monde. Les acheteurs
    que ce statut ne convient pas ne se déplacent pas, et ceux qui viennent savent déjà à quoi
    s'attendre.</p>

    <h2>Le rôle du notaire, côté vendeur</h2>

    <p>Le notaire ne travaille pas seulement pour l'acheteur. Il vérifie que vous pouvez
    juridiquement vendre, rédige l'acte, calcule les sommes dues et sécurise le paiement. Une
    vente réglée directement entre particuliers, sans acte notarié, expose autant le vendeur que
    l'acheteur&nbsp;: elle peut être remise en cause des années plus tard.</p>

    <h2>Des délais réalistes</h2>

    <p>Entre l'accord sur le prix et la signature définitive, comptez en semaines plutôt qu'en
    jours. Les vérifications du notaire, l'obtention des pièces administratives et, souvent, le
    financement de l'acheteur, prennent chacun leur temps. Un acheteur qui promet de signer sous
    huit jours annonce rarement une réalité.</p>

    <p>Un dossier complet dès le départ reste le seul levier qui raccourcisse vraiment ces
    délais.</p>

    <h2>Questions fréquentes</h2>

    <p><strong>Puis-je vendre un terrain sous délibération&nbsp;?</strong><br>
    Oui, mais la procédure et les garanties offertes à l'acheteur diffèrent de celles d'un titre
    foncier, et cela se reflète dans le prix. Annoncez le statut clairement dès le début.</p>

    <p><strong>Dois-je payer un impôt sur la vente&nbsp;?</strong><br>
    Une imposition sur la plus-value peut s'appliquer selon votre situation et la durée de
    détention. Posez la question à votre notaire au moment de la mise en vente, pas à la
    signature.</p>

    <p><strong>Puis-je vendre depuis l'étranger&nbsp;?</strong><br>
    Oui, par procuration notariée, selon le même mécanisme que pour un achat. Notre guide sur
    <a href="acheter-terrain-senegal-depuis-etranger.html">l'achat depuis l'étranger</a> décrit
    la procédure&nbsp;; elle se transpose à la vente.</p>

    <p class="avert">Cet article donne des repères généraux et ne constitue ni un avis juridique
    ni un conseil fiscal. Les règles applicables dépendent de votre situation&nbsp;: consultez un
    notaire avant de vous engager.</p>
""",
        "titre_en": "Selling Land or a House in Senegal: Documents, Price, Timelines",
        "description_en": "The documents to gather before listing, how to set a price that "
                          "holds, the notary's role on the seller's side, and realistic "
                          "timelines for a property sale in Senegal.",
        "corps_en": """
    <p>A sale that drags costs the seller money, not just time. A property listed for too long
    starts to worry buyers, who assume a hidden problem and negotiate accordingly. Most slow
    sales are slow for one plain reason: the file was not ready when the property went on the
    market.</p>

    <h2>Gather the documents before you list</h2>

    <p>Put everything together before the first viewing, not when a buyer commits. A serious
    buyer left waiting three weeks for a document starts to doubt, or finds something else.</p>

    <ul>
      <li><strong>The ownership document</strong>: freehold title, lease or deliberation, in its
      original form. The <a href="verifier-titre-foncier-senegal.html">land title status</a>
      governs everything that follows.</li>
      <li><strong>Your identity document</strong>, and the exact name as it appears on the title.
      A spelling difference between the two can be resolved, but it takes time.</li>
      <li><strong>The plan and survey</strong> if you are selling land.</li>
      <li><strong>Tax documents</strong> required of sellers. Your notary will say which ones
      apply to your situation.</li>
      <li><strong>The agreement of co-owners</strong> where the property comes from an estate or
      is jointly held. This is by far the leading cause of a blocked sale.</li>
    </ul>

    <h2>Setting a price that holds</h2>

    <p>An inflated price does not correct itself. It keeps buyers away for months, then forces a
    cut below true value to make up lost ground. A price set too low draws attention too, and
    raises the suspicion of a defect.</p>

    <p>Work from comparable sales: same municipality, same property type, similar size, recent
    transactions. Online listings give a first order of magnitude, provided you compare like with
    like. Condition, exact location and market timing account for the rest. Write to us for a
    valuation of your property: we know the prices being paid in the areas we cover.</p>

    <h2>What actually sells a property</h2>

    <p>Sharp photographs taken in daylight, with rooms empty or tidy. A listing that states the
    size, the number of rooms, the land title status and the precise neighbourhood. A contact who
    answers the same day.</p>

    <p>Showing the land title status in the listing saves everyone time. Buyers for whom that
    status does not work never make the trip, and those who do come already know what to
    expect.</p>

    <h2>The notary's role for a seller</h2>

    <p>Notaries do not work for the buyer alone. They confirm that you are legally able to sell,
    draft the deed, calculate what is owed and secure the payment. A sale settled directly
    between individuals, with no notarized deed, exposes the seller as much as the buyer: it can
    be challenged years later.</p>

    <h2>Realistic timelines</h2>

    <p>Between agreeing a price and the final signature, count in weeks rather than days. The
    notary's checks, obtaining administrative papers and, often, the buyer's financing each take
    their own time. A buyer who promises to sign within a week is rarely describing reality.</p>

    <p>A complete file from the outset remains the only lever that genuinely shortens those
    timelines.</p>

    <h2>Frequently asked questions</h2>

    <p><strong>Can I sell land held under a deliberation?</strong><br>
    Yes, though the procedure and the guarantees offered to the buyer differ from those of
    freehold title, and the price reflects that. State the status clearly from the start.</p>

    <p><strong>Will I owe tax on the sale?</strong><br>
    Capital gains tax may apply depending on your situation and how long you have held the
    property. Ask your notary when you list, not at signature.</p>

    <p><strong>Can I sell from abroad?</strong><br>
    Yes, through a notarized power of attorney, by the same mechanism as a purchase. Our guide on
    <a href="acheter-terrain-senegal-depuis-etranger.html">buying from abroad</a> sets out the
    procedure; it transposes to a sale.</p>

    <p class="avert">This article gives general guidance and is neither legal nor tax advice. The
    rules that apply depend on your situation: consult a notary before committing.</p>
""",
    },
    {
        "slug": "construire-terrain-senegal-permis",
        "titre": "Construire sur son terrain au Sénégal : viabilisation, permis de construire, délais",
        "titre_seo": "Construire sur son terrain au Sénégal",
        "titre_seo_en": "Building on Your Land in Senegal",
        "description": "Avant de poser la première pierre : vérifier le statut du terrain, "
                        "évaluer la viabilisation, obtenir le permis de construire et anticiper "
                        "les délais et surcoûts d'un chantier au Sénégal.",
        "date_publication": "2026-08-09",
        "corps": """
    <p>Un terrain acheté n'est pas un terrain constructible. Entre l'acte de vente et les
    fondations, plusieurs étapes peuvent allonger le calendrier de plusieurs mois, ou renchérir le
    projet bien au-delà du prix du foncier. Les connaître avant d'acheter change souvent le choix
    de la parcelle.</p>

    <h2>Première question&nbsp;: le statut du terrain permet-il de construire&nbsp;?</h2>

    <p>Tout part de là. Un terrain sous
    <a href="verifier-titre-foncier-senegal.html">délibération</a> n'ouvre pas les mêmes droits
    qu'un titre foncier, et certaines délibérations imposent justement une mise en valeur dans un
    délai donné, sous peine de retrait. Un bail comporte ses propres conditions d'exploitation.</p>

    <p>Vérifiez aussi la vocation de la zone. Une parcelle située en zone agricole, inondable ou
    frappée d'une servitude ne se construit pas librement, quel que soit son titre. Ces
    informations se demandent auprès de la commune avant l'achat, pas après.</p>

    <h2>La viabilisation, le poste que l'on sous-estime</h2>

    <p>Un terrain viabilisé est raccordé, ou raccordable à faible coût, à l'eau, à l'électricité et
    à une voie d'accès praticable. Un terrain qui ne l'est pas se paie moins cher à l'achat, puis
    beaucoup plus cher ensuite.</p>

    <ul>
      <li><strong>L'eau et l'électricité</strong>&nbsp;: mesurez la distance réelle au réseau
      existant. Le coût d'un raccordement croît vite avec les mètres.</li>
      <li><strong>L'accès</strong>&nbsp;: une parcelle desservie par une piste impraticable en
      hivernage renchérit chaque livraison de matériaux pendant tout le chantier.</li>
      <li><strong>L'assainissement</strong>&nbsp;: en l'absence de réseau, prévoyez une fosse et
      son entretien.</li>
      <li><strong>La nature du sol</strong>&nbsp;: un sol meuble ou une nappe haute imposent des
      fondations plus lourdes. Une étude de sol coûte peu au regard de ce qu'elle évite.</li>
    </ul>

    <h2>Le permis de construire</h2>

    <p>La construction est soumise à autorisation, délivrée par la commune. Le dossier comprend
    généralement la preuve de vos droits sur le terrain, un plan de situation et les plans du
    projet établis par un professionnel habilité.</p>

    <p>Déposez la demande avant d'engager les travaux. Construire sans permis expose à des
    sanctions et complique durablement toute revente&nbsp;: un acheteur averti, ou son notaire,
    demandera l'autorisation, et son absence fait chuter le prix ou annule la transaction.</p>

    <p>Les délais d'instruction varient d'une commune à l'autre. Renseignez-vous directement
    auprès de la mairie concernée plutôt que de vous fier à une moyenne.</p>

    <h2>Choisir qui construit</h2>

    <p>Demandez plusieurs devis détaillés, poste par poste, plutôt qu'un prix global. Un devis qui
    tient en trois lignes ne permet aucune comparaison et laisse toute latitude pour des
    suppléments.</p>

    <p>Visitez des chantiers déjà livrés par l'entreprise. Prévoyez un paiement échelonné suivant
    l'avancement réel, jamais la totalité d'avance. Mettez par écrit le délai, le prix et ce qui
    se passe en cas de retard.</p>

    <h2>Anticiper les surcoûts habituels</h2>

    <p>Les postes qui débordent le plus souvent sont les fondations lorsque le sol réserve une
    surprise, les raccordements, et les modifications demandées en cours de chantier. Gardez une
    réserve budgétaire plutôt que de compter au plus juste.</p>

    <p>Pour un propriétaire vivant à l'étranger, désignez sur place une personne de confiance
    chargée de constater l'avancement, distincte de l'entreprise qui construit. Les visites
    photographiques régulières valent mieux qu'un rapport en fin de chantier.</p>

    <h2>Questions fréquentes</h2>

    <p><strong>Puis-je construire sur un terrain sous délibération&nbsp;?</strong><br>
    Souvent oui, et la mise en valeur est parfois même attendue. Les droits attachés restent
    toutefois moins solides qu'avec un titre foncier. Vérifiez les conditions exactes auprès de la
    commune qui a délivré la délibération.</p>

    <p><strong>Faut-il un architecte&nbsp;?</strong><br>
    Cela dépend de la nature et de la taille du projet. Le dossier de permis exige en tout état de
    cause des plans établis par un professionnel habilité.</p>

    <p><strong>Combien de temps dure une construction&nbsp;?</strong><br>
    Trop de facteurs entrent en jeu pour donner un chiffre utile&nbsp;: taille, financement,
    saison, disponibilité des matériaux. Faites inscrire un délai contractuel dans le devis et
    prévoyez une marge.</p>

    <p class="avert">Cet article donne des repères généraux et ne remplace pas les règles
    d'urbanisme applicables à votre commune, qui priment&nbsp;: renseignez-vous auprès de la
    mairie et d'un professionnel avant d'engager un projet.</p>
""",
        "titre_en": "Building on Your Land in Senegal: Services, Building Permit, Timelines",
        "description_en": "Before laying the first stone: check the land's status, assess the "
                          "cost of connecting services, obtain the building permit and plan for "
                          "the delays and overruns of a construction project in Senegal.",
        "corps_en": """
    <p>Buying land is not the same as owning buildable land. Between the deed of sale and the
    foundations, several steps can stretch the schedule by months, or push the cost well beyond
    the price of the plot. Knowing them before you buy often changes which plot you choose.</p>

    <h2>First question: does the land's status allow building?</h2>

    <p>Everything starts there. Land held under a
    <a href="verifier-titre-foncier-senegal.html">deliberation</a> does not carry the same rights
    as freehold title, and some deliberations specifically require development within a set
    period, failing which they can be withdrawn. A lease comes with its own conditions of use.</p>

    <p>Check the zoning as well. A plot in an agricultural zone, a flood-prone area or one subject
    to an easement cannot be built on freely, whatever its title. Ask the municipality for this
    before buying, not after.</p>

    <h2>Connecting services, the item people underestimate</h2>

    <p>Serviced land is connected, or cheaply connectable, to water, electricity and a usable
    access road. Land that is not costs less to buy and a great deal more afterwards.</p>

    <ul>
      <li><strong>Water and electricity</strong>: measure the real distance to the existing
      network. Connection costs rise quickly with every metre.</li>
      <li><strong>Access</strong>: a plot served by a track that floods in the rainy season adds
      cost to every delivery of materials for the whole build.</li>
      <li><strong>Drainage</strong>: with no mains network, budget for a septic tank and its
      upkeep.</li>
      <li><strong>Ground conditions</strong>: soft ground or a high water table call for heavier
      foundations. A soil survey costs little against what it prevents.</li>
    </ul>

    <h2>The building permit</h2>

    <p>Construction requires authorization from the municipality. The application generally
    includes proof of your rights over the land, a location plan and project drawings prepared by
    a qualified professional.</p>

    <p>File before starting work. Building without a permit carries penalties and complicates any
    resale for good: an informed buyer, or their notary, will ask for the authorization, and its
    absence either cuts the price or kills the deal.</p>

    <p>Processing times vary between municipalities. Ask the relevant town hall directly rather
    than relying on an average.</p>

    <h2>Choosing who builds</h2>

    <p>Ask for several itemized quotes, trade by trade, rather than a single lump sum. A quote
    that fits in three lines allows no comparison and leaves every door open for extras.</p>

    <p>Visit projects the firm has already completed. Arrange staged payments against real
    progress, never everything up front. Put the timeline, the price and what happens in case of
    delay in writing.</p>

    <h2>Planning for the usual overruns</h2>

    <p>The items that most often exceed budget are foundations when the ground springs a surprise,
    service connections, and changes requested mid-build. Keep a contingency rather than costing
    everything to the last franc.</p>

    <p>If you own from abroad, appoint someone you trust on the ground to verify progress, someone
    other than the firm doing the work. Regular photo visits beat a single report at the end.</p>

    <h2>Frequently asked questions</h2>

    <p><strong>Can I build on land held under a deliberation?</strong><br>
    Often yes, and development is sometimes expected. The attached rights remain less solid than
    with freehold title, though. Check the exact conditions with the municipality that issued the
    deliberation.</p>

    <p><strong>Do I need an architect?</strong><br>
    It depends on the nature and size of the project. In any case the permit application requires
    drawings prepared by a qualified professional.</p>

    <p><strong>How long does construction take?</strong><br>
    Too many factors are involved to give a useful figure: size, financing, season, availability
    of materials. Have a contractual deadline written into the quote and allow a margin.</p>

    <p class="avert">This article gives general guidance and does not replace the planning rules
    that apply in your municipality, which take precedence: check with the town hall and a
    professional before starting a project.</p>
""",
    },
    {
        "slug": "questions-frequentes",
        "titre": "Questions fréquentes sur l'achat, la vente et la location avec PAB Immo",
        "titre_seo": "Questions fréquentes sur l'immobilier au Sénégal",
        "titre_seo_en": "Frequently Asked Questions",
        "description": "Visites, annonces vérifiées, statut foncier, achat depuis l'étranger, "
                        "estimation d'un bien, alertes : les réponses aux questions que les "
                        "visiteurs nous posent le plus souvent à Dakar et à Thiès.",
        "date_publication": "2026-08-09",
        "corps": """
    <p>Cette page rassemble les questions qui reviennent le plus souvent, sur le fonctionnement de
    l'agence comme sur les démarches elles-mêmes. Les sujets qui demandent plus de place ont leur
    propre guide, vers lequel chaque réponse renvoie.</p>

    <p>Une question qui ne figure pas ici&nbsp;? Écrivez-nous sur WhatsApp, la réponse arrive
    généralement dans la journée.</p>
""",
        "faq": [
            {
                "q": "Dans quelles zones intervenez-vous ?",
                "r": "<p>Les régions de Dakar et de Thiès. Chaque annonce indique la commune et, "
                     "lorsqu'il est connu, le quartier précis. La vitrine permet aussi de "
                     "chercher autour d'un point sur la carte, ce qui est plus parlant qu'un nom "
                     "de commune quand on ne connaît pas encore la ville.</p>",
                "q_en": "Which areas do you cover?",
                "r_en": "<p>The Dakar and Thiès regions. Every listing gives the municipality "
                        "and, where known, the specific neighbourhood. You can also search around "
                        "a point on the map, which is often clearer than a place name when you "
                        "don't know the city yet.</p>",
            },
            {
                "q": "Comment organiser une visite ?",
                "r": "<p>Les visites se font sur rendez-vous. Depuis la fiche d'un bien, vous "
                     "pouvez envoyer un message ou demander directement un créneau. Le bouton "
                     "WhatsApp ouvre une conversation avec la référence du bien déjà remplie, "
                     "ce qui évite d'avoir à la recopier.</p>",
                "q_en": "How do I arrange a viewing?",
                "r_en": "<p>Viewings are by appointment. From a property page you can send a "
                        "message or request a slot directly. The WhatsApp button opens a "
                        "conversation with the property reference already filled in, so you "
                        "don't have to copy it out.</p>",
            },
            {
                "q": "Que signifie le badge « Annonce vérifiée » ?",
                "r": "<p>Il indique que les documents du bien et son existence réelle ont été "
                     "contrôlés avant la publication. Ce badge ne vous dispense d'aucune "
                     "vérification au moment d'acheter&nbsp;: il réduit seulement le nombre de "
                     "biens sur lesquels vous aurez à les mener. Le détail de ces vérifications "
                     "figure dans notre "
                     "<a href=\"verifier-titre-foncier-senegal.html\">guide sur le statut "
                     "foncier</a>.</p>",
                "q_en": "What does the \"Verified listing\" badge mean?",
                "r_en": "<p>It means the property's documents and its actual existence were "
                        "checked before publication. The badge excuses you from no verification "
                        "when you buy; it only reduces the number of properties you will need to "
                        "run those checks on. Our "
                        "<a href=\"verifier-titre-foncier-senegal.html\">guide to land title "
                        "status</a> sets out what those checks involve.</p>",
            },
            {
                "q": "Pourquoi le statut foncier est-il affiché sur les annonces ?",
                "r": "<p>Parce qu'il détermine ce que vous achetez réellement. Un titre foncier, "
                     "un bail et une délibération n'offrent pas les mêmes garanties. L'afficher "
                     "dès l'annonce fait gagner du temps à tout le monde&nbsp;: vous savez avant "
                     "de vous déplacer si le statut vous convient. Vous pouvez d'ailleurs filtrer "
                     "les biens par statut foncier depuis la recherche avancée.</p>",
                "q_en": "Why is the land title status shown on listings?",
                "r_en": "<p>Because it determines what you are actually buying. Freehold title, a "
                        "lease and a council deliberation do not offer the same guarantees. "
                        "Showing it in the listing saves everyone time: you know before "
                        "travelling whether the status suits you. You can also filter properties "
                        "by land title status in the advanced search.</p>",
            },
            {
                "q": "Comment savoir si un bien est encore disponible ?",
                "r": "<p>Le statut figure sur chaque fiche, et un badge de disponibilité daté "
                     "indique quand elle a été confirmée pour la dernière fois. Passé un mois "
                     "sans confirmation, ce badge disparaît de lui-même plutôt que d'afficher une "
                     "date périmée. Dans le doute, demandez-nous&nbsp;: un bien peut être réservé "
                     "entre deux mises à jour.</p>",
                "q_en": "How do I know whether a property is still available?",
                "r_en": "<p>The status appears on every listing, and a dated availability badge "
                        "shows when it was last confirmed. After a month without confirmation "
                        "the badge disappears on its own rather than showing a stale date. When "
                        "in doubt, ask us: a property can be reserved between two updates.</p>",
            },
            {
                "q": "Puis-je acheter depuis l'étranger ?",
                "r": "<p>Oui. L'achat à distance passe par une procuration notariée et par un "
                     "notaire au Sénégal, qui reste compétent pour l'acte. Notre "
                     "<a href=\"acheter-terrain-senegal-depuis-etranger.html\">guide dédié</a> "
                     "détaille la procédure, les vérifications à ne pas sauter et les précautions "
                     "propres à un achat qu'on ne peut pas superviser sur place.</p>",
                "q_en": "Can I buy from abroad?",
                "r_en": "<p>Yes. A remote purchase goes through a notarized power of attorney and "
                        "a notary in Senegal, who alone has authority over the deed. Our "
                        "<a href=\"acheter-terrain-senegal-depuis-etranger.html\">dedicated "
                        "guide</a> covers the procedure, the checks not to skip and the "
                        "precautions specific to a purchase you cannot supervise in person.</p>",
            },
            {
                "q": "Quels frais s'ajoutent au prix affiché ?",
                "r": "<p>Droits d'enregistrement, émoluments du notaire, publicité foncière et, "
                     "sur un terrain, souvent un bornage. Ces montants se règlent à la signature "
                     "et s'ajoutent au prix, jamais l'inverse. Les taux évoluent, aussi la seule "
                     "méthode fiable reste de demander un devis écrit au notaire avant de "
                     "s'engager. Le détail figure dans notre guide sur "
                     "<a href=\"frais-achat-immobilier-senegal.html\">le coût réel d'un "
                     "achat</a>.</p>",
                "q_en": "What costs come on top of the advertised price?",
                "r_en": "<p>Registration duties, the notary's fees, land registration and, on a "
                        "plot of land, often a survey. These fall due at signature and come on "
                        "top of the price, never inside it. Rates change, so the only reliable "
                        "method is to ask the notary for a written estimate before committing. "
                        "Our guide on <a href=\"frais-achat-immobilier-senegal.html\">what a "
                        "purchase really costs</a> goes through each item.</p>",
            },
            {
                "q": "Je veux vendre : comment estimer mon bien ?",
                "r": "<p>Écrivez-nous en indiquant le type de bien, la commune et la superficie. "
                     "Nous connaissons les prix pratiqués dans nos communes et vous répondons "
                     "avec une fourchette argumentée. Notre "
                     "<a href=\"vendre-son-bien-senegal.html\">guide de la vente</a> décrit par "
                     "ailleurs les documents à réunir et les délais réalistes.</p>",
                "q_en": "I want to sell: how do I value my property?",
                "r_en": "<p>Write to us with the property type, the municipality and the size. We "
                        "know the prices being paid in the areas we cover and will come back to "
                        "you with a reasoned range. Our "
                        "<a href=\"vendre-son-bien-senegal.html\">selling guide</a> also sets out "
                        "the documents to gather and realistic timelines.</p>",
            },
            {
                "q": "Puis-je être prévenu quand un bien correspond à ma recherche ?",
                "r": "<p>Oui. Laissez votre email et vos critères depuis la vitrine (type, "
                     "opération, région, budget). Dès qu'un bien correspondant est publié, vous "
                     "recevez un message. Vous pouvez aussi enregistrer une recherche pour la "
                     "retrouver telle quelle à votre prochaine visite.</p>",
                "q_en": "Can I be notified when a property matches what I'm looking for?",
                "r_en": "<p>Yes. Leave your email and your criteria on the site (type, "
                        "transaction, region, budget). As soon as a matching property is "
                        "published, you get a message. You can also save a search and find it "
                        "unchanged on your next visit.</p>",
            },
            {
                "q": "Le site existe-t-il en anglais ?",
                "r": "<p>Oui. Le bouton en haut de page bascule toute la vitrine entre français "
                     "et anglais, y compris les descriptions de biens et les fiches détaillées. "
                     "Les guides sont rédigés séparément dans les deux langues plutôt que "
                     "traduits automatiquement, parce qu'ils touchent à des questions "
                     "juridiques.</p>",
                "q_en": "Is the site available in English?",
                "r_en": "<p>Yes. The button at the top of the page switches the whole site "
                        "between French and English, including property descriptions and "
                        "individual listing pages. The guides are written separately in each "
                        "language rather than machine-translated, because they deal with legal "
                        "matters.</p>",
            },
            {
                "q": "Êtes-vous une agence, et travaillez-vous avec d'autres agences ?",
                "r": "<p>PAB Immo publie ses propres biens et accueille des agences partenaires. "
                     "Les annonces publiées par une agence dont l'identité a été contrôlée "
                     "portent le badge « Agence vérifiée ». Une agence qui souhaite rejoindre le "
                     "portefeuille peut postuler depuis le formulaire en bas de la vitrine.</p>",
                "q_en": "Are you an agency, and do you work with other agencies?",
                "r_en": "<p>PAB Immo lists its own properties and hosts partner agencies. "
                        "Listings published by an agency whose identity has been checked carry "
                        "the \"Verified agency\" badge. An agency wishing to join can apply "
                        "through the form at the bottom of the site.</p>",
            },
        ],
        "titre_en": "Frequently Asked Questions About Buying, Selling and Renting with PAB Immo",
        "description_en": "Viewings, verified listings, land title status, buying from abroad, "
                          "valuing a property, alerts: answers to the questions visitors ask us "
                          "most often in Dakar and Thiès.",
        "corps_en": """
    <p>This page brings together the questions that come up most often, both about how the agency
    works and about the procedures themselves. Topics that need more room have their own guide,
    which each answer links to.</p>

    <p>A question that isn't here? Message us on WhatsApp; an answer usually comes the same
    day.</p>
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
    # Deux titres, deux rôles. Celui du H1 porte le sujet en entier — c'est ce
    # qu'on lit une fois sur la page. Celui de l'onglet et des résultats Google
    # doit tenir en 60 caractères, suffixe « | PAB Immo » compris : au-delà, la
    # fin est remplacée par des points de suspension. Tronquer le premier aurait
    # sacrifié la lisibilité de la page pour arranger le moteur.
    cle_seo = "titre_seo_en" if en else "titre_seo"
    titre_onglet = g.get(cle_seo) or couper_proprement(titre, LIMITE_TITRE - len(f" | {AGENCE}"))
    description = g["description_en"] if en else g["description"]
    description = couper_proprement(description, LIMITE_DESCRIPTION)
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
    article = {
        "@type": "Article",
        "headline": titre,
        "description": description,
        "datePublished": g["date_publication"],
        "inLanguage": "en" if en else "fr",
        "author": {"@type": "Organization", "name": AGENCE},
        "publisher": {"@type": "Organization", "name": AGENCE},
        "mainEntityOfPage": url,
    }

    # Un guide peut porter une FAQ structurée. Les questions visibles ET le
    # balisage FAQPage sont alors produits par la MÊME source : Google exige
    # que le balisage corresponde à ce que voit le visiteur, et deux listes
    # tenues séparément finiraient par diverger sans que rien ne le signale.
    faq = g.get("faq") or []
    if faq:
        blocs = "".join(
            f'''
    <details class="faq">
      <summary>{esc(f["q_en"] if en else f["q"])}</summary>
      {f["r_en"] if en else f["r"]}
    </details>''' for f in faq)
        corps = corps + f'''
    <h2>{"Frequently asked questions" if en else "Questions fréquentes"}</h2>
    {blocs}
'''
        ld = json.dumps({
            "@context": "https://schema.org",
            "@graph": [article, {
                "@type": "FAQPage",
                "inLanguage": "en" if en else "fr",
                "mainEntity": [
                    {"@type": "Question",
                     "name": f["q_en"] if en else f["q"],
                     "acceptedAnswer": {
                         "@type": "Answer",
                         # Le balisage veut du texte, pas du HTML.
                         "text": re.sub(r"\s+", " ",
                                        re.sub(r"<[^>]+>", " ",
                                               f["r_en"] if en else f["r"])).strip(),
                     }}
                    for f in faq
                ],
            }],
        }, ensure_ascii=False, indent=2)
    else:
        ld = json.dumps({"@context": "https://schema.org", **article},
                        ensure_ascii=False, indent=2)
    return f'''<!DOCTYPE html>
<html lang="{"en" if en else "fr"}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(titre_onglet)} | {AGENCE}</title>
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
  /* Bandeau collant : un visiteur arrive ici depuis Google ou un partage
     WhatsApp, pas depuis la vitrine. Statique, il disparaissait des le
     premier defilement et l'on se retrouvait sur une page sans aucun moyen
     de revenir au catalogue ni de changer de langue. z-index modeste : rien
     d'autre ne se superpose sur ces pages. */
  .bandeau{{position:sticky;top:0;z-index:50;background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;}}
  .bandeau a.marque{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a.marque span{{color:var(--accent);}}
  .bandeau-gauche{{display:flex;align-items:center;gap:10px;}}
  .bandeau a.accueil{{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;flex:none;color:#fff;border:1px solid rgba(255,255,255,.28);border-radius:9px;}}
  .bandeau a.accueil:hover{{border-color:var(--gold);color:var(--gold);}}
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
  /* FAQ dépliante. <details> natif : fonctionne sans JavaScript, se déplie à
     l'impression et reste accessible au clavier sans qu'on ait rien à câbler. */
  .faq{{border:1px solid var(--border);border-radius:var(--radius-md);margin:0 0 10px;background:var(--surface);}}
  .faq summary{{cursor:pointer;padding:14px 16px;font-weight:700;font-size:15px;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:12px;}}
  .faq summary::-webkit-details-marker{{display:none;}}
  .faq summary::after{{content:'+';font-family:'Manrope',sans-serif;font-weight:800;color:var(--gold);font-size:19px;line-height:1;flex-shrink:0;}}
  .faq[open] summary::after{{content:'\\2212';}}
  .faq summary:focus-visible{{outline:2px solid var(--gold);outline-offset:-2px;border-radius:var(--radius-md);}}
  .faq > p{{margin:0;padding:0 16px 15px;font-size:14.5px;color:var(--ink-soft);}}
  .contact{{margin-top:36px;background:linear-gradient(140deg,var(--night),var(--night-2));border-radius:var(--radius-lg);padding:24px;}}
  .contact p{{color:rgba(255,255,255,.74);font-size:14px;margin:0 0 16px;line-height:1.6;}}
  .contact h2{{color:#fff;margin:0 0 6px;}}
  .actions{{display:flex;gap:10px;flex-wrap:wrap;}}
  .actions a{{flex:1 1 200px;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;border-radius:999px;font-weight:700;font-size:14px;text-decoration:none;}}
  /* Vert WhatsApp assombri : le #25D366 de la marque ne donne que 1,98:1 avec
     du texte blanc, très en dessous du minimum AA de 4,5:1. Cette teinte reste
     dans la famille des verts WhatsApp (proche du #128C7E de leur charte) et
     passe à plus de 5:1. */
  .wa{{background:#0E7A6B;color:#fff;}} .tel{{background:var(--accent);color:#1E1607;}}
  .retour{{display:inline-block;margin-top:30px;font-size:14px;font-weight:700;color:var(--gold);}}
  footer{{background:var(--night);color:rgba(255,255,255,.5);font-size:12.5px;text-align:center;padding:26px 20px;line-height:1.9;}}
  footer a{{color:rgba(255,255,255,.72);text-decoration:none;font-weight:600;}}
  footer a:hover{{color:var(--gold);}}
  /* Pas d'opacity : elle ramenait les mentions légales à 2,84:1 sur le bleu
     nuit, très en dessous du minimum AA. La taille réduite suffit à les
     distinguer du reste du pied de page. */
  footer .reg{{font-size:11.5px;}}
</style>
<script type="application/ld+json">
{ld}
</script>
</head>
<body>
<header class="bandeau">
  <div class="bandeau-gauche">
    <!-- Le même bouton accueil que dans l'en-tête de la vitrine : depuis un
         guide, la marque seule ne se lit pas comme « retour ». -->
    <a class="accueil" href="{prefixe}/{ACCUEIL}" aria-label="{"Back to home" if en else "Revenir à l'accueil"}" title="{"Home" if en else "Accueil"}">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>
    </a>
    <a class="marque" href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  </div>
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
  {AGENCE} — {TEL_AFFICHE} · {EMAIL} · {"24/7" if en else "7j/7, 24h/24"} · {"visits by appointment" if en else "visites sur rendez-vous"}<br>
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
  /* Bandeau collant : un visiteur arrive ici depuis Google ou un partage
     WhatsApp, pas depuis la vitrine. Statique, il disparaissait des le
     premier defilement et l'on se retrouvait sur une page sans aucun moyen
     de revenir au catalogue ni de changer de langue. z-index modeste : rien
     d'autre ne se superpose sur ces pages. */
  .bandeau{{position:sticky;top:0;z-index:50;background:var(--night);padding:14px 20px;display:flex;align-items:center;justify-content:space-between;}}
  .bandeau a.marque{{color:#fff;text-decoration:none;font-family:'Manrope',sans-serif;font-weight:800;font-size:16px;}}
  .bandeau a.marque span{{color:var(--accent);}}
  .bandeau-gauche{{display:flex;align-items:center;gap:10px;}}
  .bandeau a.accueil{{display:inline-flex;align-items:center;justify-content:center;width:34px;height:34px;flex:none;color:#fff;border:1px solid rgba(255,255,255,.28);border-radius:9px;}}
  .bandeau a.accueil:hover{{border-color:var(--gold);color:var(--gold);}}
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
  /* Pas d'opacity : elle ramenait les mentions légales à 2,84:1 sur le bleu
     nuit, très en dessous du minimum AA. La taille réduite suffit à les
     distinguer du reste du pied de page. */
  footer .reg{{font-size:11.5px;}}
</style>
</head>
<body>
<header class="bandeau">
  <div class="bandeau-gauche">
    <!-- Le même bouton accueil que dans l'en-tête de la vitrine : depuis un
         guide, la marque seule ne se lit pas comme « retour ». -->
    <a class="accueil" href="{prefixe}/{ACCUEIL}" aria-label="{"Back to home" if en else "Revenir à l'accueil"}" title="{"Home" if en else "Accueil"}">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>
    </a>
    <a class="marque" href="{prefixe}/{ACCUEIL}">PAB <span>Immo</span></a>
  </div>
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
  {AGENCE} — {TEL_AFFICHE} · {EMAIL} · {"24/7" if en else "7j/7, 24h/24"} · {"visits by appointment" if en else "visites sur rendez-vous"}<br>
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
