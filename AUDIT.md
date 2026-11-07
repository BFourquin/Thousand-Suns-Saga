# Audit du code — Thousand Suns Saga

Audit du 2026-11-07, mis à jour le même jour après les corrections.

Ce document remplace l'audit du 2026-11-05, qui décrivait encore le code MongoDB. L'ancienne version reste dans l'historique git (`git show 0f64d9b:AUDIT.md`), et ses numéros ne sont plus valables.

**Ce que fait le dépôt :** un jeu de stratégie spatiale au tour par tour, jouable dans le navigateur. Il tourne sur Django et PostgreSQL, avec une base commune pour les comptes et un schéma PostgreSQL par serveur de jeu.

**Charge supposée :** une pré-alpha sur un seul processus, avec quelques dizaines de joueurs et des cycles lancés à la main.

**Tests :** 230 tests, tous verts.

## Résumé

| N° | Sujet | État |
| --- | --- | --- |
| 1 | District central gratuit par requête directe | Corrigé |
| 2 | Règle du multi-compte jamais appliquée | Corrigé, remplacée par les serveurs exclusifs |
| 3 | Serveur arrêté et commandant mort pouvaient jouer | Corrigé, mode consultation |
| 4 | Double clic sur la fin de cycle | Corrigé |
| 5 | Nouveaux joueurs absents du suivi de cycle | Corrigé |
| 6 | Configuration non prête pour un site public | **À faire** |
| 7 | Rapport archivé désarchivé à l'ouverture, badge faux | Corrigé |
| 8 | Rapports à l'envers et chargés en entier | Corrigé |
| 9 | Bugs du générateur de carte, sans test | **À faire** |
| 10 | Noms mal nettoyés | Corrigé |
| 11 | Droits du staff dans l'administration | Corrigé |
| 12 | Erreurs 500 sur des requêtes mal formées | **À faire** |
| 13 | Trop de requêtes sur la page colonie | Corrigé |
| 14 | `settings_opensource.py` périmé | Corrigé, `settings.py` est versionné |
| 15 | Code mort | Trié : bokeh et le code remplacé sont retirés, le reste attend une décision |
| 16 | Dépendances anciennes et non épinglées | **À faire** |
| 17 | La fin de cycle relit les tables pour chaque joueur | Corrigé |
| 18 | Fichier Excel temporaire non ignoré | **À faire** |

## Ce qui reste à faire

### 6. La configuration n'est pas prête pour un site public

`django_tss/settings.py:50`, `:52`, `:177` et `static_server.py:20`.

- **Problème :** `DEBUG = True`, `ALLOWED_HOSTS = ['*']`, CORS ouvert à tous, et un serveur statique ouvert sur toutes les interfaces. En mode debug, une erreur affiche la configuration et les variables locales.
- **Correction :** lire `debug` et `allowed_hosts` dans `secrets/django.ini`, limiter CORS au serveur statique et écouter sur `127.0.0.1`.
- **Sinon :** dès que le site est exposé, une simple erreur 500 révèle des informations internes.

### 9. Le générateur de carte garde plusieurs bugs, sans aucun test

`geography/mg_systems_placement.py:24`, `:34`, `:85`, `geography/mg_system_composition.py:173`, `stats/stats_geography.py:14`.

- **Problème :**
  - `randint(0, len(...))` peut dépasser la liste, et comme la graine est fixe, le même secteur plante à chaque essai.
  - `== 'border' or 'corner'` est toujours vrai.
  - La ligne 34 compare X à la taille en Y.
  - Le nuage d'Oort reprend la probabilité et le tirage de la ceinture d'astéroïdes, donc les deux vont toujours ensemble.
  - Les statistiques regroupent par `[:12]` alors qu'un secteur fait 10 caractères.
- **Correction :** corriger ces cinq lignes et ajouter un test qui génère un petit secteur avec une graine fixe.
- **Sinon :** certaines graines ne produisent jamais de carte, et les autres donnent des cartes et des statistiques fausses.

### 12. Des requêtes mal formées donnent une erreur 500

`backend/views_api_buildings.py`, `backend/views_api_research.py`.

- **Problème :** `request_params` fusionne GET et POST, et renvoie une liste si un paramètre est répété. `activation_percent` absent donne une erreur 500, et `technology` envoyé deux fois aussi.
- **Correction :** utiliser `request.POST.get` dans les API, et supprimer le doublon de `request_params` dans `views_api_user.py`.
- **Sinon :** le joueur reçoit une erreur brute et les journaux se remplissent de bruit.

### 15. Fonctions inutilisées sans remplaçant : décision à prendre

Bokeh et le code déjà remplacé sont retirés. Ces fonctions ne sont appelées par aucun code du jeu, mais rien ne les remplace, donc elles sont conservées :

