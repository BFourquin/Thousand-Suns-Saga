
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
Framework : Django  \
Template : AdminLTE


***
### INSTALLATION


**Serveur Web Catalogue Digital**

- Install Python 3.11.9 (https://www.python.org/downloads/) \
  Add option "Add python.exe to PATH" in the installer

- Get the project code from :
  > https://github.com/BFourquin/Thousand-Suns-Saga

- Open a console and write
  > cd {répertoire du projet} \
  > python -m pip install -r requirements.txt


**MongoDB**

- Install MongoDB (Community Edition) (https://www.mongodb.com/try/download/community) \
  Include during installation MongoDB Compass \

- Run the script {project folder}/database/create_tables.py


**InfluxDB**

- Install InfluxDB Open Source v2.x (https://www.influxdata.com/downloads/)

- Execute {project folder}/influxd.bat

- Connect on the Influx interface at http://localhost:8086/ \
  Fill the form for the admin account creation \
  Keep the API token (/!\ can't be retrieved later)

- Create a file token.txt at the following place : {project folder}/data/influxdb/token.txt \
  Paste the admin account token in the file


***
### RUNNING THE WEBSERVER

Run the following scripts :

- influxd.bat
- static_server.bat
- runserver.bat


***
### CREATE NEW GAME SERVERS

TODO

***
### TRANSLATION

The project use the integrated Django i18n associated with Rosetta.  \
In HTML templates, text to translate need to be in a trans tag as such > {% trans 'Bonjour!' %}

The following command will search the project for text to translate > makemessages -l en --ignore=venv --ignore=README.md

You can access the Rosetta interface to do the translation at > (you_site.com)/rosetta  \
or via the default Django admin page