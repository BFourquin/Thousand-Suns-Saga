
import datetime

from database.db_connect import clients

client = clients['TSS_main_server']
db = client['server_details']


# SERVER STATUS :
server_status = ('open',  # users can create an account and play
                 'close',  # users can play but not create new accounts
                 'test',  # only superuser can create an account
                 'stop',  # the server is fixed in time at the end of the game, no new account or any order,
                 'dead')  # everything shut down


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
    return db.find({})


def create_server(server_name, status='test', admin_only_visibility=True):

    if get_server_details(server_name):
        raise Exception("'" + server_name + "' already exist.")
    if status not in server_status:
        raise Exception("'" + status + "' is not valid as a server state.")

    server_details = {'server_name': server_name,
                      'status': status,
                      'admin_only_visibility': admin_only_visibility,
                      'creation_date': datetime.datetime.today(),
                      'opening_date': datetime.datetime.now(),
                      'end_date': None,
                      'active_commandants': [],
                      'previous_commandants': [],
                      'allow_multiaccounts': False,
                      }

    return db.insert_one(server_details)


def change_server_param(server_name, param, param_value):
    db.update_one({'_id': get_server_details(server_name)['_id']},
                  {"$set": { param: param_value }})


#create_server('test 2', status='stop', admin_only_visibility=True)
#print(get_server_details('Alpha'))