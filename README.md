
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


***
***
### TECHNICAL STACK

Language : Python / HTML / JS  \
Framework : Django  \
Template : AdminLTE  \
Translation : Rosetta



***
### INSTALLATION

- Install Gettext and reboot > (Windows version) https://mlocati.github.io/articles/gettext-iconv-windows.html



***
### NEW SERVER



***
### TRANSLATION

The project use the integrated Django i18n associated with Rosetta.  \
In HTML templates, text to translate need to be in a trans tag as such > {% trans 'Bonjour!' %}

The following command will search the project for text to translate > makemessages -l en --ignore=venv

You can access the Rosetta interface to do the translation at > (you_site.com)/rosetta  \
or via the default Django admin page

