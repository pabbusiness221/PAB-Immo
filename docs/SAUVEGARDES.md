# Sauvegardes et restauration — PAB Immo

Dernière vérification du schéma : **21 juillet 2026**
Projet Supabase : `avanktgaxepzpqmsiauz` (région eu-west-1)

---

## 1. Où vit quoi

Le site n'est pas un bloc unique. Cinq choses distinctes doivent survivre à une panne, et **elles ne sont pas sauvegardées au même endroit**.

| Élément | Où il vit | Dans ce dépôt ? |
|---|---|---|
| Les deux pages HTML | dépôt GitHub | ✅ oui |
| Structure de la base (tables, vues, règles de sécurité) | base Supabase | ✅ `supabase/schema.sql` |
| Code des 3 fonctions Edge | Supabase | ✅ `supabase/functions/` |
| **Les données** (biens, prospects, RDV) | base Supabase | ❌ **jamais** — voir §2 |
| **Les photos** des biens | bucket `property-photos` | ❌ non |
| **Les secrets** (clé Resend, etc.) | secrets Supabase | ❌ non |

### Pourquoi les données ne sont pas dans le dépôt

**Ce dépôt est public.** Les tables `contact_messages` et `appointments` contiennent les noms, téléphones et emails de personnes réelles qui ont pris contact. Les publier serait une fuite de données personnelles, irrattrapable une fois indexée.

Les exports de données vont dans un stockage privé (disque chiffré, Drive privé, coffre-fort), jamais dans git.

---

## 2. Sauvegarder

### 2.1 Ce que Supabase fait tout seul

Supabase effectue des sauvegardes automatiques de la base. **Leur fréquence et leur durée de rétention dépendent de l'offre souscrite** — à vérifier dans `Database → Backups` de la console. Sur les offres d'entrée, la rétention est courte et il n'y a pas de restauration à un instant précis.

⚠️ **Ces sauvegardes automatiques ne couvrent pas le bucket de stockage.** Les photos des biens ne sont pas dedans.

### 2.2 Export manuel des données (à faire régulièrement)

Depuis la console Supabase, `SQL Editor`, exporter chaque table en CSV :

```sql
select * from properties;
select * from property_photos;
select * from property_status_history;
select * from contact_messages;      -- DONNÉES PERSONNELLES
select * from appointments;           -- DONNÉES PERSONNELLES
select * from alert_subscriptions;    -- DONNÉES PERSONNELLES
select * from collaborators;
select * from site_visits;
select * from property_views;
select * from favorite_events;
select * from activity_logs;
```

Ranger les fichiers dans un dossier daté, **hors du dépôt** : `sauvegardes/2026-07-21/`.

### 2.3 Les photos

Le bucket `property-photos` doit être copié séparément. Le plus simple depuis la console : `Storage → property-photos → Download`. Pour automatiser, la CLI Supabase (`supabase storage cp`) ou un script s'appuyant sur `storage_path` de la table `property_photos`.

Sans ces fichiers, une base restaurée affichera des annonces sans aucune image.

### 2.4 Les secrets à noter

Ces valeurs ne sont **nulle part** dans le dépôt et ne doivent pas y être. À conserver dans un gestionnaire de mots de passe :

| Secret | Utilisé par |
|---|---|
| `RESEND_API_KEY` | notify-lead, notify-alert-matches |
| `NOTIFY_EMAIL` | notify-lead (destinataire des alertes internes) |
| `NOTIFY_FROM` | les deux (expéditeur, optionnel) |
| `ALERT_LISTING_URL` | notify-alert-matches, share-preview |
| `SUPABASE_SERVICE_ROLE_KEY` | les trois fonctions |

---

## 3. Restaurer

### 3.1 Ordre obligatoire

L'ordre n'est pas négociable : chaque étape dépend de la précédente.

1. **Créer les comptes utilisateurs d'abord.** La table `properties` a une clé étrangère vers `auth.users(id)`. Si les comptes n'existent pas, l'import des biens échoue intégralement.
2. **Corriger `is_admin()` dans `schema.sql`.** Elle contient l'identifiant admin **écrit en dur** :
   ```sql
   select auth.uid() = '514ff065-fa33-454b-9701-c9aec9053862'::uuid;
   ```
   Sur un nouveau projet, cet identifiant n'existe plus. Sans correction, **plus personne n'a accès à rien** : ni aux prospects, ni aux collaborateurs, ni au journal.
3. **Jouer `supabase/schema.sql`** dans le SQL Editor.
4. **Réimporter les données** dans l'ordre des dépendances : `properties` → puis toutes les autres.
5. **Recréer le bucket** `property-photos` en accès public et y reverser les fichiers.
6. **Redéployer les 3 fonctions Edge** depuis `supabase/functions/`, puis reconfigurer leurs secrets (§2.4).
7. **Mettre à jour `SUPABASE_URL` et la clé publique** dans les deux fichiers HTML si le projet a changé d'identifiant.
8. **Corriger les URL codées en dur dans les fonctions SQL.** `notify_lead_webhook()` et `notify_alert_matches()` appellent `https://avanktgaxepzpqmsiauz.supabase.co/functions/v1/...`. Sur un nouveau projet, ces adresses ne répondent plus.

