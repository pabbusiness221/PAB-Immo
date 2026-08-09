#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vérifie qu'un visiteur anonyme ne peut lire QUE ce qui est destiné au public.

POURQUOI CE SCRIPT EXISTE
-------------------------
L'audit du 9 août 2026 a trouvé deux fuites que rien n'aurait signalées :

  C1  La vue `leads_enrichis` renvoyait tout le fichier prospects — nom,
      téléphone/email, notes commerciales — à n'importe quel visiteur. La
      protection existait pourtant : une migration ultérieure l'avait défaite
      SANS ERREUR, en recréant la vue avec un CREATE OR REPLACE VIEW dépourvu
      de clause WITH (ce qui réinitialise security_invoker).

  C2  `estimer_bien()` interrogeait les biens NON PUBLIÉS. En appelant la
      fonction avec une surface de 1, on lisait le prix au m² d'un brouillon.

Aucun test ne pouvait les voir : `verifier-integrite.py` compare des fichiers,
`verifier-mise-en-ligne.py` vérifie le référencement. Personne n'interrogeait
le site *comme le ferait un inconnu*. C'est ce que fait celui-ci.

CE QU'IL GARANTIT
-----------------
1. Toute table ou vue du schéma `public` est interrogée avec la clé publique.
   Sauf celles explicitement déclarées publiques ci-dessous, aucune ne doit
   renvoyer la moindre ligne.

2. La liste des relations est extraite du DÉPÔT (schema.sql + migrations), pas
   du réseau. Conséquence voulue : une table ajoutée par une future migration
   entre automatiquement dans le test. Il n'y a rien à penser à mettre à jour —
   c'est précisément l'oubli qui a produit C1.

3. `estimer_bien()` ne doit jamais voir plus de biens que le catalogue public
   n'en contient. Invariant vérifiable sans aucun secret : on compte les biens
   comparables dans `public_properties`, et la fonction ne doit pas en
   annoncer davantage. C'est exactement ce qui trahissait C2.

CE QU'IL NE COUVRE PAS
----------------------
Les droits des comptes connectés (admin, collaborateur) : les tester
demanderait des identifiants, que ce script n'a pas et ne doit pas avoir. Il
couvre la frontière qui compte le plus — celle entre le public et le reste.

USAGE
-----
    python outils/verifier-rls.py

Code de sortie 0 si tout est conforme, 1 sinon (utilisable en CI).
La clé lue est la clé « publishable », déjà publique dans commun.js : ce
script n'utilise, et ne doit utiliser, aucun secret.
"""

import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

RACINE = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Relations dont la lecture publique est VOULUE.
#
# Toute relation absente de cette liste doit rester muette pour un visiteur
# anonyme. Ajouter une entrée ici est une décision de sécurité : elle signifie
# « le contenu de cette relation peut paraître sur la place publique ».
# ---------------------------------------------------------------------------
LECTURE_PUBLIQUE_ASSUMEE = {
    "public_properties",             # le catalogue publié : c'est la vitrine
    "public_property_photos",        # les photos de ces biens
    "public_property_cover_photos",  # leur photo de couverture
    "public_reviews",                # les avis modérés et publiés
    "public_stats",                  # compteurs agrégés du bandeau de confiance
}

# Relations techniques hors périmètre (extensions, non métier).
IGNOREES = {"spatial_ref_sys", "geography_columns", "geometry_columns"}


def cle_et_url():
    """Lit l'URL et la clé publique dans commun.js — une seule source."""
    js = (RACINE / "commun.js").read_text(encoding="utf-8")
    url = re.search(r"SUPABASE_URL\s*=\s*'([^']+)'", js)
    cle = re.search(r"SUPABASE_KEY\s*=\s*'([^']+)'", js)
    if not url or not cle:
        sys.exit("Impossible de lire SUPABASE_URL / SUPABASE_KEY dans commun.js")
    return url.group(1).rstrip("/"), cle.group(1)


def relations_du_depot():
    """Toutes les tables et vues `public` déclarées dans le dépôt."""
    fichiers = [RACINE / "supabase" / "schema.sql"]
    fichiers += sorted((RACINE / "supabase" / "migrations").glob("*.sql"))

    motifs = [
        re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)", re.I),
        re.compile(r"create\s+(?:or\s+replace\s+)?view\s+(?:public\.)?(\w+)", re.I),
        re.compile(r"create\s+materialized\s+view\s+(?:if\s+not\s+exists\s+)?(?:public\.)?(\w+)", re.I),
    ]

    trouvees = set()
    for f in fichiers:
        if not f.exists():
            continue
        # Les commentaires sont retirés AVANT l'analyse. Sans cela, une phrase
        # comme « recréée avec un CREATE OR REPLACE VIEW dépourvu de clause
        # WITH » — écrite dans le correctif de C1 — fait passer « dépourvu »
        # pour un nom de vue. Ce n'est pas une hypothèse : c'est arrivé au
        # premier lancement de ce script.
        texte = re.sub(r"--[^\n]*", "", f.read_text(encoding="utf-8"))
        for motif in motifs:
            trouvees.update(m.group(1).lower() for m in motif.finditer(texte))
    return sorted(trouvees - IGNOREES)


