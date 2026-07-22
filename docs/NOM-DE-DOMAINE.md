# Brancher un nom de domaine

Dernière mise à jour : **22 juillet 2026**

---

## Pourquoi ça compte

Le site vit aujourd'hui sous `pabbusiness221.github.io/PAB-Immo/` — un **sous-dossier
d'un domaine qui ne vous appartient pas**. Trois conséquences concrètes :

| | |
|---|---|
| `robots.txt` | Inerte. Les robots ne lisent que celui de la racine du domaine, qui appartient à un autre dépôt. Vérifié : 404. |
| Autorité | Elle se construit sur un domaine. Vous n'en capitalisez aucune. |
| Crédibilité | Une agence immobilière dont l'adresse contient `github.io` fait amateur dans un résultat de recherche. |

Un nom de domaine règle les trois d'un coup. C'est le levier le plus rentable
avant même d'écrire une ligne de plus.

---

## 1. Choisir l'extension

**`.sn`** — le signal local le plus fort pour une agence de Dakar et Thiès.
Géré par [NIC Sénégal](https://nicsenegal.sn/faq/), attribué au premier arrivé,
enregistrement généralement traité sous 24 h via un bureau accrédité. Comptez de
l'ordre de **14 000 à 21 000 FCFA par an** selon le prestataire ; un formulaire
est à déposer auprès du NIC.

**`.com`** — immédiat, sans formalité, un peu moins cher, mais aucun signal
géographique.

> Rien n'oblige à choisir : beaucoup d'agences prennent les deux et font pointer
> l'un vers l'autre. Si vous n'en prenez qu'un, prenez le `.sn`.

Choisissez un nom court, sans tiret ni accent : `pabimmo.sn` se dicte au
téléphone, `pab-immobilier-dakar.sn` non.

---

## 2. Déclarer le domaine à GitHub

Dans le dépôt, **Settings → Pages → Custom domain**, saisir le domaine, puis
**Save**. GitHub crée un fichier `CNAME` à la racine — le laisser en place, il
fait partie de la configuration.

Cocher **Enforce HTTPS** dès que l'option devient disponible (elle apparaît une
fois le certificat émis, sous une heure en général).

---

## 3. Configurer le DNS

Chez le registrar, dans la zone DNS du domaine.

**Pour le domaine nu** (`pabimmo.sn`) — quatre enregistrements `A` :

```
185.199.108.153
185.199.109.153
185.199.110.153
185.199.111.153
```

**Pour le `www`** — un enregistrement `CNAME` :

```
www   →   pabbusiness221.github.io.
```

> Ces adresses sont celles de GitHub Pages. Si le site ne répond pas après
> quelques heures, les revérifier dans la
> [documentation GitHub](https://docs.github.com/pages/configuring-a-custom-domain-for-your-github-pages-site) :
> ce sont les seules valeurs susceptibles de changer dans cette procédure.

La propagation prend de quelques minutes à 48 h.

---

## 4. Répercuter dans le code

**Le site passe du sous-dossier à la racine.** `…/PAB-Immo/Biens-Immo.html`
devient `…/Biens-Immo.html`. Les liens internes sont relatifs, ils suivent tout
seuls. Les adresses absolues, non.

### Une seule ligne pilote tout ce qui est généré

Dans [`outils/generer-pages.py`](../outils/generer-pages.py) :

```python
SITE = "https://pabimmo.sn"        # sans barre oblique finale
```

Puis `python outils/generer-pages.py`. Les 25 fiches, le `sitemap.xml` et le
`robots.txt` se réécrivent avec la nouvelle adresse.

### Six lignes à changer à la main

Dans `vitrine.html` (ou `Biens-Immo.html` s'il a déjà été renommé) — ces balises
doivent figurer en dur dans le code source, les moteurs et les réseaux sociaux
ne les liraient pas autrement :

| Balise | Nouvelle valeur |
|---|---|
| `og:image` | `https://pabimmo.sn/assets/dakar-aerienne.jpg` |
| `og:url` | `https://pabimmo.sn/Biens-Immo.html` |
| `canonical` | `https://pabimmo.sn/Biens-Immo.html` |
| `twitter:image` | `https://pabimmo.sn/assets/dakar-aerienne.jpg` |
| JSON-LD `url` | `https://pabimmo.sn/Biens-Immo.html` |
| JSON-LD `image` | `https://pabimmo.sn/assets/dakar-aerienne.jpg` |

Demandez-la-moi : c'est un seul commit, et je vérifie derrière que rien ne
pointe plus vers l'ancienne adresse.

---

## 5. Search Console

**Une nouvelle propriété est obligatoire.** Search Console traite
`pabbusiness221.github.io/PAB-Immo/` et `pabimmo.sn` comme deux sites sans
rapport ; l'historique ne se transfère pas.

Avec un domaine à vous, choisir cette fois le type **Domaine** plutôt que
« Préfixe d'URL » : la validation se fait par un enregistrement DNS `TXT`, et la
propriété couvre alors `www`, le domaine nu, `http` et `https` d'un coup.

Puis redéclarer le sitemap : `sitemap.xml`.

Gardez l'ancienne propriété quelques mois, le temps de voir la bascule.

---

## 6. Ce qui ne casse pas

**Les liens déjà partagés continuent de fonctionner.** GitHub redirige
automatiquement l'ancienne adresse `github.io` vers le domaine personnalisé.
Les liens WhatsApp envoyés à vos prospects et les emails d'alerte déjà partis
restent valides.

**`robots.txt` devient enfin effectif** — il est déjà écrit et prêt, il ne
servait simplement à rien jusque-là.

---

## Ordre conseillé

1. Acheter le domaine
2. Le déclarer dans GitHub Pages, configurer le DNS, attendre le HTTPS
3. Répercuter les adresses dans le code, régénérer, pousser
4. Lancer `python outils/verifier-mise-en-ligne.py`
5. Créer la propriété Search Console et y déclarer le sitemap

Les étapes 2 et 3 peuvent se faire le même jour : tant que le DNS n'a pas
propagé, l'ancienne adresse continue de répondre.

**Sources :** [NIC Sénégal](https://nicsenegal.sn/faq/) ·
[GitHub Pages — domaine personnalisé](https://docs.github.com/pages/configuring-a-custom-domain-for-your-github-pages-site)
