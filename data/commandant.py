import datetime

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from database.db_connect import clients
from data import starting_values as sv



def valid_commandant_creation(server, user, pseudo):

    client = clients['TSS_'+server]

    # Pseudo

    # Server authorize new accounts
    if server['status'] != 'open' and not user['is_superuser']:
        return False, "Ce serveur n'autorise pas de nouveaux joueurs"

    # Iterate all commandants in the server
    for commandant in client['commandant'].find_many({}):

        # Name already taken
        if commandant['pseudo'].lower() == pseudo.lower():
            return False, 'Pseudo déjà pris'

        # Owner already have an account
        if commandant['user_id'] == user['_id'] \
                and not server['allow_multiaccounts'] \
                and not user['is_superuser']:
            return False, 'Vous possédez déjà un compte'


def create_commandant(server, user, pseudo):

    client = clients['TSS_'+server]
    db = client['starting_values']
    starting_values = sv.get_starting_values(server)

    commandant = {

        # Account parameters
        'server': server,
        'user_id': user['_id'],
        'user_name': user['username'],
        'pseudo': pseudo,
        'creation_date': datetime.datetime.now(),

        # Empire and allegiances
        'native_faction': starting_values['starting_factions'],
        'native_planet': starting_values['starting_planets'],
        'capital': starting_values['starting_capital'],
        'territories': starting_values['starting_territories'],
        'resources': starting_values['starting_ressources'],
        'technologies': starting_values['starting_technologies'],
        'player_modifiers': starting_values['starting_modifiers'],
        'owned_ship_designs': [],

        # Other
        'tutorial_step': None}

    db.insert_one(commandant)
