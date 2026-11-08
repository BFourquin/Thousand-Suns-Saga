
# THOUSAND SUNS SAGA


![TSS Intro](https://i.ibb.co/nD16Htk/Git-Intro.png)


- Space exploration and colonization
- Land and space warfare
- Spaceship designer
- Vast technology tree
- Many resources to mine / fabricate
- Many buildings and complex industrial management
- Markets for resources, ships, weapons
- Lightly randomized techs and equipment (ever-changing meta)
- Diplomacy with other players' space empires


## Work in progress, estimated ~2026

<< [Screenshots of the pre-alpha](SCREENSHOTS.md) >>


***
***
### TECHNICAL STACK

Language : Python / HTML / JS  \
Database : PostgreSQL \
Framework : Django  \
Template : AdminLTE


***
### INSTALLATION


**Python**

- Install Python 3.11.9 (https://www.python.org/downloads/) \
  Add option "Add python.exe to PATH" in the installer


- Get the project code from :
  > https://github.com/BFourquin/Thousand-Suns-Saga

- Open a console and write
  > cd {project folder} \
  > python -m pip install -r requirements.txt


**Secrets**

The confidential values live in the folder secrets/, ignored by git. Create it with these two files :

secrets/postgres.ini
```ini
[postgres]
name = TSS_main_server
user = admin
password = your_password
host = localhost
port = 5432
```

secrets/django.ini
```ini
[django]
secret_key = generated_with_the_command_below
site_url = http://127.0.0.1
```
> python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"

secrets/map.ini, optional on a test server : the salt of every map, so that nobody draws a map again from the seed of its Excel
```ini
[map]
secret = any_long_random_text
```
Changing it changes every map generated afterwards : keep it with the backups of the database.


**PostgreSQL**

- Install PostgreSQL (https://www.postgresql.org/download/)


- Create the role and the database, with the user and password of your secrets/postgres.ini : \
  (CREATEDB is only there to let `manage.py test` create its test database)
  > psql -U postgres -c "CREATE ROLE admin LOGIN CREATEDB PASSWORD 'your_password'" \
  > psql -U postgres -c "CREATE DATABASE \"TSS_main_server\" OWNER admin TEMPLATE template0 ENCODING 'UTF8'"


**Django**

- Open a console and write
  > python manage.py migrate \
  > python manage.py createsuperuser

The last command will ask name and password to create your django admin account

***
### RUNNING THE WEBSERVER

Run the following scripts :

- static_server.bat
- runserver.bat


***
### CREATE NEW GAME SERVERS

The game need a Excel configuration file with all the server configuration. \
Every technology, building, resource and even the map geography generator have to be specified here.

Ask Iranis#8652 on Discord for a valid config Excel, 
or create a new one from scratch with the exemple provided in TSS.xlsx

Modify create_new_server.py with the appropriate server name and parameters and run the script.

All the game servers live in the same PostgreSQL database : the schema TSS_main_server holds the accounts and
the list of servers, each game server has its own schema TSS_{server name}.

After a change of the models of the app game, apply the migrations to every server :
> python manage.py makemigrations game \
> python manage.py migrate_servers


***
### SCHEDULED STEPS AND ANTICHEAT

The end of the cycles and the anticheat checks run at the local hours of each server : the columns hour_* of
backend_server, from the sheet Config of the Excel. An empty hour means nothing automatic, and a skirmish server is
always manual. They need a system scheduler running this command every 5 minutes, whatever the servers :

> */5 * * * * cd /path/to/project && python manage.py run_schedule

Changing an hour in the database is enough, the next run takes it into account. A step that fails blocks its server
until an admin unblocks it on /admin_servers_states/, and a step missed during a breakdown is skipped, never caught up :
see data/schedule.py.

The journal of the players and the alerts are in the schema TSS_anticheat, the alerts can be read on /admin_cheat_alerts/.
The IP addresses are read from REMOTE_ADDR : behind a reverse proxy, adapt `client_ip` in data/admin.py first,
or all the players will seem to share one IP.


***
### TRANSLATION

The project use the integrated Django i18n associated with Rosetta as interface.  \
In HTML templates, text to translate need to be in a trans tag as such > {% trans 'Bonjour!' %}

The following command will search the project for text to translate > makemessages -l en --ignore=venv --ignore=README.md

A few texts are generated on the API/backend side of the program and won't be discovered by the i18n script
You can add them inside the following file : static/templates/public/translations.txt

You can access the Rosetta interface to do the translation at > (you_site.com)/rosetta  \
or via the default Django admin page
