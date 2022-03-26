import datetime

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from database.db_connect import clients
from data import player_starting_values



def valid_player_creation(server, user, pseudo):

    client = clients['TSS_'+server]

    # Pseudo

    # Server authorize new accounts
    if server['status'] != 'open' and not user['is_superuser']:
        return False, "Ce serveur n'autorise pas de nouveaux joueurs"

    # Iterate all players in the server
    for player in client['player'].find_many({}):

        # Name already taken
        if player['pseudo'].lower() == pseudo.lower():
            return False, 'Pseudo déjà pris'

        # Owner already have an account
        if player['user_id'] == user['_id'] \
                and not server['allow_multiaccounts'] \
                and not user['is_superuser']:
            return False, 'Vous possédez déjà un compte'





def create_player(server, user, pseudo):

    client = clients['TSS_'+server]
    db = client['player_starting_values']
    starting_values = player_starting_values.get_starting_values(server)

    player = {}

    # Account parameters
    player['server'] = server
    player['user_id'] = user['_id']
    player['user_name'] = user['username']
    player['pseudo'] = pseudo
    player['creation_date'] = datetime.datetime.now()

    # Empire and allegiances
    player['native_faction'] = starting_values['starting_factions']
    player['native_planet'] = starting_values['starting_planets']
    player['capital'] = starting_values['starting_capital']
    player['territories'] = starting_values['starting_territories']

    # Other
    player['resources'] = starting_values['starting_ressources']
    player['technologies'] = starting_values['starting_technologies']
    player['player_modifiers'] = starting_values['starting_modifiers']
    player['owned_ship_designs'] = []
    player['tutorial_step'] = None

    db.insert_one(player)
