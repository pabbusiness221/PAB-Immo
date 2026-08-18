#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fige le comportement actuel des deux pages, pour qu'une modification ne le
change pas sans qu'on le voie.

Pourquoi ce script existe
-------------------------
vitrine.html et Portefeuille-Immo.html font ensemble près de 7 000 lignes, et
rien ne les vérifie. Les pannes les plus fréquentes ici ne provoquent aucune
erreur visible au chargement : un identifiant renommé et c'est un bouton qui
ne répond plus ; une fonction partagée recopiée localement et les deux pages
divergent en silence ; un oubli de esc() et le texte d'un visiteur devient du
code exécuté.

Ces trois pannes ont un point commun : la page s'affiche normalement. Seul
l'usage révèle le problème, souvent chez un vrai client.

Ce script ne teste pas ce que le code DEVRAIT faire — il enregistre ce qu'il
fait AUJOURD'HUI et prévient si cela change. C'est le filet minimum avant
toute réorganisation du code : sans lui, on ne peut pas savoir si un
déplacement de fonction a cassé quelque chose.

Il ne contacte pas le réseau et ne lit pas la base : uniquement les fichiers
du dépôt. Il est donc rapide et donne toujours le même résultat.

Utilisation
-----------
    python outils/verifier-integrite.py

Sortie 0 si tout est conforme, 1 sinon — utilisable dans une action GitHub.
"""

import os
import re
import sys
from html.parser import HTMLParser

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# La vitrine s'appelle vitrine.html en maintenance et Biens-Immo.html une fois
# en ligne : on prend celle qui existe, comme le font generer-pages.py et
# verifier-mise-en-ligne.py. Sans cela, l'outil signalait une page absente
# apres la bascule et ne verifiait plus la vitrine du tout.
VITRINE = next((n for n in ("Biens-Immo.html", "vitrine.html")
                if os.path.exists(os.path.join(RACINE, n))), "vitrine.html")
PAGES = [VITRINE, "Portefeuille-Immo.html"]
PARTAGES = ["commun.js", "commun.css"]

# Champs saisis par un visiteur. Tout ce qui vient d'eux doit passer par esc()
# avant d'entrer dans du HTML : c'est la seule barrière entre un avis et du
# code exécuté dans le navigateur des autres visiteurs.
CHAMPS_VISITEUR = [
    "comment", "author_name", "name", "contact", "message",
    "notes", "display_name", "contact_name",
]

anomalies = []
remarques = []


def controle(condition, message, grave=True):
    """Enregistre une anomalie sans s'arrêter : on veut la liste complète,
    pas la première erreur rencontrée."""
    if not condition:
        (anomalies if grave else remarques).append(message)
    return condition


def lire(nom):
    with open(os.path.join(RACINE, nom), encoding="utf-8") as f:
        return f.read()


def sans_scripts(html):
    """Retire les blocs <script> pour ne garder que le balisage réellement
    présent au chargement. Indispensable : les gabarits JS contiennent des
    id= qui ne coexistent jamais à l'écran (branches d'un if), et les
    confondre avec du balisage statique produit de faux doublons."""
    return re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)


def noms_definis(source):
    """Noms définis au premier niveau d'un fichier JS."""
    return set(re.findall(r"^(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)",
                          source, re.M))


