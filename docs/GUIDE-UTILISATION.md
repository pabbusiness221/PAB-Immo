# Guide d'utilisation — PAB Immo

Dernière mise à jour : **22 juillet 2026**

Ce guide explique comment faire fonctionner le site au quotidien. Il s'adresse à
vous, sans supposer de connaissances techniques. Les sujets purement techniques
(mise en ligne, sauvegardes, référencement, nom de domaine) ont leurs propres
fiches, listées à la fin.

---

## 1. Les deux visages du site

Votre site est fait de **deux pages** qui se ressemblent mais ne servent pas les
mêmes personnes.

| | Pour qui | Adresse |
|---|---|---|
| **La vitrine** | Vos clients, le public | `Biens-Immo.html` (aujourd'hui `vitrine.html`, en travaux) |
| **Le portefeuille** | Vous, et vos collaborateurs | `Portefeuille-Immo.html` |

La vitrine montre les biens et permet de vous contacter. Le portefeuille est
votre poste de commande : vous y ajoutez les biens, suivez les demandes, gérez
les agences. **Vos clients n'y ont jamais accès** — il faut un compte.

> Aujourd'hui le site est **en maintenance** : la vitrine est masquée derrière
> une page « Notre site fait peau neuve ». Pour la remettre en ligne, voir
> [MISE-EN-LIGNE.md](MISE-EN-LIGNE.md).

---

## 2. Se connecter au portefeuille

1. Ouvrez `Portefeuille-Immo.html`.
2. Un mur de connexion s'affiche. Saisissez votre email et votre mot de passe.
3. Une fois connecté, la barre d'outils du haut apparaît.

Le bouton **« ← Retour au site public »** sous le formulaire ramène à la vitrine
sans se connecter — utile si vous êtes arrivé là par erreur.

Pour quitter, le lien **Déconnexion** en haut à droite.

### Deux niveaux de compte

- **Administrateur** (vous) : accès à tout.
- **Collaborateur** (une agence partenaire) : voit et gère **ses propres biens**
  et les demandes qui les concernent, mais pas la boîte de réception globale, ni
  le journal, ni les agences, ni les prospects. Les statistiques qu'un
  collaborateur voit ne portent que sur ses biens.

Cette séparation n'est pas un réglage d'affichage : elle est imposée par la base
de données. Un collaborateur ne peut pas voir les biens d'un autre, même en
contournant la page.

---

## 3. La barre d'outils

De gauche à droite, selon votre niveau de compte :

| Bouton | Ce qu'il ouvre |
|---|---|
| **Prospects** | Le suivi des personnes qui vous ont contacté (admin) |
| **Agences** | Les collaborateurs et les candidatures d'agences (admin) |
| **Journal** | L'historique de qui a fait quoi (admin) |
| **Statistiques** | Les chiffres de fréquentation et de conversion |
| **Boîte de réception** | Les messages et demandes de rendez-vous (admin) |
| **Ajouter un bien** | Le formulaire de création (bouton doré) |
| **Vitrine** | Ouvre la vitrine côté client, pour voir ce que voient vos visiteurs |

Une **pastille rouge** sur un bouton indique des éléments nouveaux à traiter
(messages non lus, candidatures à examiner).

---

## 4. Gérer les biens

### Ajouter un bien

Cliquez sur **Ajouter un bien** (le bouton doré). Remplissez :

- **Type** : Terrain, Maison, Appartement, Studio ou Champ agricole.
- **Opération** : Vente ou Location. Le prix d'une location est compris comme
  mensuel, celui d'une vente comme total.
- **Statut** : Disponible, Réservé, puis Vendu ou Loué. Seuls *Disponible* et
  *Réservé* apparaissent sur la vitrine.
- **Région** : liste **Dakar** ou **Thiès**. Un nouveau bien vous force à
  choisir — ce n'est pas un oubli, c'est voulu. Cette liste garantit que les
  alertes email retrouvent bien le bien (voir §10).
- **Département, Commune, Quartier** : la localisation fine.
- **Latitude / Longitude** : la position sur la carte. Indispensable pour que le
  bien apparaisse au bon endroit.
- **Superficie** : en m², ou en **hectares** pour un champ agricole.
- **Prix**, **Description**, et les **pièces** (chambres, salons, etc.) pour les
  biens habitables.

Une **référence** (ex. `TF-2026-1234`) est attribuée automatiquement, avec un
préfixe par type : TF terrain, MA maison, AP appartement, ST studio, CH champ.

### Les photos

Ajoutez au moins **une photo par bien**. Un bien sans photo n'intéresse ni un
acheteur ni Google. La première photo sert de couverture. Les photos sont
redimensionnées automatiquement : inutile de les alléger avant.

### Publier ou garder en brouillon

La case **« Publié »** décide si le bien paraît sur la vitrine. Un bien non
publié reste visible pour vous seul, le temps de le compléter.

### Modifier, archiver

- **Modifier** : cliquez sur un bien dans la liste, changez ce qu'il faut,
  enregistrez.
- **Archiver** : un bien archivé quitte la vitrine et les listes courantes, mais
  reste consultable et **restaurable** dans l'onglet **Archives**. À préférer à
  la suppression : on ne perd rien.

---

## 5. Les badges de confiance

Trois badges peuvent apparaître sur une annonce, côté vitrine. Ils se règlent
dans la fiche du bien, section **Confiance**.

| Badge | Ce qu'il dit | Qui le pose |
|---|---|---|
| **Annonce vérifiée** | Documents et existence du bien contrôlés | L'admin seul |
| **Disponibilité** | Le bien est toujours disponible, confirmé récemment | Vous, bouton *Confirmer* |
| **Agence vérifiée** | Publié par une agence certifiée | Via l'écran Agences |

La **disponibilité** est datée : au-delà d'un mois sans confirmation, le badge
disparaît de lui-même plutôt que d'afficher une date périmée. Pensez à cliquer
*Confirmer* de temps en temps sur vos biens actifs.

---

## 6. Mettre un bien en avant (sponsoring)

Section **Mise en avant** de la fiche d'un bien (admin uniquement).

- Choisissez une **date de fin**. Le bien remonte en tête de la vitrine
  jusque-là, avec une étiquette « Sponsorisé », puis redescend tout seul.
- Jusqu'à **20 biens** peuvent être mis en avant : ils occupent la première page
  de la vitrine. Le compteur affiche les places restantes.
- Au-delà de 20, une mise en avant supplémentaire ne servirait à rien : la fiche
  vous en avertit.

C'est une échéance, pas un interrupteur : vous n'avez rien à éteindre, la date
s'en charge.

---

## 7. Les demandes de vos clients

### La boîte de réception

Le bouton **Boîte de réception** rassemble les **messages** et les **demandes de
rendez-vous** laissés depuis la vitrine. Vous y voyez le nom, le contact, le bien
concerné, et pouvez marquer comme lu.

Les demandes de rendez-vous ont un **statut** : En attente → Confirmé →
Réalisée, ou Annulé. Passez-les à *Réalisée* après la visite : c'est ce qui
nourrit vos statistiques de visites.

### Le suivi des prospects (pipeline)

Le bouton **Prospects** regroupe ces demandes **par personne**, et non par
message : quelqu'un qui écrit trois fois puis demande deux visites n'y apparaît
**qu'une fois**. Chaque prospect suit une progression :

**Nouveau → Contacté → Visite → Négociation → Conclu / Perdu**

Faites avancer chaque prospect à la main, au fil de vos échanges. L'écran indique
depuis combien de jours chacun n'a pas donné signe de vie, pour savoir qui
relancer. Le **taux de conversion** en haut se calcule sur les dossiers tranchés
(conclus + perdus), pas sur le total — il ne chute pas à chaque nouveau contact.

---

## 8. Les agences collaboratrices

Le bouton **Agences** ouvre deux choses.

### Les collaborateurs actuels

La liste des agences qui publient déjà chez vous. Le bouton **Certifier** leur
accorde le badge « Agence vérifiée », visible sur toutes leurs annonces.
**Réservé à l'admin** : une agence ne peut pas se certifier elle-même, sinon le
badge ne voudrait rien dire.

### Les candidatures

En dessous, les **agences qui ont postulé** depuis le formulaire en bas de la
vitrine. Chacune a un statut : Nouvelle → En discussion → Acceptée / Refusée.

> **Important** : accepter une candidature ne crée **pas** de compte
> automatiquement. Il reste à inviter l'agence depuis Supabase, puis à l'ajouter
> aux collaborateurs. Le statut ne sert qu'à suivre où en est l'échange.

---

## 9. Statistiques et journal

**Statistiques** : fréquentation (visiteurs, vues, favoris), demandes générées,
visites organisées, taux de conversion, et des graphiques par mois, par type,
par région. Un collaborateur n'y voit que ses propres biens.

**Journal d'activité** : la trace de qui a créé, modifié ou publié quel bien, et
quand. Réservé à l'admin. Utile pour comprendre ce qui a changé, et par qui.

---

## 10. Les alertes email

Un visiteur peut, depuis la vitrine, **s'abonner aux alertes** : il laisse son
email et ses critères (type, opération, région, budget). Dès que vous publiez un
bien qui correspond, il reçoit un email automatiquement.

Vous n'avez rien à faire : l'envoi est déclenché par la publication.

### Le bandeau rouge « Des emails n'arrivent pas »

Si un envoi échoue, un bandeau rouge apparaît en haut du portefeuille. Il existe
parce qu'une panne d'email est autrement **invisible** : la demande est bien
enregistrée, mais personne n'est prévenu.

- Il indique combien d'emails sont partis et combien ont échoué, avec la cause
  probable.
- Il **disparaît tout seul** dès qu'un envoi réussit après le dernier échec.
- La fiabilité dépend d'un service externe (Resend). Pour des envois vraiment
  fiables, il faudra **vérifier votre domaine** chez Resend, une fois le nom de
  domaine en place (voir [NOM-DE-DOMAINE.md](NOM-DE-DOMAINE.md)).

---

## 11. Ce que voient vos visiteurs (la vitrine)

Pour vous mettre à leur place, ouvrez la vitrine par le bouton **Vitrine**.

- **Recherche** par commune, région ou référence, et filtres par type, prix,
  surface, chambres, ou autour d'un point sur la carte.
- **Liste et carte** : chaque bien apparaît des deux côtés.
- **Favoris** : le visiteur peut marquer des biens (gardés sur son appareil).
- **Fiche d'un bien** : photos, caractéristiques, carte, et boutons **WhatsApp**
  et **Appeler**, plus un formulaire de message et de rendez-vous.
- **Partage** : le bouton *Partager* envoie un lien qui, sur WhatsApp ou
  Facebook, affiche la photo et le prix du bien.
- **Devenir collaborateur** : en bas de page, le formulaire par lequel les
  agences vous postulent (voir §8).

---

## 12. Les tâches d'entretien

**Régénérer les fiches Google** : chaque bien publié a une page dédiée que Google
peut lire. Elle est reconstruite **automatiquement chaque nuit**. Pour ne pas
attendre, un bouton *Run workflow* existe sur GitHub. Détails et cas où c'est
nécessaire : [MISE-EN-LIGNE.md](MISE-EN-LIGNE.md).

**Sauvegardes** : la procédure pour sauvegarder et restaurer vos données est
dans [SAUVEGARDES.md](SAUVEGARDES.md). À faire régulièrement une fois en ligne.

---

## 13. Petits problèmes courants

| Symptôme | Explication |
|---|---|
| Un bien publié n'apparaît pas sur Google | Normal : sa fiche est régénérée la nuit, et l'indexation prend des semaines. Voir [REFERENCEMENT.md](REFERENCEMENT.md). |
| Le bandeau rouge des emails persiste | Il reflète les 7 derniers jours ; il part dès qu'un envoi réussit. Voir §10. |
| Un bien n'apparaît pas sur la carte | Vérifiez sa latitude et sa longitude. |
| Un collaborateur ne voit pas un bien | Normal s'il n'en est pas le propriétaire : chacun ne voit que les siens. |
| La vitrine affiche « site en travaux » | Le site est en maintenance. Pour le publier : [MISE-EN-LIGNE.md](MISE-EN-LIGNE.md). |

---

## Les autres fiches

- **[MISE-EN-LIGNE.md](MISE-EN-LIGNE.md)** — publier le site, remplacer les biens
  de test, et l'entretien des fiches.
- **[REFERENCEMENT.md](REFERENCEMENT.md)** — comment Google trouve vos biens, et
  Search Console.
- **[NOM-DE-DOMAINE.md](NOM-DE-DOMAINE.md)** — brancher une adresse à vous
  (`pabimmo.sn`), et fiabiliser les emails.
- **[SAUVEGARDES.md](SAUVEGARDES.md)** — sauvegarder et restaurer les données.
