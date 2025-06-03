
import datetime
from random import randint
from bson.objectid import ObjectId

from database.db_connect import databases
from data import server_details
from data.server_details import get_server_details
from data.commandant import get_commandant_by_object_id


def create_cycle_entry(server_name, last_cycle=None):

    client = databases['TSS_' + server_name]
    db = client['cycles']

    server = get_server_details(server_name)
    commandants_list = server['active_commandants']

    cycle = {
        'cycle_nb': last_cycle['cycle_nb']+1 if last_cycle else 1,
        'datetime_start' : datetime.datetime.now(),
        'datetime_end' : None,

        # Long-term version : daily passing of cycles
        'datetime_planned_end': None,  # TODO planned time for next cycle

        # Boardgame version : manual passing of cycles
        'commandants_cycle_playing': [],
        'commandants_cycle_finished': [],
        'commandants_cycle_absent': last_cycle['players_absent'] if last_cycle else [],
    }

    # Boardgame version : manual passing of cycles
    for commandant_id in commandants_list:
        if last_cycle and commandant_id in last_cycle['commandants_cycle_absent']:
            cycle['commandants_cycle_absent'].append(commandant_id)
            cycle['commandants_cycle_finished'].append(commandant_id)
        else:
            cycle['commandants_cycle_playing'].append(commandant_id)

    db.insert_one(cycle)


def get_current_cycle(server_name):

    client = databases['TSS_' + server_name]
    db = client['cycles']

    return db.find_one({}, sort=[('cycle_nb', -1)])


def update_cycle(server, param, value):
    # Modifies an existing document or documents in a collection

    client = databases['TSS_' + server]
    db = client['cycles']

    cycle_id = get_current_cycle(server)['_id']
    db.update_one({"_id": cycle_id}, {"$set": {param: value}})


def push_param_cycle(server, param, value):
    # Appends a specified value to an array

    client = databases['TSS_' + server]
    db = client['cycles']

    cycle_id = get_current_cycle(server)['_id']
    db.update_one({"_id": cycle_id}, {"$push": {param: value}})


def pull_param_cycle(server, param, value):
    # Removes from an existing array all instances of a value or values that match a specified condition.

    client = databases['TSS_' + server]
    db = client['cycles']

    cycle_id = get_current_cycle(server)['_id']
    db.update_one({"_id": cycle_id}, {"$pull": {param: value}})


########################################################################################################################
# Boardgame version : manual passing of cycles

def mark_commandant_cycle_finished(server, commandant_id):
    pull_param_cycle(server, 'commandants_cycle_playing', commandant_id)
    push_param_cycle(server, 'commandants_cycle_finished', commandant_id)

def mark_commandant_cycle_playing(server, commandant_id):
    pull_param_cycle(server, 'commandants_cycle_finished', commandant_id)
    push_param_cycle(server, 'commandants_cycle_playing', commandant_id)

# Player declared absent : always display as cycle finished

def mark_commandant_cycle_absent(server, commandant_id):
    pull_param_cycle(server, 'commandants_cycle_playing', commandant_id)
    push_param_cycle(server, 'commandants_cycle_finished', commandant_id)
    push_param_cycle(server, 'commandants_cycle_absent', commandant_id)

def mark_commandant_cycle_present(server, commandant_id):
    pull_param_cycle(server, 'commandants_cycle_finished', commandant_id)
    pull_param_cycle(server, 'commandants_cycle_absent', commandant_id)
    push_param_cycle(server, 'commandants_cycle_playing', commandant_id)


########################################################################################################################


def end_cycle(server_name):

    server = server_details.get_server_details(server_name)



if __name__ == '__main__':
    # create_cycle_entry('Alpha_Boardgame')
    mark_commandant_cycle_finished('Alpha_Boardgame', ObjectId('682a50b4be58ce0e09fdab34'))


