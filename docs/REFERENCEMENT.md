# Référencement — PAB Immo

Dernière mise à jour : **22 juillet 2026**

---

## 1. Comment fonctionne le référencement de ce site

La vitrine construit ses annonces en JavaScript. Dans son code source, il n'y a
donc **aucune annonce, aucun prix, aucune commune** — Google n'a rien à indexer.

C'est pourquoi `outils/generer-pages.py` produit, en plus de la vitrine, **une
page statique par bien** : titre, prix, superficie, description et photos écrits
en dur dans le HTML, sans dépendre d'aucun JavaScript.

```
bien/appartement-a-louer-almadies-bien-2024-055.html
bien/terrain-a-vendre-keur-moussa-tf-2026-3724.html
```

Ce sont **ces pages** que Google indexe et positionne, pas la vitrine. La
vitrine reste l'outil de navigation pour les visiteurs ; les pages générées sont
les portes d'entrée depuis les moteurs de recherche.

### Comment elles sont reliées

Une page que rien ne relie au reste est un cul-de-sac : Google la découvre par
le sitemap, mais rien ne lui dit qu'elle compte, et le visiteur qui y atterrit
n'a nulle part où aller. Trois liaisons évitent ça :

| Fichier | Rôle |
|---|---|
| `bien/index.html` | Index statique du catalogue. C'est la seule page en HTML pur qui pointe vers les 24 fiches — la vitrine, construite en JavaScript, n'affiche aucun lien dans son code source. |
| Bloc « Autres biens » | Trois biens proches en fin de chaque fiche, classés par commune, puis type, puis opération. |
| `bien/index.json` | Liste des fiches réellement écrites. La vitrine s'en sert pour ouvrir la fiche d'un bien ; comme elle ne lit que ce qui existe, elle ne peut pas fabriquer de lien mort. |

C'est aussi ce qui répare l'aperçu de partage : le bouton « Partager » envoie
l'adresse de la fiche, la seule dont le code source porte la photo, le titre et
le prix du bien. WhatsApp et Facebook lisent le code source sans exécuter de
JavaScript — un lien vers la vitrine ne leur montrait que l'image générique.

### À relancer après chaque changement

```bash
python outils/generer-pages.py
```

Un bien ajouté, modifié, dépublié ou archivé ne sera reflété qu'après un nouveau
passage du script. Le dossier `bien/` est reconstruit de zéro à chaque fois :
un bien dépublié ne laisse pas de page fantôme derrière lui.

---

## 2. Deux pièges propres à GitHub Pages

### `robots.txt` n'est pas lu

Les robots ne consultent que `https://pabbusiness221.github.io/robots.txt`,
à la **racine du domaine** — qui appartient à un autre dépôt et renvoie 404.
Le fichier `robots.txt` de ce dépôt est servi, mais **ignoré**.

Conséquence : il ne bloque rien et ne déclare rien. Il ne deviendra effectif
qu'avec un nom de domaine propre (`pabimmo.sn` par exemple).

Le sitemap doit donc être déclaré **à la main dans Search Console**, et la
suspension d'indexation repose sur les balises `noindex` des pages.

### C'est de toute façon la bonne méthode

Un `robots.txt` bloquant empêcherait Google de **lire** le `noindex`. Il pourrait
alors indexer l'adresse malgré tout, sur la foi d'un lien externe, en affichant
un résultat vide. Pour retirer une page de l'index, il faut que Google puisse la
visiter et y lire l'interdiction.

---

## 3. Raccorder Google Search Console

Sans Search Console, on travaille à l'aveugle : aucune idée de ce qui est
indexé, ni sur quelles recherches le site apparaît.

### Étape 1 — Créer la propriété

Sur [search.google.com/search-console](https://search.google.com/search-console) :

1. **Ajouter une propriété** → choisir **Préfixe d'URL** (et non « Domaine »,
   qui exige un accès DNS que github.io ne permet pas)
2. Saisir exactement :
   ```
   https://pabbusiness221.github.io/PAB-Immo/
   ```

### Étape 2 — Valider la propriété

Deux méthodes possibles, au choix.

**Balise HTML** (la plus simple à maintenir) — Google affiche une ligne du type :

```html
<meta name="google-site-verification" content="AbCdEf123..." />
```

Copier **uniquement la valeur du `content`**, la coller dans
`outils/generer-pages.py` :

```python
GOOGLE_VERIFICATION = "AbCdEf123..."
```

puis relancer le script. La balise doit aussi figurer dans `index.html` et
`vitrine.html` — demandez-la, c'est une ligne à ajouter.

**Fichier HTML** — Google fournit un fichier `googleXXXXXXXX.html` à déposer
à la racine du dépôt, puis à pousser. Aucune modification de code.

> La validation fonctionne même avec les pages en `noindex` : ce sont deux
> mécanismes indépendants.

### Étape 3 — Déclarer le sitemap

Dans Search Console, menu **Sitemaps**, saisir :

```
sitemap.xml
```

L'adresse complète est `https://pabbusiness221.github.io/PAB-Immo/sitemap.xml`
(déjà en ligne, XML validé, 25 adresses).

---

## 4. À quoi s'attendre

**Tant que le site est en maintenance**, Search Console signalera les pages
comme « Exclues par la balise noindex ». C'est normal et voulu. La chaîne est
en place, elle ne produira d'effet qu'au retour en ligne.

**Au retour en ligne** : passer `EN_MAINTENANCE = False` dans le script, le
relancer, pousser. Puis dans Search Console, demander une indexation pour
quelques pages afin d'amorcer.

**Ensuite** : compter en semaines, pas en jours. Google découvre, explore, puis
indexe. Les premiers résultats apparaissent généralement sous 2 à 6 semaines
pour un site neuf.

---

## 5. Sur quelles recherches viser

Avec 24 biens, se battre sur « immobilier Sénégal » ou « agence immobilière
Dakar » est perdu d'avance : ces requêtes sont tenues par des portails à
plusieurs milliers d'annonces.

Les requêtes atteignables sont **précises**, et ce sont elles qui amènent des
acheteurs sérieux :

- « terrain à vendre Keur Moussa »
- « appartement à louer Almadies 3 chambres »
- « champ agricole à vendre Thiès »

C'est exactement ce que ciblent les titres des pages générées, qui reprennent le
type de bien, l'action et le lieu dans cet ordre.

Le meilleur levier pour élargir ensuite n'est pas technique : c'est **le nombre
d'annonces**. Chaque bien publié est une page de plus, donc une chance de plus
d'être trouvé.
