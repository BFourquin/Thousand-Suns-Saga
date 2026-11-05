# Audit du code — Thousand Suns Saga

Audit du 2026-11-01, numérotation du 2026-11-05.

Le code est lisible et bien découpé, mais pas prêt à accueillir des joueurs : 2 failles critiques, 3 bugs critiques qui cassent l'économie ou corrompent les données, et une branche `Postgresql-transition` qui ne démarre plus.

**Périmètre** : les 67 fichiers Python (environ 5 200 lignes : `backend/`, `data/`, `database/`, `geography/`, `actions/`, `statistics/`, `django_tss/`, scripts racine), les templates, le JS maison, la configuration et les modifications non commitées (thèmes). Bibliothèques tierces vendorisées et contenu des fichiers Excel non audités ; rien n'a été exécuté, tous les constats viennent de la lecture du code.

Chaque problème porte un numéro unique, de 1 à 100, à citer pour demander une correction.

**Les 6 points à traiter en premier**

- **1.** N'importe qui peut créer un commandant sur le compte d'un autre joueur (`api_create_commandant` sans authentification).
- **2.** Un joueur peut lire, archiver ou supprimer les rapports des autres (aucun contrôle de propriétaire).
- **16.** Construire un district ne coûte rien : le coût est vérifié mais jamais débité.
- **17.** Supprimer un district laisse une référence morte dans la colonie, qui fait ensuite planter la page colonie.
- **18.** La page Compte boucle indéfiniment dès qu'un joueur a un compte mort.
- **42.** La configuration pointe vers PostgreSQL alors que tout le code parle à MongoDB : l'application quitte dès le démarrage.

## Sécurité

Les API JSON font confiance aux paramètres du client : n'importe qui peut créer un commandant au nom d'un autre joueur, et un joueur connecté peut lire ou supprimer les rapports des autres. Ce sont les deux premières corrections à faire.