| Fonction | Ce qui manque | Remarque |
| --- | --- | --- |
| `delete_building` (`data/buildings.py`) | Démolir un bâtiment | Ne marche pas : parcourt un dict comme une liste de paires, et ne rembourse rien |
| `cheat_log` (`data/admin.py`) | Journal de triche | Vide, et les vérifications anti-triche des API ne journalisent rien |
| `set_dead_commandant` (`data/server_details.py`) | Mort d'un commandant | Seuls les tests l'appellent : aucune règle du jeu ne tue encore un commandant |
| `delete_commandant` (`data/commandant.py`) | Suppression par un admin | Seuls les tests l'appellent ; son commentaire cite un `commandant_death()` qui n'existe pas |
| `get_tz` (`data/server_details.py`) | Fuseau horaire du serveur | Le champ `Server.timezone` est stocké mais jamais appliqué |
| `get_resources_subcategories` (`data/resources.py`) | Filtre par sous-catégorie | La table est chargée, la page Ressources ne filtre que par catégorie |
| `update_district` (`data/districts.py`) | Modifier un district | À garder si les dégâts et les PV arrivent |
| `get_all_colonies`, `get_all_districts` | Liste complète | Simples lectures, rien ne les utilise |

Deux templates ne sont utilisés nulle part : `admin/admin_raw_json.html` et `template.html`.

### 16. Les dépendances ne sont ni à jour ni épinglées

`requirements.txt`.

- **Problème :** aucune version n'est fixée, et Django 5.0.6 installé sur la machine de dev n'a plus de correctifs de sécurité. Flask, Flask-Cors, DRF, django-filter, PyYAML, Markdown, watchdog, argh et pathtools ne sont importés nulle part, et `pytest` n'est pas utilisé. Tornado et d'autres paquets listés ne servaient qu'à bokeh, maintenant retiré.
- **Correction :** passer à Django 5.2 LTS, garder un seul fichier épinglé et supprimer `requirements_OLD.txt` et `requirements_versionning.txt`.
- **Sinon :** l'environnement n'est pas reproductible et les failles de Django ne seront plus corrigées.

### 18. Un fichier Excel temporaire n'est pas ignoré

`.gitignore`.

- **Problème :** `~$TSS_v2.xlsx` apparaît dans `git status`.
- **Correction :** remplacer les lignes concernées par `~$*.xlsx`.

## Ce qui a été corrigé

- **1.** L'API refuse les districts centraux et ceux au-dessus du niveau technologique. Le menu de construction suit la même règle (`is_buildable_district`).
- **2.** Un joueur a un seul commandant par serveur, et ne peut jouer que sur un seul serveur **exclusif** à la fois. Le réglage `allow_multiaccounts` devient `exclusive`, et la liste publique affiche « Exclusif » ou « Libre » avec une légende. Un commandant mort ou un serveur terminé ne compte plus.
- **3.** Sur un serveur `stop` ou `dead`, ou avec un commandant mort, le joueur rouvre son compte depuis sa page de compte et voit tout, mais aucun ordre n'est accepté (`orders_closed`). Les formulaires sont désactivés et une bannière l'explique.
- **4.** Le formulaire envoie le numéro du cycle, et la fermeture du cycle est atomique : un second envoi ne change rien.
- **5.** Un nouveau commandant rejoint les listes du cycle en cours.
- **7.** Ouvrir un rapport ne touche que les non lus, et le badge du menu se met à jour.
- **8.** Les rapports sont filtrés et paginés dans la base, les plus récents d'abord. La recherche ignore la casse et passe en GET.
- **10.** Les espaces et le caractère nul sont retirés des noms, les comptes et e-mails sont uniques sans tenir compte de la casse, et la longueur du pseudo suit le message (5 à 25).
- **11.** Toute l'administration, signalements compris, est réservée aux superusers, et seuls `status`, `admin_only_visibility` et `exclusive` sont modifiables avec des valeurs fixes. Le staff garde la modération des forums et le passage de cycle.
- **13.** Les ressources sont lues une seule fois par menu (`get_resources_by_name`) au lieu d'une fois par ligne, ce qui profite aussi à la page Technologies. Les compteurs du menu et les infos de cycle partagent chacun un seul changement de schéma. Mesures avec les vraies données Excel : `/colony/` passe de 167 à 43 requêtes et `/technologies/` de 42 à 33. Les pages simples perdent 6 requêtes et font 33 à 39 requêtes.
- **14.** `settings.py` est versionné, ses valeurs confidentielles restent dans `secrets/`, et la copie open source est supprimée.
- **15.** Sont retirés :
  - bokeh, ses templates et sa dépendance ;
  - le bloc de test des rapports et les imports inutiles des vues ;
  - `api_can_join_server`, remplacée par les contrôles de `api_create_commandant` ;
  - `check_enough_resource`, remplacée par `check_enough_resources_dict` et `pay_resources` ;
  - `give_starting_resources`, remplacée par `create_commandant` ;
  - `get_commandant_by_name`, remplacée par `forums.find_commandant` ;
  - `update_cycle`, remplacée par `end_cycle` ;
  - `get_all_sectors` et `get_all_coordinates`, remplacées par la pagination de `admin_geography` ;
  - `get_available_native_planets`, remplacée par `get_starting_values` ;
  - `get_statistic` et `set_statistic`, remplacées par les versions par catégorie ;
  - `tech`, remplacée par les colonnes Excel ;
  - `actions/building.py` et `geography/planet.py`.
- **17.** Les tables communes sont lues une seule fois par fin de cycle.

## Limites de cet audit

- **Non lu :** le détail des templates et des bibliothèques tierces, ni la plupart de `geography/` et des chargeurs Excel en dehors de `load_buildings`.
- **Non testé :** aucun essai à plusieurs utilisateurs simultanés ni dans un navigateur, y compris pour le mode consultation. La désactivation des formulaires côté navigateur n'a donc pas été vue en vrai, mais le serveur refuse les ordres et cela est testé.
