

from data.commandant import get_commandant_by_object_id, update_commandant
from database.db_connect import databases



def get_all_resources_parameters(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources']

    return db.find({})


def get_resources_categories(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources_categories']

    return db.find({})


def get_resources_subcategories(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources_subcategories']

    return db.find({})


########################################################################################################################


def check_enough_resource(server, commandant_id, resource, quantity):
    commandant = get_commandant_by_object_id(server, commandant_id)

    if resource not in commandant['resources']:
        return False

    return commandant['resources'][resource] >= quantity



def resource_change(server, commandant_id, resource, quantity, allow_negative=False):
    commandant = get_commandant_by_object_id(server, commandant_id)

    if resource not in commandant['resources']:
        return False

    if allow_negative or commandant['resources'][resource] + quantity > 0:
        commandant['resources'][resource] += quantity
        update_commandant(server, commandant_id,
                              'resources.'+resource,
                              commandant['resources'][resource])
        return True
    return False


########################################################################################################################


def give_starting_resources(server_name, commandant_id):

    ...  # TODO
