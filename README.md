
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
Databse : MongoDB / Influx V2 \
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


**MongoDB**

- Install MongoDB (Community Edition) (https://www.mongodb.com/try/download/community) \
  Include during installation MongoDB Compass


- Run the script {project folder}/database/create_tables.py


**Django**

- Open a console and write
  > python manage.py makemigrations\
  > python manage.py migrate
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

***
### TRANSLATION

The project use the integrated Django i18n associated with Rosetta as interface.  \
In HTML templates, text to translate need to be in a trans tag as such > {% trans 'Bonjour!' %}

The following command will search the project for text to translate > makemessages -l en --ignore=venv --ignore=README.md

A few texts are generated on the API/backend side of the program and won't be discovered by the i18n script
You can add them inside the following file : static/templates/public/translations.txt

You can access the Rosetta interface to do the translation at > (you_site.com)/rosetta  \
or via the default Django admin page
