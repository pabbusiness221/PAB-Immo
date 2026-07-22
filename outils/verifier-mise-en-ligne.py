#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vérifie que le site est cohérent avec son mode : maintenance ou en ligne.

Pourquoi ce script existe
-------------------------
La bascule entre maintenance et publication touche cinq endroits sans lien
mécanique entre eux : le réglage EN_MAINTENANCE, les balises noindex des pages
d'accueil, celles des fiches, le sitemap, et les fichiers présents à la racine.
En oublier un ne provoque aucune erreur : le site a l'air normal, mais il reste
invisible pour Google, ou il publie des annonces qui n'existent plus.

Ce script relit tout ce qui est écrit sur le disque et le confronte au mode
déclaré. Il ne contacte ni Supabase ni le réseau : il vérifie ce qui sera
réellement servi aux visiteurs, pas ce que la base contient.

Utilisation
-----------
    python outils/verifier-mise-en-ligne.py

Sortie 0 si tout est cohérent, 1 sinon — utilisable dans une action GitHub.
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.join(RACINE, "bien")

anomalies = []
remarques = []


def controle(condition, message, grave=True):
    """Enregistre une anomalie. On ne s'arrête pas à la première : mieux vaut
    présenter la liste complète que faire relancer le script cinq fois."""
    if not condition:
        (anomalies if grave else remarques).append(message)
    return condition


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return f.read()


def mode_declare():
    """Lit EN_MAINTENANCE dans le générateur plutôt que de le demander : c'est
    ce réglage qui a produit les pages, c'est donc lui la référence."""
    src = lire(os.path.join(RACINE, "outils", "generer-pages.py"))
    m = re.search(r"^EN_MAINTENANCE\s*=\s*(True|False)", src, re.M)
    assert m, "EN_MAINTENANCE introuvable dans outils/generer-pages.py"
    return m.group(1) == "True"


