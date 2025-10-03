
import datetime
from dateutil import tz

from database.db_connect import databases
from data import commandant

client = databases['TSS_main_server']
db = client['server_details']


# SERVER STATUS :
server_status = ('open',  # users can create an account and play
                 'close',  # users can play but not create new accounts
                 'test',  # only superuser can create an account
                 'stop',  # the server is fixed in time at the end of the game, no new account or any order,
                 'dead')  # everything shut down


def create_server(server_name, version, status='test', admin_only_visibility=True,
                  language='fr', roleplay='HRP', gameplay='saga', timezone='Europe/Paris'):

    if get_server_details(server_name):
        raise Exception("'" + server_name + "' already exist.")
    if status not in server_status:
        raise Exception("'" + status + "' is not valid as a server state.")

    server_details = {'server_name': server_name,
                      'version': version,
                      'gameplay': gameplay,
                      'status': status,
                      'admin_only_visibility': admin_only_visibility,
                      'creation_date': datetime.datetime.today(),
                      'opening_date': datetime.datetime.now(),
                      'end_date': None,
                      'language': language,
                      'roleplay': roleplay,
                      'allow_multiaccounts': False,

                      'active_users': [],
                      'previous_users': [],
                      'active_commandants': [],
                      'dead_commandants': [],

                      'timezone': tz.gettz(timezone),
                      }

    return db.insert_one(server_details)


def get_servers_names(open_servers=True, playable_servers=True, test_servers=True, old_servers=True, admin_visibility=False):
    servers_list = []
    for server in db.find({}):

        if server['admin_only_visibility'] and not admin_visibility:
            continue

        status = server['status']
        if (open_servers and status == 'open' ) or \
           (playable_servers and status in ('open', 'close') ) or \
           (test_servers and status == 'test' ) or \
           (old_servers and status in ('stop', 'dead') ):
                servers_list.append(server['server_name'])

    return servers_list


def get_server_details(server_name):
    return db.find_one({'server_name': server_name})


def get_all_servers_details():
    return list(db.find({}))


def get_tz(server_name):
    return tz.gettz(get_server_details(server_name)['timezone'])


def change_server_param(server_name, param, param_value):
    db.update_one({'_id': get_server_details(server_name)['_id']},
                  {"$set": {param: param_value}})


def delete_server_details(server_name):
    # To be used only on test servers !

    commandants_list = get_server_details(server_name)['active_commandants'] + \
                       get_server_details(server_name)['dead_commandants']
    for commandant_id in commandants_list:
        commandant.delete_commandant(server_name, commandant_id)

    db.delete_one({'server_name': server_name})

    return db.delete_one({'server_name': server_name})


########################################################################################################################
# Players lists

def add_active_user(server_name, user_id):

    users_list = get_server_details(server_name)['active_users']
    users_list.append(user_id)

    db.update_one({'_id': get_server_details(server_name)['_id']},
                  {"$set": {'active_users': users_list}})


def set_dead_user(server_name, user_id):

    active_users_list = get_server_details(server_name)['active_users']
    dead_users_list = get_server_details(server_name)['dead_users']

    if user_id in active_users_list:
        active_users_list.remove(user_id)
        db.update_one({'_id': get_server_details(server_name)['_id']},
                      {"$set": {'active_users': active_users_list}})

    dead_users_list.append(user_id)
    db.update_one({'_id': get_server_details(server_name)['_id']},
                  {"$set": {'dead_users': dead_users_list}})
    
    
########################################################################################################################
# Commandants lists

def add_active_commandant(server_name, commandant_id):

    commandants_list = get_server_details(server_name)['active_commandants']
    commandants_list.append(commandant_id)

    db.update_one({'_id': get_server_details(server_name)['_id']},
                  {"$set": {'active_commandants': commandants_list}})


def set_dead_commandant(server_name, commandant_id):

    active_commandants_list = get_server_details(server_name)['active_commandants']
    dead_commandants_list = get_server_details(server_name)['dead_commandants']

    if commandant_id in active_commandants_list:
        active_commandants_list.remove(commandant_id)
        db.update_one({'_id': get_server_details(server_name)['_id']},
                      {"$set": {'active_commandants': active_commandants_list}})

    dead_commandants_list.append(commandant_id)
    db.update_one({'_id': get_server_details(server_name)['_id']},
                  {"$set": {'dead_commandants': dead_commandants_list}})


#create_server('test 2', status='stop', admin_only_visibility=True)
#print(get_server_details('Alpha'))
#db.update_one({"server_name": "Alpha_Boardgame"}, {"$push": {'timezone': 'Europe/Paris'}})