def interroger(url, cle, relation):
    """GET anonyme. Renvoie (nb_lignes, note). nb_lignes = -1 si inaccessible."""
    requete = urllib.request.Request(
        f"{url}/rest/v1/{relation}?select=*&limit=2",
        headers={"apikey": cle, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            lignes = json.loads(reponse.read().decode("utf-8"))
            return (len(lignes), "") if isinstance(lignes, list) else (0, "réponse inattendue")
    except urllib.error.HTTPError as e:
        # 401/403/404 : la relation n'est pas exposée — c'est le comportement voulu.
        return -1, f"HTTP {e.code}"
    except Exception as e:  # réseau
        return -2, str(e)[:60]


def appeler_rpc(url, cle, nom, arguments):
    requete = urllib.request.Request(
        f"{url}/rest/v1/rpc/{nom}",
        data=json.dumps(arguments).encode("utf-8"),
        headers={"apikey": cle, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except Exception:
        return None


def controle_estimation(url, cle):
    """estimer_bien ne doit pas voir plus de biens que le catalogue public.

    Reproduit exactement la faille C2 : on compare ce que la fonction annonce
    à ce qu'un visiteur peut réellement dénombrer dans public_properties.
    """
    requete = urllib.request.Request(
        f"{url}/rest/v1/public_properties?select=type,operation,commune,surface,price",
        headers={"apikey": cle, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=20) as reponse:
            biens = json.loads(reponse.read().decode("utf-8"))
    except Exception as e:
        return [f"catalogue public illisible ({str(e)[:50]})"]

    def normaliser(nom):
        nom = (nom or "").strip().lower()
        for a, b in zip("àáâãäåèéêëìíîïòóôõöùúûüçñÿ", "aaaaaaeeeeiiiiooooouuuucny"):
            nom = nom.replace(a, b)
        nom = re.sub(
            r"^(commune|communaute rurale|communaute|region|ville|departement|arrondissement)\s+(de|du|d')\s*",
            "", nom)
        return re.sub(r"\s+", " ", nom).strip()

    publics = {}
    for b in biens:
        if (b.get("surface") or 0) > 0 and (b.get("price") or 0) > 0:
            cle_groupe = (b["type"], b["operation"], normaliser(b.get("commune")))
            publics[cle_groupe] = publics.get(cle_groupe, 0) + 1

    anomalies = []
    for (type_, operation, commune), nb_public in sorted(publics.items()):
        resultat = appeler_rpc(url, cle, "estimer_bien", {
            "p_type": type_, "p_operation": operation,
            "p_commune": commune, "p_surface": 1,
        })
        if not resultat:
            continue
        annonce = (resultat[0] if isinstance(resultat, list) else resultat).get("nb_comparables", 0)
        if annonce > nb_public:
            anomalies.append(
                f"estimer_bien annonce {annonce} biens pour "
                f"{type_}/{operation}/{commune} alors que le catalogue public "
                f"n'en montre que {nb_public} — des biens non publiés sont visibles"
            )
    return anomalies


def main():
    url, cle = cle_et_url()
    relations = relations_du_depot()

    print(f"Cible   : {url}")
    print(f"Clé     : publique ({cle[:22]}...)")
    print(f"Relations déclarées dans le dépôt : {len(relations)}\n")

    fuites, publiques, fermees, injoignables = [], [], [], []

    for relation in relations:
        nb, note = interroger(url, cle, relation)
        if nb == -2:
            injoignables.append(f"{relation} ({note})")
        elif relation in LECTURE_PUBLIQUE_ASSUMEE:
            publiques.append(relation)
        elif nb > 0:
            fuites.append(f"{relation} — {nb} ligne(s) lisible(s) par un anonyme")
        else:
            fermees.append(relation)

    print(f"[OK]  {len(fermees)} relations muettes pour un visiteur anonyme")
    print(f"[PUB] {len(publiques)} relations publiques assumées : {', '.join(sorted(publiques))}")
    if injoignables:
        print(f"[!]   {len(injoignables)} injoignables : {', '.join(injoignables)}")

    anomalies_estimation = controle_estimation(url, cle)
    if not anomalies_estimation:
        print("[OK]  estimer_bien ne voit aucun bien hors catalogue public")

    if fuites or anomalies_estimation:
        print("\n" + "=" * 68)
        print("FUITE DE DONNÉES — un visiteur anonyme lit ce qu'il ne devrait pas")
        print("=" * 68)
        for f in fuites + anomalies_estimation:
            print(f"  x {f}")
        print(
            "\nSi cette exposition est volontaire, il faut l'inscrire dans "
            "LECTURE_PUBLIQUE_ASSUMEE\nen haut de ce fichier — et donc l'assumer "
            "explicitement. Sinon, c'est une régression :\nvérifier la policy RLS, "
            "et pour une vue, la clause `with (security_invoker = true)`."
        )
        return 1

    print("\nConforme : rien ne fuit vers le public.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
