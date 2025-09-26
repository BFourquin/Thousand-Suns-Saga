import datetime
from random import randint
from bson.objectid import ObjectId

from database.db_connect import databases
from data import server_details
from data import starting_values as sv
from data.user import get_user_by_name, update_user, pull_param_user
from actions import colonize
from backend import utils


def valid_commandant_creation(server, user, pseudo,
                              admin_override=False, game_wide_pseudo_restriction=True):

    client = databases['TSS_' + server]

    # Server authorize new accounts
    if server['status'] != 'open' and not user['is_superuser']:
        return False, "Ce serveur n'autorise pas de nouveaux joueurs"

    # Server is not full
    if not sv.get_starting_values(server)['available_native_planets'] :
        return False, "Ce serveur ne possède plus de places disponibles"


    # Iterate all commandants in the server
    for commandant in client['commandant'].find_many({}):

        # Name already taken
        if commandant['pseudo'].lower() == pseudo.lower():
            return False, 'Un commandant porte déjà ce nom'

        # Owner already have an account
        if commandant['user_id'] == user['_id'] \
                and not server['allow_multiaccounts'] \
                and not user['is_superuser']:
            return False, 'Vous possédez déjà un compte'

    # Can't take name of a previous commandant, even from previous server
    if game_wide_pseudo_restriction:
        for server_name in server_details.get_servers_names():
            try:
                client = databases['TSS_' + server_name]
                for commandant in client['commandant'].find_many({}):
                    if commandant['pseudo'].lower() == pseudo.lower():
                        return False, 'Un commandant porte déjà ce nom'
            except:
                ... # TODO



def create_commandant(server, user, commandant_name, civilisation_name):

    try:

        client = databases['TSS_' + server]
        db = client['commandants']

        user = get_user_by_name(user)
        starting_values = sv.get_starting_values(server)

        starting_planet_id = starting_values['available_native_planets'][randint(0, len(starting_values['available_native_planets'])-1)]

        commandant = {

            # Account parameters
            'id': None,  # Get it later
            'commandant_name': commandant_name,
            'civilisation_name': civilisation_name,
            'gender': 'm',  # TODO gender

            'portrait': 'images/commandants/default_flag.jpg',
            'flag': 'images/commandants/default_portrait.jpg',

            'server': server,
            'status': 'active',
            'user_id': user['_id'],
            'user_name': user['username'],
            'creation_date': datetime.datetime.now(),

            # Starting position
            'native_entente': None,  # TODO native_faction
            'native_sector': utils.info_from_seed(starting_planet_id)['sector_id'],
            'native_system': utils.info_from_seed(starting_planet_id)['system_id'],
            'native_planet': starting_planet_id,

            # Empire and allegiances
            'capital': None,
            'colonies': [],
            'resources': starting_values['starting_resources'],
            'technologies': starting_values['starting_technologies'],
            'player_modifiers': starting_values['starting_modifiers'],
            'owned_ship_designs': [],
            'orientations': {},

            # Reports
            'reports': [],
            'nb_unread_reports': 0,

            # Other
            'tutorial_step': None}


        db.insert_one(commandant)

        # Add commandant reference to user
        commandant_id = get_commandant_by_name(server, commandant_name)['_id']
        accounts = user['accounts']
        accounts.append(commandant_id)
        update_user(user, 'accounts', accounts)

        update_commandant(server, commandant_id, 'id', commandant_id)  # Add id field (django template can't read '_id')

        # Add commandant and user references to server_details
        server_details.add_active_user(server, user['_id'])
        server_details.add_active_commandant(server, commandant_id)


        # Starting colony
        colonize.colonize(server, commandant_id,
                          fleet_id=None,
                          coordinate_seed=starting_planet_id,
                          colony_name=None,
                          colony_type='starting_colony',
                          central_district_type='district_territory',
                          admin_force_action=True)

        # Welcome and tutorial report
        from data.report import create_report  # Placed here to prevent circular import
        create_report(server, commandant_id, 'welcome_on_TSS')

        return 'created'

    except Exception as e:
        raise e
    #    return e


def get_commandant_by_object_id(server, _id):
    client = databases['TSS_' + server]
    db = client['commandants']
    return db.find_one({'_id': ObjectId(_id)})


def get_commandant_by_name(server, name):
    client = databases['TSS_' + server]
    db = client['commandants']
    return db.find_one({'commandant_name': name})


def get_commandant_from_any_server(name=None, _id=None):

    from django_tss.settings import DATABASES
    for db_name in DATABASES.keys():
        if db_name == 'default':
            continue

        try:
            client = databases['TSS_' + db_name]
            db = client['commandants']
        except:
            continue

        if name:
            result = db.find_one({'commandant_name': name})
            if result:
                return result

        if _id:
            result = db.find_one({'_id': ObjectId(_id)})
            if result:
                return result


def update_commandant(server, commandant_id, param, value):
    # Modifies an existing document or documents in a collection

    client = databases['TSS_' + server]
    db = client['commandants']
    db.update_one({"_id": commandant_id}, {"$set": {param: value}})


def push_param_commandant(server, commandant_id, param, value):
    # Appends a specified value to an array

    client = databases['TSS_' + server]
    db = client['commandants']
    db.update_one({"_id": commandant_id}, {"$push": {param: value}})


def pull_param_commandant(server, commandant_id, param, value):
    # Removes from an existing array all instances of a value or values that match a specified condition.

    client = databases['TSS_' + server]
    db = client['commandants']
    db.update_one({"_id": commandant_id}, {"$pull": {param: value}})


def delete_commandant(server, commandant_id):
    # /!\ TEST AND ADMIN ACTION ONLY (removal of the commandant and any mention in user account)
    # Use commandant_death() instead for normal endgame or death of a player

    client = databases['TSS_' + server]
    db = client['commandants']

    commandant = get_commandant_by_object_id(server, commandant_id)
    user = get_user_by_name(commandant['user_name'])

    pull_param_user(user, 'accounts', ObjectId(commandant_id))  # Remove reference from user table
    db.delete_one({"_id": ObjectId(commandant_id)})



if __name__ == '__main__':
    server = 'Alpha_test'
    delete_commandant(server, get_commandant_by_name(server, 'Paullus Beneradane')['_id'])