class VerificateurHtml(HTMLParser):
    """Détecte les balises non fermées et les fermetures orphelines."""
    ORPHELINES = {"br", "hr", "img", "input", "meta", "link", "source",
                  "area", "base", "col", "embed", "param", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pile = []
        self.erreurs = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.ORPHELINES:
            self.pile.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        if tag in self.ORPHELINES:
            return
        if not self.pile:
            self.erreurs.append(f"</{tag}> ligne {self.getpos()[0]} sans ouverture")
            return
        if self.pile[-1][0] == tag:
            self.pile.pop()
        elif any(t == tag for t, _ in self.pile):
            while self.pile and self.pile[-1][0] != tag:
                oublie, ligne = self.pile.pop()
                self.erreurs.append(f"<{oublie}> ouvert ligne {ligne}, jamais fermé")
            if self.pile:
                self.pile.pop()
        else:
            self.erreurs.append(f"</{tag}> ligne {self.getpos()[0]} sans ouverture")


# ---- Content-Security-Policy : la politique couvre-t-elle l'usage reel ? ---
def csp_de(html):
    """Extrait la politique du <meta http-equiv="Content-Security-Policy">,
    sous la forme {directive: [sources]}. None si la balise est absente."""
    m = re.search(r'http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html)
    if not m:
        return None
    politique = {}
    for morceau in m.group(1).split(";"):
        morceau = morceau.strip()
        if not morceau:
            continue
        jetons = morceau.split()
        politique[jetons[0]] = jetons[1:]
    return politique


def ressources_externes(html):
    """Recense les ressources externes que la page charge reellement, telles
    qu'observees dans le code : scripts et feuilles de style poses dans le
    HTML, CDN de repli charges dynamiquement (ex. ensureChartJs), tuiles de
    carte Leaflet, appels fetch() explicites. Ne couvre pas ce que construit
    le SDK Supabase en interne, ni les sous-ressources d'une CSS externe
    (fonts.gstatic.com, chargee depuis la CSS de Google Fonts) : un « rien de
    bloque » ne garantit donc pas une couverture totale, seulement l'absence
    des ecarts visibles dans le code source."""
    vues = []
    for u in re.findall(r'<script[^>]+src="(https://[^"]+)"', html):
        vues.append(("script-src", u))
    for u in re.findall(r'<link[^>]+rel="stylesheet"[^>]+href="(https://[^"]+)"', html):
        vues.append(("style-src", u))
    for u in re.findall(r"'(https://[^']+\.js)'", html):
        vues.append(("script-src", u))
    for u in re.findall(r"tileLayer\('(https://[^']+)'", html):
        vues.append(("img-src", u.replace("{s}.", "a.")))
    for u in re.findall(r"fetch\(\s*[`'\"](https://[^`'\"]+)", html):
        vues.append(("connect-src", u))
    return vues


def csp_autorise(politique, directive, url):
    """Une source de la directive (ou de default-src, en repli) couvre-t-elle
    cette URL ? Gere le seul joker que ce projet utilise : *.domaine."""
    hote = re.sub(r"^https?://", "", url).split("/", 1)[0]
    for source in politique.get(directive) or politique.get("default-src", []):
        source = source.strip("'")
        if source in ("self", "unsafe-inline", "none") or source == "data:":
            continue
        hote_source = re.sub(r"^https?://", "", source)
        if hote_source.startswith("*."):
            if hote.endswith(hote_source[1:]):
                return True
        elif hote_source == hote:
            return True
    return False


def main():
    for nom in PAGES + PARTAGES:
        if not os.path.exists(os.path.join(RACINE, nom)):
            anomalies.append(f"{nom} est absent du dépôt.")
            return rendre_verdict()

    commun_js = lire("commun.js")
    partages = noms_definis(commun_js)
    print(f"commun.js definit {len(partages)} noms partages\n")

    for page in PAGES:
        html = lire(page)
        statique = sans_scripts(html)
        print(f"--- {page} ---")

        # --- 1. Chaque getElementById vise un element qui existe -------------
        # La panne la plus courante : on renomme ou supprime un element, la
        # page s'affiche toujours, mais getElementById renvoie null et le
        # gestionnaire associe plante au premier clic.
        ids_statiques = set(re.findall(r'\bid="([A-Za-z0-9_\-]+)"', statique))
        ids_gabarits = set(re.findall(r"""id=["'`]?\$?\{?([A-Za-z0-9_\-]+)""", html))
        # Un element cree en JS recoit son identifiant par affectation
        # (bloc.id = 'monBloc') et non par un attribut : sans cette lecture,
        # le controle le declarait introuvable et signalait une panne
        # imaginaire a chaque bandeau construit a la volee.
        ids_affectes = set(re.findall(
            r"""\.id\s*=\s*['"]([A-Za-z0-9_\-]+)['"]""", html))
        # Meme cas pour setAttribute('id', ...), plus rare mais equivalent.
        ids_affectes |= set(re.findall(
            r"""setAttribute\(\s*['"]id['"]\s*,\s*['"]([A-Za-z0-9_\-]+)['"]""", html))
        connus = ids_statiques | ids_gabarits | ids_affectes
        references = set(re.findall(
            r"""getElementById\(\s*['"]([A-Za-z0-9_\-]+)['"]\s*\)""", html))
        orphelines = sorted(references - connus)
        print(f"  {len(references)} references getElementById, "
              f"{len(ids_statiques)} id statiques")
        controle(not orphelines,
                 f"{page} : getElementById vise {len(orphelines)} element(s) "
                 f"qui n'existent nulle part : {orphelines[:8]}. Le bouton ou "
                 f"le panneau concerne ne repondra plus.")

        # --- 2. Pas deux fois le meme id dans le balisage statique -----------
        # Deux elements portant le meme id : getElementById en renvoie un seul,
        # arbitrairement. L'autre devient inatteignable.
        tous = re.findall(r'\bid="([A-Za-z0-9_\-]+)"', statique)
        doublons = sorted({i for i in tous if tous.count(i) > 1})
        controle(not doublons,
                 f"{page} : id en double dans le balisage : {doublons}. "
                 f"getElementById n'en atteindra qu'un seul.")

        # --- 3. Les fonctions partagees ne sont pas recopiees localement -----
        # Une copie locale prend le pas sur commun.js : corriger la version
        # partagee ne corrige alors qu'une page sur deux, sans aucun signal.
        locales = noms_definis(re.sub(r"^.*?<script\b[^>]*>", "", html, flags=re.S | re.I))
        redefinis = sorted(locales & partages)
        controle(not redefinis,
                 f"{page} : {redefinis} est deja fourni par commun.js et se "
                 f"trouve redefini ici. La copie locale gagne : corriger "
                 f"commun.js ne corrigerait plus cette page.")

        # --- 4. Le code partage est bien charge ------------------------------
        for fichier in PARTAGES:
            controle(fichier in html,
                     f"{page} : {fichier} n'est plus charge. Toutes les "
                     f"fonctions communes deviennent introuvables.")

        # --- 5. Le texte des visiteurs passe par esc() -----------------------
        # Sans esc(), un avis contenant du HTML s'execute dans le navigateur
        # des autres visiteurs.
        # On ne vise que les acces a une ligne de donnees, ecrits ici avec un
        # alias court (a.comment, p.name, m.contact...). Sans cette limite, le
        # controle attrapait file.name (le fichier choisi par l'admin) et
        # error.message (une erreur Supabase), qui ne viennent pas d'un
        # visiteur et n'ont rien a faire dans cette liste.
        nus = []
        for champ in CHAMPS_VISITEUR:
            motif = r"\$\{([^}]*?\b[A-Za-z_$][\w$]{0,2}\.%s\b[^}]*)\}" % re.escape(champ)
            for expr in re.findall(motif, html):
                if "esc(" not in expr:
                    nus.append(f"{champ} dans ${{{expr.strip()[:60]}}}")
        controle(not nus,
                 f"{page} : texte de visiteur insere sans esc() :\n      "
                 + "\n      ".join(nus[:6]))

        # --- 6. Le balisage est bien forme -----------------------------------
        v = VerificateurHtml()
        v.feed(statique)
        restantes = [f"<{t}> ouvert ligne {l}, jamais ferme" for t, l in v.pile]
        controle(not (v.erreurs or restantes),
                 f"{page} : balises mal equilibrees :\n      "
                 + "\n      ".join((v.erreurs + restantes)[:6]))

        # --- 7. La CSP autorise tout ce que la page charge vraiment -----------
        # Une ressource bloquee par la CSP ne provoque aucune erreur visible
        # dans l'usage courant : la page s'affiche, mais amputee. C'est ainsi
        # que leaflet.css est passe inapercu une fois — les tuiles de carte se
        # chargeaient (img-src les autorisait), mais la feuille de style qui
        # les POSITIONNE etait coupee : carte visuellement fausse, aucune
        # alerte. Verifier « la ressource se charge » ne suffit pas ; il faut
        # verifier que la politique la couvre.
        politique = csp_de(html)
        controle(politique is not None,
                 f"{page} : plus aucune Content-Security-Policy. Les origines "
                 f"externes ne sont plus limitees.")
        if politique:
            bloquees = []
            for directive, url in ressources_externes(html):
                if not csp_autorise(politique, directive, url):
                    bloquees.append(f"{directive} <- {url[:80]}")
            controle(not bloquees,
                     f"{page} : la CSP bloque des ressources que la page "
                     f"charge :\n      " + "\n      ".join(bloquees[:6])
                     + "\n      La page s'affichera amputee, sans erreur visible.")
        print()

    # --- 8. Aucun secret dans les fichiers servis aux visiteurs --------------
    # La cle de service donne un acces TOTAL a la base, RLS comprise. Elle ne
    # doit vivre que dans les secrets des fonctions Edge.
    for nom in PAGES + PARTAGES:
        contenu = lire(nom)
        controle("service_role" not in contenu and "SERVICE_ROLE" not in contenu,
                 f"{nom} contient une reference a la cle de service. Cette cle "
                 f"contourne toutes les regles de securite et ne doit jamais "
                 f"figurer dans un fichier servi aux visiteurs.")
        controle(not re.search(r"\bsb_secret_[A-Za-z0-9_\-]+", contenu),
                 f"{nom} contient une cle secrete Supabase en clair.")

    return rendre_verdict()


def rendre_verdict():
    for r in remarques:
        print(f"  [note] {r}")
    if anomalies:
        print(f"\n{len(anomalies)} anomalie(s) :\n")
        for a in anomalies:
            # Marqueurs ASCII : la console Windows est en cp1252 et refuserait
            # des symboles decoratifs, au moment precis ou le script a quelque
            # chose d'important a dire.
            print(f"  [!] {a}")
        print("\nComportement modifie : verifier que c'est voulu.")
        return 1
    print("Conforme : le comportement fige n'a pas change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