| N° | Gravité | Problème | Où | Correction proposée |
| --- | --- | --- | --- | --- |
| 1 | Critique | `api_create_commandant` n'exige pas de connexion et prend l'utilisateur dans `params['user']` : un anonyme crée un commandant sur le compte de n'importe qui, sur n'importe quel serveur (`params['server']` non vérifié). | `backend/views_api_commandant.py:31` | `@login_required`, utilisateur tiré de `request.user`, appel de `valid_commandant_creation` (statut du serveur, multicompte). |
| 2 | Critique | Rapports sans contrôle de propriétaire : `report`, `delete`, `read`, `archive` acceptent n'importe quel `report_id`. Un joueur lit, supprime ou archive les rapports d'un autre. | `backend/views_game.py:223-242, 309` ; `data/report.py:82-99` | Filtrer sur `{'_id': id, 'owner': commandant['_id']}` dans chaque requête. |
| 3 | Haute | `get_user` et `get_commandant` sont publics : ils renvoient tout le profil (e-mail, `is_staff`, `is_superuser`, serveur joué…) de n'importe quel compte par nom ou id. Seul le hash du mot de passe est retiré. Aucun template, script ou module du dépôt ne les appelle. | `backend/views_api_user.py:49` ; `backend/views_api_commandant.py:70` | Supprimer ces deux routes et leurs vues. |
| 4 | Haute | Actions qui modifient l'état via GET : fin de cycle, absences, statut des rapports, préférences, `admin_servers_states_edit`, et toutes les API d'écriture (`api_delete_district`, `api_build_district`, `create_user`…), car `request_params` fusionne GET et POST. La protection CSRF de Django ne couvre pas GET : un lien piégé suffit à finir un cycle, détruire un district ou modifier un serveur. | `backend/utils.py:10` ; `backend/views_game.py:166-188` ; `backend/views_admin.py:92` ; `admin_servers_states.html` | Lire les actions dans `request.POST` uniquement (`@require_POST`) ; `request_params` à proscrire pour les écritures. |
| 5 | Haute | `admin_servers_states_edit` écrit n'importe quel champ (`params['type']`) avec n'importe quelle valeur dans `server_details`. Combiné au point précédent, exploitable par CSRF. | `backend/views_admin.py:92-99` | Liste blanche des champs modifiables, POST + CSRF. |
| 6 | Haute | XSS réfléchi dans l'admin : `server_name_selected` est concaténé dans du HTML rendu avec `{% autoescape off %}`. Un lien piégé exécute du JS dans la session d'un admin (qui a `hijack`). | `backend/views_admin.py:129-162` ; `admin_geography.html:36,97` | Construire les liens dans le template avec échappement, ou `format_html`. |
| 7 | Haute | `test_hijack` sans aucune authentification, charge `User id=2`. | `backend/views_admin.py:56` ; `django_tss/urls.py:107` | Supprimer la vue et la route. |
| 8 | Haute | `settings.py` : `DEBUG = True`, `ALLOWED_HOSTS = ['*']`, `CORS_ALLOW_ALL_ORIGINS = True`. En prod, une erreur affiche la config et les variables locales. | `django_tss/settings.py:36-38, 188` | Variables d'environnement par environnement ; CORS limité au serveur statique. |
| 9 | Moyenne | Mots de passe non validés à l'inscription : `AUTH_PASSWORD_VALIDATORS` n'est jamais appelé (`validate_password`). Un mot de passe d'1 caractère est accepté. | `backend/views_api_user.py:41-45` | `django.contrib.auth.password_validation.validate_password(...)`. |
| 10 | Moyenne | Pas de limitation des tentatives de connexion (joueur et admin). | `backend/views_public.py:37` ; `backend/views_admin.py:16` | `django-axes` ou limitation simple par IP/compte. |
| 11 | Moyenne | Les vues admin ne vérifient que `is_staff` alors que la connexion admin exige `is_superuser` : un compte staff non superuser accède à tout via URL directe. | `backend/views_admin.py:70-121` | Un décorateur unique (`user_passes_test(lambda u: u.is_superuser)`). |
| 12 | Moyenne | Le serveur statique écoute sur `0.0.0.0:33100` avec `Access-Control-Allow-Origin: *` et sert tout `admin_web/static`. | `static_server.py:20` | Servir les statiques via Django/WhiteNoise ou un vrai serveur web. |
| 13 | Moyenne | `pymongo` se connecte sans authentification : `USERNAME`/`PASSWORD` des settings sont ignorés par `db_connect`. MongoDB doit donc tourner sans auth. | `database/db_connect.py:12` | Passer `username`, `password`, `authSource` à `MongoClient`. |
| 14 | Basse | Corps de toast inséré comme HTML par AdminLTE ; `body` reprend une saisie utilisateur (`activation_percent` invalide). | `backend/views_api_buildings.py:75` | Ne pas renvoyer la saisie brute. |
| 15 | Basse | `print()` de paramètres de requête (identifiants inclus lors de l'inscription) dans les logs. | `backend/views_api_user.py:25` ; `views_api_buildings.py:111` ; `views_game.py:66` | Supprimer ou passer par `logging` sans données sensibles. |

Point positif : `settings.py` (mots de passe BDD, `SECRET_KEY`) n'a jamais été commité ; seul `settings_opensource.py`, expurgé, est versionné.

## Bugs et erreurs de logique

19 bugs confirmés à la lecture. Les plus graves cassent l'économie du jeu (construction gratuite) ou corrompent des données (district supprimé mais toujours référencé).

| N° | Gravité | Bug | Où | Effet constaté |
| --- | --- | --- | --- | --- |
| 16 | Critique | Le coût d'un district est vérifié mais jamais débité. | `backend/views_api_buildings.py:43-60` ; `data/districts.py:56` | Construction gratuite et illimitée. |
| 17 | Critique | `delete_district` retire de la colonie l'id `district['_id']` au lieu de `district['colony_id']`. | `data/districts.py:110` | La colonie garde une référence vers un district effacé ; la page colonie plante ensuite (`get_district` renvoie `None`). |
| 18 | Critique | Boucle infinie dans `user_account` : `dead_accounts = user['dead_accounts']` puis on ajoute dans cette même liste en l'itérant. | `backend/views_game.py:46-50` | La page compte ne répond plus dès qu'un compte mort existe. |
| 19 | Haute | `user_account` est défini deux fois (la 2ᵉ copie écrase la 1ʳᵉ). Le diff en cours modifie les deux. | `backend/views_game.py:24` et `:109` | Toute correction faite dans la 1ʳᵉ est ignorée. |
| 20 | Haute | `end_cycle` passe le dict `server` à `update_commandant` au lieu du nom. | `data/cycles.py:131-132` | `TypeError` après création du nouveau cycle : fin de cycle à moitié appliquée. |
| 21 | Haute | `check_available_district_slot` est appelé mais son résultat ignoré dans `create_district` ; la vérification de la vue et l'insertion ne sont pas atomiques. | `data/districts.py:65` | Dépassement des emplacements par double clic ou requêtes parallèles. |
| 22 | Haute | `delete_report` retire l'id en `str` alors que la liste du commandant contient des `ObjectId`. | `data/report.py:97` | Le rapport est effacé mais reste référencé dans `commandant.reports`. |
| 23 | Haute | `valid_commandant_creation` n'est jamais appelée et ne peut pas marcher : `server['status']` sur une `str`, collection `commandant` (au lieu de `commandants`), `find_many` inexistant, pas de `return True`. | `data/commandant.py:13-49` | Aucun contrôle serveur fermé / plein / multicompte / pseudo déjà pris. |
| 24 | Haute | `api_create_commandant` vérifie l'unicité du nom de commandant et de civilisation dans la table des **utilisateurs**. | `backend/views_api_commandant.py:40, 51` | Doublons de commandants possibles ; refus si le nom coïncide avec un pseudo de compte. |
| 25 | Haute | `colonies.append(colonies)` laissé en « test visuel ». | `backend/views_game_colonies.py:38` | La liste se contient elle-même ; le template reçoit une entrée invalide. |
| 26 | Moyenne | `delete_building` itère `build_cost` (dict) en décompactant des tuples. | `data/buildings.py:112` | `ValueError` à chaque destruction de bâtiment. |
| 27 | Moyenne | Remboursement de district calculé sur tous les champs du type (`district_type.items()`), pas sur `build_cost`, et jamais appliqué. | `data/districts.py:123-128` | Aucun remboursement ; `TypeError` possible sur champs non numériques. |
| 28 | Moyenne | `recalculate_buildings_slots` lit `districts_slots` au lieu de `buildings_slots`. | `data/districts.py:134` | Capacité en bâtiments fausse. |
| 29 | Moyenne | `probability_picker` et `random_picker` ont `random_number=random.random()` en valeur par défaut : évalué une seule fois à l'import. `random.seed()` modifie aussi l'état global. | `backend/utils.py:72, 99` | Le même tirage à chaque appel sans argument ; génération de carte biaisée. |
| 30 | Moyenne | `unread_reports_counting` sans liste appelle `get_commandant_reports`, qui renvoie un tuple. | `data/report.py:117-118` | `TypeError` si appelé sans `reports_list`. |
| 31 | Moyenne | `set_dead_user` lit `dead_users`, clé jamais créée (`create_server` crée `previous_users`). `delete_commandant` passe un dict à `pull_param_user` qui attend un id. `delete_server_details` supprime deux fois. | `data/server_details.py:113, 93-95` ; `data/commandant.py:213` | `KeyError` / références non nettoyées. |
| 32 | Moyenne | `create_server` stocke `tz.gettz(...)` (objet non sérialisable en BSON) alors que `get_tz` attend une chaîne. | `data/server_details.py:45, 77` | Création de serveur impossible sans correction manuelle en base. |
| 33 | Basse | La branche POST de `player_register` appelle `authenticate` et ne crée aucun compte. Elle ne sert pas : le formulaire part en AJAX vers `/create_user/`. | `backend/views_public.py:54-72` | Code mort trompeur ; `KeyError` en cas de POST direct sans e-mail. |
| 34 | Basse | Divers : `portrait`/`flag` inversés ; `tech()` ignore ses arguments et `tech_types` a une virgule manquante (`'energy' 'spaceship'`) ; `redirect('/geography_system/', {...})` ignore le 2ᵉ argument ; `create_user` accepte 6–24 caractères alors que le message dit 5–25 ; `add_cycle_info` plante si aucun cycle n'existe ; `geography_system` plante si le système n'existe pas ; `ObjectId(...)` sur une saisie invalide donne une 500. | `data/commandant.py:73-74` ; `data/technology.py:6-25` ; `views_game.py:106, 343` ; `views_api_user.py:28` ; `decorators.py:67` | Erreurs 500 et données incohérentes. |

**Génération de carte** (`geography/`), bugs à part car ils ne touchent que la création d'un serveur :

- **35.** `if sector['sector_type'] == 'border' or 'corner':` est toujours vrai ; la règle de bord s'applique donc à tous les secteurs (`mg_systems_placement.py:24`). La ligne 34 compare `pos_x` à `nb_sectors_axe_y` au lieu de `_x`.
- **36.** `random.randint(0, len(systems_coordinates))` inclut la borne haute : `IndexError` aléatoire (`mg_systems_placement.py:85`). Utiliser `random.choice`.
- **37.** Boucles sans fin possibles : si `nb_natives_start` dépasse `nb_systems` (`mg_systems_placement.py:84`) ou si les règles de placement rejettent toutes les positions (`generate_system_coordinates`).
- **38.** Le nuage d'Oort réutilise la probabilité et la graine de la ceinture d'astéroïdes (`telluric_prob`, suffixe `'002'`) : il y a un nuage d'Oort exactement quand il y a une ceinture (`mg_system_composition.py:170-173`).
- **39.** `random_picker` avec un dict ne regarde que la première clé.
- **40.** `statistics_systems_types_per_sector` regroupe par `_id[:12]` alors qu'un id de secteur fait 10 caractères : les statistiques par secteur sont fausses (`stats_geography.py:14`).
- **41.** `remove_past_generation` vide `planets`, collection inexistante, et pas `coordinates` ni `available_native_planets` : une régénération garde d'anciennes planètes de départ.

## Base de données et transition PostgreSQL

Sur la branche `Postgresql-transition`, l'application ne peut pas démarrer : `settings.py` déclare des bases PostgreSQL, mais toute la couche données reste en `pymongo`. Aucun modèle Django n'existe (`backend/models.py` est vide) et `psycopg` n'est utilisé nulle part.

**Ce qui casse aujourd'hui**

- **42.** `database/db_connect.py` boucle sur `DATABASES` et ouvre `mongodb://localhost:5432/` avec pymongo. Le port 5432 est PostgreSQL : `server_info()` échoue au bout de 30 s puis `sys.exit()`, dès l'import du premier module `data/*`.
- **43.** Même si la connexion passait, `User.objects.create_user` écrirait les comptes dans PostgreSQL alors que `data/user.py` relit `auth_user` dans MongoDB : un compte créé serait introuvable (`get_user_by_name` → `None`).
- **44.** Tout le code dépend de types Mongo : `ObjectId` (bson) dans 15 fichiers, opérateurs `$push`, `$pull`, `$lookup`, documents imbriqués (`resources` dans le commandant, listes d'ids dans colonies et districts).

**Problèmes de la couche données, à corriger quelle que soit la base**

- **45.** Aucune transaction : `create_commandant` enchaîne 7 écritures (commandant, utilisateur, serveur, colonie, district, emplacements, rapport). Une erreur au milieu laisse un état partiel. `try: ... except Exception as e: raise e` n'apporte rien.
- **46.** Lecture-modification-écriture non atomiques : `resource_change` (devrait être un `$inc` conditionnel ou un `UPDATE ... WHERE stock >= x`), `add_active_user`, `add_active_commandant`, `create_commandant` (liste `accounts`). Deux requêtes simultanées perdent une écriture.
- **47.** Relations stockées dans les deux sens (colonie → districts et district → colonie, commandant → rapports et rapport → owner) sans contrainte : c'est l'origine des références orphelines de la section Bugs. En SQL, une clé étrangère `ON DELETE CASCADE` suffit.
- **48.** Une base par serveur de jeu, déclarée à la main dans `settings.py` (`create_new_server.py:50`). En SQL, une seule base avec une colonne `server_id` simplifie migrations, sauvegardes et requêtes inter-serveurs (`get_commandant_from_any_server` parcourt toutes les bases).
- **49.** Aucun index créé (`create_tables.py` crée les collections seulement). Requêtes fréquentes sur `username`, `internal_name`, `commandant_name`, `controller`, `server_name`, `cycle_nb`.
- **50.** Noms incohérents : `create_tables` crée `reports`, le code écrit dans `report` ; `valid_commandant_creation` lit `commandant`.
- **51.** `set_system`, `set_sector`, `set_coordinate` font `delete_one` + `insert_one` au lieu d'un `replace_one(..., upsert=True)`.
- **52.** `starting_values` : clés `starting_resources` et `starting_ressources` coexistent ; `start_type` est ignoré dans `starting_values_ressources`.

**Recommandation pour la migration** : définir les modèles Django (User étendu via `OneToOneField` ou `AbstractUser`, Server, Commandant, Colony, District, Building, Report, Cycle, types en tables de référence), migrer module par module derrière les fonctions existantes de `data/*` (leur signature isole déjà les vues de la base), et écrire un script d'import Mongo → PostgreSQL. Tant que ce n'est pas fait, garder `DATABASES` sur Mongo pour que la branche reste exécutable.

## Architecture et organisation du code

Le découpage vues (`backend/`) / accès données (`data/`) / génération (`geography/`) est sain ; ce qui pèse, c'est la duplication, le code mort et l'absence de couche commune pour l'authentification et la validation.

**Duplication**

- **53.** Chaque fonction de `data/*` répète `client = databases['TSS_' + server]; db = client['x']`, et chaque collection a ses propres `update_*` / `push_param_*` / `pull_param_*` copiés (commandant, colonie, district, cycle, user). Un helper `collection(server, name)` et trois fonctions génériques suffisent.
- **54.** `buildings_types.py` est un copier-coller de `districts_types.py` (le code le dit : « copier coller des districts à vérifier »).
- **55.** Trois `info_from_seed` différents (`backend/utils.py`, `data/systems.py`, `geography/mg_coordinate.py`) et deux `request_params` (`backend/utils.py`, `views_api_user.py`).
- **56.** Le début de chaque vue de jeu est identique (récupérer serveur + commandant, rediriger sinon, vérifier que la colonie appartient au joueur). À regrouper dans un décorateur `@commandant_required` qui injecte `server`, `commandant`.
- **57.** Les trois chargeurs Excel (`load_technologies`, `load_resources`, `load_buildings`) et `excel_importer` partagent la même boucle (lignes `#`, `END_OF_FILE`, entête `internal_name`).

**Code mort ou de test laissé en place**

- **58.** Vues/routes : `test_hijack`, `bokeh_exemple` (sans route), `api_can_join_server` (inachevée, sans route), `admin.site.urls` (marqué TODO Remove).
- **59.** Templates : `colony_old.html`, `geography_systemOLD.html`, `admin_raw_json.html`, `bokeh_*`.
- **60.** Fonctions jamais appelées ou vides : `valid_commandant_creation`, `give_starting_resources`, `cheat_log`, `check_if_colonisable` (renvoie toujours `True`), `remove_redundant_info` / `recreate_redundant_info`, `actions/building.py` (commentaires seuls), `geography/planet.py` (vide).
- **61.** Blocs `if __name__ == '__main__'` qui écrivent en base avec des ids en dur (`data/buildings.py:131`, `data/cycles.py:138`, `data/commandant.py:218`) : un `python data/commandant.py` supprime un vrai commandant.
- **62.** Gros blocs commentés ou en chaîne (`views_game.py:259-278`, fin de `server_details.py`).
- **63.** 61 `TODO` et 37 `print()` dans le code Python.

**Couplage et structure**

- **64.** Le dossier `statistics/` masque le module standard `statistics` de Python : toute bibliothèque qui fait `import statistics` reçoit le paquet du projet. À renommer (`tss_statistics/`).
- **65.** Connexion à la base à l'import (`db_connect.py:25`) avec `sys.exit()` en cas d'échec : impossible de tester un module sans base, et un import qui tue le process.
- **66.** Imports circulaires contournés par des imports locaux (`data.report` dans `create_commandant`, `data.commandant` dans `new_colony`) ; `districts` ↔ `colonies` ↔ `buildings` s'importent mutuellement.
- **67.** `create_new_server.py` est un script avec paramètres en dur en tête de fichier et exécution à l'import ; à transformer en commande Django (`manage.py create_server --name ... --excel ...`).
- **68.** Les identifiants mélangent `str`, `int` et `ObjectId` selon les fonctions (seeds en `str` puis `int`, ids convertis ou non) ; source directe de bugs comme `delete_report`.
- **69.** Les erreurs métier sont renvoyées comme chaînes (`'created'`, `'Planet is not colonisable'`) au lieu d'exceptions ou de résultats typés.
- **70.** Textes en dur en français dans les vues et API alors que le projet a `gettext`/Rosetta ; `name_' + 'fr'` codé en dur dans `resources`.

## Performance et tenue en charge

Une page de jeu déclenche environ 20 requêtes en base avant même la logique de la vue, plus une par commandant du serveur. Ça tient à quelques joueurs, pas à quelques centaines.

- **71.** **Utilisateur relu 6 à 8 fois par requête** : `get_user_by_name` (2 requêtes chacun) est appelé par 3 context processors, `log_player_action`, `add_cycle_info`, `get_active_server_and_commandant_from_request` et la vue. À charger une fois dans un middleware et poser sur `request`.
- **72.** **`servers_details`** fait 3 parcours complets de `server_details` à chaque page, même publique. À mettre en cache (quelques minutes).
- **73.** **N+1 dans `add_cycle_info`** : une requête par commandant du cycle, sur chaque page de jeu. Une requête `$in` suffit.
- **74.** **N+1 dans la page colonie** : par district, `get_district` + `get_district_type` + `get_language` (2 requêtes) + bâtiments ; `get_all_buildable_districts_types` fait une requête par ressource et par type de district.
- **75.** **Une écriture par page vue** (`log_player_action` met à jour `time_last_activity`), y compris en simple lecture.
- **76.** **Rapports** : tous les rapports du commandant sont chargés puis filtrés et paginés en Python ; `update_nb_unread_reports` les recharge tous après chaque action et les affiche avec `print`. Filtrer, compter et paginer côté base.
- **77.** **Aucun index** (voir section Base de données).
- **78.** **Génération de carte** : chaque secteur, système et coordonnée est écrit un par un en `delete_one` + `insert_one`, chaque secteur est relu plusieurs fois, et les paramètres du générateur sont relus pour chaque secteur. Utiliser `insert_many` / `bulk_write` en mémoire puis une écriture finale.
- **79.** **Admin géographie** charge tous les systèmes ou toutes les coordonnées d'un serveur dans une seule page (le code le signale lui-même). Paginer.
- **80.** **Serveur statique** : `http.server` mono-thread de la bibliothèque standard sert toutes les images, CSS et JS. `adminlte.css` est chargé non minifié (52 000 lignes) au lieu de `adminlte.min.css`.
- **81.** **`translation.activate` dans un context processor** : appelé pendant le rendu, donc trop tard pour les textes produits par la vue, et jamais désactivé : la langue d'un joueur peut fuir vers la requête suivante servie par le même thread. Utiliser un middleware (ou `LocaleMiddleware` + préférence en session).

## Front-end, templates et assets

Le front repose sur AdminLTE 3 importé en entier : environ 40 bibliothèques sont dans `admin_web/static/libraries`, une dizaine seulement sont référencées par les templates.

- **82.** **Appels API** (`includes/form_submit_to_json_api.js`) : l'option `done` n'existe pas dans `$.ajax` (c'est `success`), et les succès sont renvoyés en HTTP 302 sans en-tête `Location`, que jQuery traite comme une erreur. Ça marche par accident via le callback `error`. Renvoyer 200 avec le champ `redirect`.
- **83.** **Assets inutilisés versionnés** : démos AdminLTE (`dist/js/demo.js`, `dashboard*.js`), variantes CSS `dist/css/alt/*` (55 000 lignes), statiques de l'admin Django (126 fichiers, déjà fournis par Django). Le dépôt `.git` pèse 120 Mo, surtout en images et fichiers Excel.
- **84.** **CSS non minifié** : `adminlte.css` au lieu de `adminlte.min.css` (voir Performance).
- **85.** **Dépendances externes au chargement** : Google Fonts et Ionicons 2.0.1 depuis `code.ionicframework.com`. Points de défaillance et transfert d'IP vers des tiers (RGPD) ; à héberger localement.
- **86.** **Templates morts** : `colony_old.html`, `geography_systemOLD.html`, `bokeh_*`, `test_hijack.html`, `admin_raw_json.html`.
- **87.** **Internationalisation incomplète** : `<html lang="fr">` fixe ; `{% blocktranslate %} {{title}} {% endblocktranslate %}` ne traduit pas une variable ; libellés en dur en français dans les vues et API.
- **88.** **Styles et scripts en ligne** : 211 attributs `style="..."` et 47 balises `<script>` dans les templates. Freine la maintenance des thèmes (le nouveau système de thèmes devra surcharger ces styles en ligne) et empêche une Content-Security-Policy.
- **89.** **Données fictives affichées comme réelles** : la page Ressources affiche des valeurs figées (stockage 20 000, production 178, consommation 80…) pour toutes les ressources (`views_game.py:404-411`).
- **90.** **Thèmes (travail en cours, non commité)** : la validation par liste blanche (`is_valid_theme`) est correcte. Le chemin `{% static "css/themes/theme_" %}{{ theme }}.css` contourne `static` et casserait avec un `ManifestStaticFilesStorage` ; préférer `{% static 'css/themes/theme_'|add:theme|add:'.css' %}`. Les noms de thèmes sont en français en dur dans `data/themes.py`.

## Configuration, dépendances, tests et outillage

Aucun test, aucune CI et des dépendances non épinglées : on ne peut ni reproduire l'environnement ni savoir si une modification casse quelque chose.

| N° | Sujet | Constat | Action proposée |
| --- | --- | --- | --- |
| 91 | Tests | `backend/tests.py` est vide ; aucun autre test. `pytest` est listé mais inutilisé. | Commencer par les règles métier fragiles : coût et emplacements de district, propriété des rapports, cycles, `probability_picker`, `seed_convertor`. |
| 92 | CI | Pas de `.github/workflows`. | Workflow minimal : installation, `manage.py check --deploy`, tests, `ruff`. |
| 93 | Versions | `requirements.txt` sans versions ; `requirements_versionning.txt` (Django 3.2.9) et `requirements_OLD.txt` ne correspondent pas au venv (Django 4.1.3). Django 3.2 et 4.1 ne sont plus maintenus. | Un seul fichier épinglé (`pip freeze` ou `pip-tools`), montée vers Django 5.2 LTS. |
| 94 | Dépendances inutiles | Flask, Flask-Cors, djangorestframework, django-filter, PyYAML, Markdown, watchdog, argh, pathtools ne sont importés nulle part. `djongo` n'est plus maintenu et impose `sqlparse==0.2.4` (version avec failles connues). | Supprimer ; retirer `djongo` avec la migration PostgreSQL. |
| 95 | Dépendances manquantes | `python-dateutil` est importé mais pas déclaré (arrive par transitivité). | Le déclarer. |
| 96 | Settings | Un seul `settings.py` local non versionné contenant secrets et choix d'environnement ; `settings_opensource.py` lève une exception dès l'import et a dérivé (pas de Rosetta, Hijack, ni des 3 context processors). | `settings.py` versionné qui lit les secrets dans l'environnement (`.env` + `django-environ`), fichiers `dev` / `prod`. |
| 97 | Lancement | Scripts `.bat` Windows uniquement, `mongod.lnk` versionné, serveur statique séparé à lancer à la main. | Documenter dans le README ; servir les statiques par Django en dev ; Docker Compose (app + base) pour un environnement reproductible. |
| 98 | Données de jeu | Toute la configuration (bâtiments, ressources, technos, générateur) vit dans `TSS.xlsx` / `TSS_boardgame.xlsx` : binaires, sans diff ni relecture possible. `db.mdj` (14 000 lignes) est un modèle StarUML probablement obsolète. | Exporter en CSV/YAML versionné (l'Excel peut rester l'outil d'édition) ; valider les schémas au chargement. |
| 99 | Qualité | Pas de linter ni de formateur ; 37 `print()` au lieu de `logging` ; `except:` nus (`views_api_user.py:36`, `commandant.py:48, 165`, `user.py:6`) qui masquent les erreurs. | `ruff` + `ruff format` en pre-commit ; `logging` configuré dans les settings. |
| 100 | Nommage | Fichier `geography/Hertzsprung-Russel Diagram.py` (espace, non importable) ; mélange français/anglais (`ressources`, `exemple`) ; fautes de frappe dans des clés stockées en base (`starting_ressources`). | Renommer au fil des corrections ; les clés en base à traiter avec la migration. |

## Plan d'action priorisé

Ordre proposé : fermer les failles exploitables, corriger ce qui corrompt les données, puis seulement poursuivre la migration PostgreSQL sur une base de code assainie et testée.

**Immédiat — failles et blocages (environ 1 jour)**

- [ ] `api_create_commandant` : `@login_required`, utilisateur depuis `request.user`, contrôles serveur.
- [ ] Rapports : filtrer toutes les opérations sur `owner = commandant['_id']`.
- [ ] Supprimer `get_user` / `get_commandant`.
- [ ] Supprimer `test_hijack` et sa route.
- [ ] Passer toutes les actions qui écrivent en POST uniquement (cycles, rapports, préférences, admin, API).
- [ ] Retirer `autoescape off` de `admin_geography.html`.
- [ ] Supprimer le doublon `user_account` et corriger la boucle infinie `dead_accounts`.
- [ ] Remettre `DATABASES` sur MongoDB (ou isoler la config PostgreSQL) pour que la branche redémarre.

Numéros concernés : 1 à 7, 18, 19, 42, 43.

**Court terme — intégrité du jeu**

- [ ] Débiter le coût de construction, de façon atomique avec la vérification.
- [ ] Corriger `delete_district` (`colony_id`) et nettoyer les colonies déjà corrompues.
- [ ] Corriger `end_cycle`, `delete_report`, `delete_building`, `recalculate_buildings_slots`.
- [ ] Brancher `valid_commandant_creation` (réécrite) dans la création de commandant.
- [ ] Retirer `colonies.append(colonies)` et les données fictives de la page Ressources.
- [ ] Valider les mots de passe à l'inscription ; retirer la branche morte de `player_register`.
- [ ] Corriger les valeurs par défaut de `random_number` dans `probability_picker` / `random_picker`.
- [ ] Premiers tests automatisés sur ces correctifs + CI minimale.

Numéros concernés : 9, 16, 17, 20 à 26, 28, 29, 33, 89, 91, 92.

**Moyen terme — socle**

- [ ] Décorateur `@commandant_required` et chargement unique de l'utilisateur par requête (middleware).
- [ ] Settings par environnement avec secrets en variables d'environnement ; `DEBUG=False`, `ALLOWED_HOSTS`, CORS restreint.
- [ ] `requirements.txt` épinglé, dépendances inutiles retirées, Django LTS.
- [ ] Renommer `statistics/` ; supprimer code et templates morts ; `logging` à la place des `print`.
- [ ] Index sur les champs de recherche ; corriger les N+1 (cycle, colonie, rapports).
- [ ] Corriger les bugs du générateur de carte et passer en écritures groupées.

Numéros concernés : 8, 35 à 41, 49, 56, 58 à 64, 71, 73, 74, 76 à 78, 86, 93 à 96, 99.

**Migration PostgreSQL**

- [ ] Modèles Django pour utilisateur étendu, serveur, commandant, colonie, district, bâtiment, rapport, cycle, types.
- [ ] Une seule base avec `server_id` plutôt qu'une base par serveur.
- [ ] Réécrire `data/*` module par module derrière les mêmes signatures, avec transactions (`transaction.atomic`).
- [ ] Script d'import MongoDB → PostgreSQL et vérification des comptes.
- [ ] Retirer `pymongo`, `djongo`, `bson` et `db_connect.py`.

Numéros concernés : 44 à 48, 65, 94.