def main():
    maintenance = mode_declare()
    accueil = "vitrine.html" if maintenance else "Biens-Immo.html"
    print(f"Mode déclaré : {'MAINTENANCE' if maintenance else 'EN LIGNE'}")
    print(f"Accueil du catalogue attendu : {accueil}\n")

    # --- 1. Fichiers de la racine -------------------------------------------
    controle(os.path.exists(os.path.join(RACINE, accueil)),
             f"{accueil} est absent : c'est la page d'accueil du catalogue.")

    if maintenance:
        for page in ("Biens-Immo.html", "index.html"):
            chemin = os.path.join(RACINE, page)
            if controle(os.path.exists(chemin),
                        f"{page} est absent : c'est la page de maintenance."):
                controle("noindex" in lire(chemin),
                         f"{page} est indexable. Google retiendrait « site en cours "
                         f"de mise à jour » comme résultat pour « PAB Immo ».")
    else:
        controle(not os.path.exists(os.path.join(RACINE, "vitrine.html")),
                 "vitrine.html existe encore. En ligne, le catalogue doit s'appeler "
                 "Biens-Immo.html — c'est l'adresse déjà partagée par WhatsApp et "
                 "par les emails d'alerte. Deux copies, c'est du contenu dupliqué.")
        controle(not os.path.exists(os.path.join(RACINE, "index.html")),
                 "index.html existe encore : c'est la page de maintenance, elle "
                 "s'afficherait à la place du catalogue.")
        controle("noindex" not in lire(os.path.join(RACINE, accueil)),
                 f"{accueil} porte encore une balise noindex. Tant qu'elle est là, "
                 f"tout le reste du référencement est sans effet.")

    # --- 2. Fiches générées -------------------------------------------------
    if not os.path.isdir(DOSSIER):
        anomalies.append("Le dossier bien/ n'existe pas. Lancer generer-pages.py.")
        return rendre_verdict()

    fiches = sorted(f for f in os.listdir(DOSSIER)
                    if f.endswith(".html") and f != "index.html")
    print(f"{len(fiches)} fiches dans bien/")
    controle(bool(fiches), "Aucune fiche générée : le catalogue serait invisible.")

    for f in fiches + (["index.html"] if os.path.exists(os.path.join(DOSSIER, "index.html")) else []):
        html = lire(os.path.join(DOSSIER, f))
        robots = re.search(r'<meta name="robots" content="([^"]+)"', html)
        valeur = robots.group(1) if robots else ""
        # Chercher « index, follow » dans la valeur serait un piège : cette
        # chaîne est contenue dans « noindex, follow ». Une première version de
        # ce contrôle déclarait donc les 24 fiches conformes alors qu'elles
        # portaient exactement l'interdiction qu'il devait détecter. On teste
        # la présence de « noindex », qui elle est sans ambiguïté.
        controle(robots and ("noindex" in valeur) == maintenance,
                 f"bien/{f} : balise robots « {valeur or 'absente'} », attendu "
                 f"« {'noindex' if maintenance else 'index'} ». Relancer generer-pages.py.")
        controle('<link rel="canonical"' in html,
                 f"bien/{f} : pas d'adresse canonique.")
        controle('application/ld+json' in html,
                 f"bien/{f} : pas de données structurées.")

    controle(os.path.exists(os.path.join(DOSSIER, "index.html")),
             "bien/index.html est absent. C'est la seule page en HTML pur qui "
             "relie les fiches entre elles ; sans elle, Google n'a aucun chemin "
             "d'exploration vers le catalogue.")

    # --- 3. Liens internes --------------------------------------------------
    presentes = set(fiches)
    morts = []
    for f in os.listdir(DOSSIER):
        if not f.endswith(".html"):
            continue
        html = lire(os.path.join(DOSSIER, f))
        for cible in re.findall(r'class="voisin" href="([^"]+)"', html):
            if cible not in presentes:
                morts.append(f"bien/{f} → bien/{cible}")
    controle(not morts, "Liens internes morts :\n      " + "\n      ".join(morts[:10]))

    if fiches:
        cibles = {c for f in os.listdir(DOSSIER) if f.endswith(".html")
                  for c in re.findall(r'class="voisin" href="([^"]+)"',
                                      lire(os.path.join(DOSSIER, f)))}
        orphelines = presentes - cibles
        controle(not orphelines,
                 f"{len(orphelines)} fiche(s) qu'aucun lien n'atteint : "
                 + ", ".join(sorted(orphelines)[:5]))

    # --- 4. Manifeste -------------------------------------------------------
    chemin_manifeste = os.path.join(DOSSIER, "index.json")
    if controle(os.path.exists(chemin_manifeste),
                "bien/index.json est absent : la vitrine ne pourra ouvrir aucune fiche."):
        manifeste = json.loads(lire(chemin_manifeste))
        absentes = [v for v in manifeste.values() if v not in presentes]
        controle(not absentes,
                 f"bien/index.json annonce {len(absentes)} fiche(s) qui n'existent "
                 f"pas : {absentes[:5]}")
        controle(len(manifeste) == len(fiches),
                 f"bien/index.json liste {len(manifeste)} références pour "
                 f"{len(fiches)} fiches sur le disque.")

    # --- 5. Sitemap ---------------------------------------------------------
    chemin_sitemap = os.path.join(RACINE, "sitemap.xml")
    if controle(os.path.exists(chemin_sitemap), "sitemap.xml est absent."):
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        racine_xml = ET.parse(chemin_sitemap).getroot()
        adresses = [n.text for n in racine_xml.findall(".//s:loc", ns)]
        print(f"{len(adresses)} adresses dans sitemap.xml")

        # L'adresse de la page d'index se termine par « /bien/ » : la découper
        # donne une chaîne vide, qu'il ne faut pas confondre avec une fiche.
        declarees = {a.rsplit("/bien/", 1)[1] for a in adresses
                     if "/bien/" in a and not a.endswith("/bien/")}
        controle(declarees <= presentes,
                 f"Le sitemap annonce des fiches absentes du disque : "
                 f"{sorted(declarees - presentes)[:5]}. C'est le symptôme d'un "
                 f"generer-pages.py non relancé, ou d'un git add qui n'a pas "
                 f"enregistré les suppressions.")
        controle(presentes <= declarees,
                 f"Des fiches ne sont pas dans le sitemap : "
                 f"{sorted(presentes - declarees)[:5]}")
        controle(any(a.endswith(f"/{accueil}") for a in adresses),
                 f"{accueil} n'est pas dans le sitemap.")
        controle(any(a.endswith("/bien/") for a in adresses),
                 "La page d'index bien/ n'est pas dans le sitemap.")

    return rendre_verdict()


def rendre_verdict():
    print()
    for r in remarques:
        print(f"  [note] {r}")
    if anomalies:
        print(f"\n{len(anomalies)} anomalie(s) :\n")
        for a in anomalies:
            # Marqueurs en ASCII : la console Windows est en cp1252 et refuse
            # les symboles décoratifs, ce qui ferait planter le script au
            # moment précis où il a quelque chose d'important à dire.
            print(f"  [!] {a}")
        print("\nNe pas publier en l'état.")
        return 1
    print("Tout est cohérent avec le mode déclaré.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
