

from data.commandant import get_commandant_by_object_id, update_commandant
from database.db_connect import databases



def get_all_resources_parameters(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources']

    return db.find({})


def get_resource_parameters(server_name, resource_name):
    client = databases['TSS_' + server_name]
    db = client['resources']

    return db.find_one({'internal_name': resource_name})


def add_infos_to_resources_dict(server_name, resources_dict, language=None, commandant=None):
    # Add necessary interface info (like name and illustrations) from a simple {resource: quantity} dict
    # Return : { resource : {quantity:int, name:str, enough_stockpiles:bool, illustration:str} }

    for res_internal_name, quantity in resources_dict.items():
        resource_declaration = get_resource_parameters(server_name, res_internal_name)
        resources_dict[res_internal_name] = {
            'internal_name': res_internal_name,
            'name': resource_declaration['name_' + language] if language else resource_declaration['name_en'],
            'quantity': quantity,
            'commandant_storage': commandant['resources'][res_internal_name] if commandant and res_internal_name in commandant['resources'] else 0,
            'enough_stockpiles': commandant and res_internal_name in commandant['resources'] and commandant['resources'][res_internal_name] >= quantity,
            'illustration': resource_declaration['icon'],
            'unit_notation': resource_declaration['unit_notation'],
        }
    return resources_dict


########################################################################################################################
# RESOURCES CATEGORIES AND SUB-CATEGORIES


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
