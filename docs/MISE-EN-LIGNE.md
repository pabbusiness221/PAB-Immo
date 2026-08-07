# Mise en ligne — procédure

Dernière mise à jour : **7 août 2026**

Le site est actuellement **en maintenance**. Ce document décrit la bascule vers
le site public, dans l'ordre. Il existe parce que la bascule touche cinq
endroits différents et qu'en oublier un ne provoque aucune erreur visible — le
site a simplement l'air normal tout en restant invisible pour Google, ou en
publiant de fausses annonces.

---

## État actuel

| Adresse | Ce qu'elle sert aujourd'hui |
|---|---|
| `Biens-Immo.html` | Page de maintenance. **C'est l'adresse partagée** dans les WhatsApp et les emails d'alerte déjà envoyés. |
| `index.html` | Copie de la page de maintenance, pour couvrir la racine du dossier. |
| `vitrine.html` | Le vrai catalogue, en `noindex`, invisible du public. |
| `Portefeuille-Immo.html` | L'espace de gestion. Accessible normalement. |
| `mentions-legales.html`, `confidentialite.html` | Pages légales (en `noindex`). Reliées au pied de la vitrine. |
| `bien/` | Les fiches générées à partir de **données fictives**. |

Les biens en base sont un **jeu d'essai**. Ils seront supprimés et remplacés par
le vrai portefeuille. Attention : quelques-uns portent une référence ou une
région de test (« THIES », « Région de Dakar », réf. `…-test`) — ils partent avec
le reste au nettoyage.

> **Prérequis d'hébergement** (à régler avant l'annonce publique) : passer le
> projet **Supabase en plan Pro** (le gratuit se met en pause et plafonne le
> trafic) et **vérifier le domaine d'envoi chez Resend** pour des e-mails d'alerte
> fiables. Voir aussi [NOM-DE-DOMAINE.md](NOM-DE-DOMAINE.md).

> **Prérequis IA** : les fonctions Edge `generer-description` (rédaction
> assistée, admin) et `traduire-description` (traduction anglaise à la volée,
> vitrine) ont besoin du secret **`GROQ_API_KEY`** (clé gratuite sur
> [console.groq.com](https://console.groq.com)), à configurer dans
> `Project Settings → Edge Functions → Secrets` sur Supabase. Sans lui, ces deux
> fonctions répondent une erreur claire plutôt qu'un texte — rien de cassé côté
> visiteur, mais les descriptions ne se génèrent ni ne se traduisent plus.

---

## La bascule, dans l'ordre

### 1. Remplacer les données

Depuis `Portefeuille-Immo.html` :

- supprimer les 24 biens fictifs ;
- saisir les biens réels, avec **au moins une photo chacun** — près de la
  moitié des biens d'essai n'en avaient aucune, et une fiche sans photo
  n'intéresse ni un acheteur ni Google ;
- veiller à la **cohérence des lieux** : une même commune doit toujours porter
  la même région et la même orthographe. Google s'appuie sur ces mentions pour
  la recherche locale, deux réponses différentes le désorientent.

> Le générateur normalise déjà « Commune de Sébikhotane » → « Sébikhotane »,
> « Région de Dakar » → « Dakar », « THIES » → « Thiès ». Il rattrape la casse
> et les préfixes, **pas** une région erronée.

### 2. Rendre la vitrine publique

Trois gestes, aucun n'est optionnel :

```bash
git mv vitrine.html Biens-Immo.html   # écrase la page de maintenance
git rm index.html                     # ne sert plus à rien
```

Puis, dans `Biens-Immo.html`, **supprimer la ligne** :

```html
<meta name="robots" content="noindex, nofollow" />
```

C'est elle qui interdit l'indexation. Tant qu'elle est là, tout le reste est
sans effet.

### 3. Régénérer les fiches

Dans `outils/generer-pages.py` :

```python
EN_MAINTENANCE = False
```

puis :

```bash
python outils/generer-pages.py
```

Le script reconstruit `bien/` de zéro, réécrit `sitemap.xml` et retire les
balises `noindex` des fiches.

> **Le point qui se rate.** Le script supprime les fichiers du disque, mais Git
> ne l'apprend qu'avec `git add -A`. Un `git add bien/` classique n'enregistre
> pas les suppressions : les fiches fictives resteraient en ligne et dans le
> sitemap alors que la base est vide.

### 4. Publier

```bash
git add -A
git commit -m "Mettre le catalogue en ligne"
git push
```

### 5. Vérifier avant d'annoncer

```bash
python outils/verifier-mise-en-ligne.py
```

Le script contrôle qu'il ne reste aucun `noindex`, que le sitemap correspond
aux fiches réellement présentes, et qu'aucun lien interne n'est mort.

### 6. Search Console

Dans [Search Console](https://search.google.com/search-console) :

- **Inspection de l'URL** sur `Biens-Immo.html` et sur `bien/`, puis
  « Demander une indexation ». Ça amorce l'exploration au lieu d'attendre.
- Vérifier que le sitemap est passé à « Réussite » et qu'il annonce le bon
  nombre d'adresses.

Voir `docs/REFERENCEMENT.md` pour le fonctionnement d'ensemble.

---

## Ensuite, à chaque changement de bien

Publier, modifier, dépublier ou archiver un bien depuis le portefeuille **n'a
aucun effet immédiat sur les fiches**. Le bien apparaît tout de suite sur la
vitrine, mais sa fiche — la seule page que Google sait lire — n'existe que
lorsque le générateur est passé. Une fiche non régénérée continue d'annoncer un
ancien prix, ou un bien déjà vendu.

**C'est automatique.** L'action `.github/workflows/actualiser-fiches.yml`
régénère et publie les fiches **toutes les 15 minutes**. Un bien fraîchement
ajouté est ainsi visible de Google — et surtout **partageable avec sa photo, son
type et son lieu** sur WhatsApp/Facebook — en un quart d'heure au plus, au lieu
d'attendre la nuit. Le contrôle de cohérence ne s'exécute que lorsqu'il y a
réellement quelque chose à publier : les exécutions à vide (l'immense majorité)
ne peuvent ni échouer ni envoyer de mail. En cas d'incohérence sur un vrai
changement, la publication est refusée et GitHub envoie un mail.

**Pour ne pas attendre les 15 minutes** : onglet **Actions** du dépôt →
*Actualiser les fiches* → bouton **Run workflow**. Comptez deux minutes.

**Manuellement**, si besoin :

```bash
python outils/generer-pages.py
python outils/verifier-mise-en-ligne.py
git add -A && git commit -m "Actualiser les fiches" && git push
```

> **Deux choses à savoir sur les actions planifiées.** GitHub les **désactive
> après 60 jours sans aucune activité** sur le dépôt — il envoie un mail avant,
> et un simple clic les réactive. Et un déclenchement toutes les 15 min peut
> glisser de quelques minutes quand ses serveurs sont chargés ; ce n'est pas une
> panne.

### Ce que l'action ne fait pas

Elle ne touche jamais aux réglages : `EN_MAINTENANCE`, les balises `noindex`,
le renommage de `vitrine.html`. La bascule décrite plus haut reste un geste
volontaire, à faire une seule fois.