### 3.2 Pièges connus

- **L'ordre d'import compte** : `property_photos`, `contact_messages` et `appointments` référencent `properties`.
- **Les déclencheurs se réveillent pendant l'import.** Réimporter des biens déclenchera `notify_alert_matches` et enverra de vrais emails aux inscrits. Désactiver les déclencheurs le temps de l'import :
  ```sql
  alter table public.properties disable trigger notify_alert_matches_trigger;
  -- … import …
  alter table public.properties enable trigger notify_alert_matches_trigger;
  ```
- **`activity_logs` et `property_status_history` se remplissent tout seuls** pendant l'import, avec de fausses dates. Les vider après import si l'historique réel a été réimporté.
- **`leads` se reconstruit tout seul, et écrase les dates.** Importer `contact_messages` et `appointments` déclenche `rattacher_lead`, qui recrée chaque fiche prospect — mais avec `last_activity_at = now()`. Toutes les fiches paraîtront actives aujourd'hui, et la colonne « à relancer » tombera à zéro. Pire, si `leads` a été réimporté **avant**, les étapes et notes restent mais les dates sont écrasées.

  Importer `leads` **en dernier**, déclencheurs coupés :
  ```sql
  alter table public.contact_messages disable trigger trg_messages_lead;
  alter table public.appointments     disable trigger trg_rdv_lead;
  -- … import de contact_messages, appointments, puis leads …
  alter table public.contact_messages enable trigger trg_messages_lead;
  alter table public.appointments     enable trigger trg_rdv_lead;
  ```
  Si `leads` n'a pas été sauvegardé, laisser les déclencheurs faire : les fiches se recréent avec les bons noms et les bons biens, seules les étapes de suivi sont perdues.

---

## 4. Tester la restauration

Une sauvegarde jamais restaurée n'est pas une sauvegarde. Le test se fait sur un **projet Supabase vierge**, jamais sur la production.

### Résultat du dernier test — 21 juillet 2026

✅ **Restauration rejouée de bout en bout** sur un projet Supabase vierge.

| Contrôle | Résultat |
|---|---|
| `schema.sql` s'exécute sans erreur sur une base vide | ✅ |
| 11 tables, 2 vues, 7 fonctions, 8 déclencheurs, 18 index, 25 politiques | ✅ identiques à la production |
| 30 colonnes sur `properties`, 3 types énumérés | ✅ |
| Colonne générée `location` calculée automatiquement | ✅ |
| Déclencheur du journal d'activité alimenté à l'insertion | ✅ |
| Un collaborateur ne voit que ses propres biens | ✅ 1 bien sur 2 |
| Un collaborateur voit les messages portant sur ses biens | ✅ |
| Le journal reste invisible au collaborateur | ✅ 0 ligne |
| Un visiteur anonyme ne lit **rien** | ✅ 0 bien, 0 message, 0 journal |
| Un visiteur anonyme peut déposer un message | ✅ |
| Un collaborateur ne peut pas certifier son propre bien | ✅ refusé par le déclencheur |
| Un collaborateur peut confirmer la disponibilité | ✅ |

> **Depuis ce test, le schéma a grandi.** Le pipeline de prospects du 22 juillet 2026
> ajoute une table, une vue, quatre fonctions, trois déclencheurs, deux index et
> quatre politiques. Sa syntaxe et son ordre de déclaration ont été vérifiés hors
> ligne, mais **il n'a pas été rejoué sur une base vierge**. Le tableau ci-dessus
> reste le constat du 21 juillet, il n'a pas été réécrit après coup.

**Un défaut réel a été trouvé et corrigé grâce à ce test** : la colonne `location`
était transcrite en `default (st_setsrid(...))` alors qu'il s'agit d'une colonne
**générée**. PostgreSQL refuse qu'un `DEFAULT` référence d'autres colonnes, si
bien que le fichier était **irrestaurable**. Ni la relecture ni l'analyse
syntaxique ne l'avaient vu : seule l'exécution réelle l'a révélé. C'est
exactement la raison d'être de ce test.

Reste non testé, faute d'être reproductible sans les vrais services :
le bucket de stockage, les fonctions Edge et l'envoi d'emails.

### Comment refaire ce test

Deux vérifications gratuites avant tout, sans créer de projet :

```bash
pip install pglast
python -c "import pglast,io; pglast.parse_sql(io.open('supabase/schema.sql',encoding='utf-8').read()); print('syntaxe valide')"
```

Puis, sur un projet Supabase vierge (l'offre gratuite en autorise deux par
organisation, coût 0 €) : jouer `schema.sql`, comparer les comptes d'objets à
la production, et rejouer le tableau ci-dessus.

⚠️ Le projet de test doit être **supprimé après usage** depuis le tableau de
bord Supabase.

---

## 5. Rythme conseillé

| Quoi | Quand |
|---|---|
| Export des données | chaque semaine, et avant toute modification de schéma |
| Copie des photos | chaque mois, et après un ajout important de biens |
| Mise à jour de `schema.sql` | à chaque changement de structure |
| Test de restauration complet | tous les 6 mois |

Pour régénérer `schema.sql` après un changement de structure, réextraire depuis la base plutôt que de le modifier à la main : il doit rester le reflet exact de la production.
