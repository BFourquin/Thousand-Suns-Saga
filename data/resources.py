from data.names import localized_name

from django.db import transaction

from game.models import Commandant, Resource, ResourceCategory, ResourceSubcategory
from database.schemas import on_server
from data.commandant import get_commandant



@on_server
def get_all_resources_parameters(server_name):
    return [resource.as_dict() for resource in Resource.objects.all().order_by('id')]


@on_server
def get_resource_parameters(server_name, resource_name):
    resource = Resource.objects.filter(internal_name=resource_name).first()
    return resource.as_dict() if resource else None


@on_server
def add_infos_to_resources_dict(server_name, resources_dict, commandant=None, language=None):
    # Add necessary interface info (like name and illustrations) from a simple {resource: quantity} dict
    # Return : { resource : {quantity:int, name:str, enough_stockpiles:bool, illustration:str} }

    for res_internal_name, quantity in resources_dict.items():
        resource_declaration = get_resource_parameters(server_name, res_internal_name)
        resources_dict[res_internal_name] = {
            'internal_name': res_internal_name,
            'name': localized_name(resource_declaration, language or 'en'),
            'quantity': quantity,
            'commandant_storage': commandant['resources'][res_internal_name] if commandant and res_internal_name in commandant['resources'] else 0,
            'enough_stockpiles': commandant and res_internal_name in commandant['resources'] and commandant['resources'][res_internal_name] >= quantity,
            'illustration': resource_declaration['icon'],
            'unit_notation': resource_declaration['unit_notation'],
        }
    return resources_dict


########################################################################################################################
# RESOURCES CATEGORIES AND SUB-CATEGORIES


@on_server
def get_resources_categories(server_name):
    return [category.as_dict() for category in ResourceCategory.objects.all().order_by('id')]


@on_server
def get_resources_subcategories(server_name):
    return [category.as_dict() for category in ResourceSubcategory.objects.all().order_by('id')]


########################################################################################################################


@on_server
def check_enough_resource(server, commandant_id, resource, quantity):
    commandant = get_commandant(server, commandant_id)

    if resource not in commandant['resources']:
        return False
    return commandant['resources'][resource] >= quantity


@on_server
def check_enough_resources_dict(server, commandant_id, resources_dict, return_missing_details=False):
    commandant = get_commandant(server, commandant_id)

    enough_resources = True
    missing_resources = {}

    for resource, quantity in resources_dict.items():
        if resource not in commandant['resources'] or commandant['resources'][resource] < quantity:
            enough_resources = False
            missing_resources[resource] = quantity - commandant['resources'][resource] if resource in commandant['resources'] else quantity
    return (enough_resources, missing_resources) if return_missing_details else enough_resources


########################################################################################################################


@on_server
@transaction.atomic
def pay_resources(server, commandant_id, cost):
    # The commandant is locked between the check and the debit : two simultaneous orders can't spend the same stock

    cost = {resource: quantity for resource, quantity in cost.items() if quantity > 0}
    if not cost:
        return True

    commandant = Commandant.objects.select_for_update().filter(id=commandant_id).first()
    if not commandant or any(commandant.resources.get(resource, 0) < quantity for resource, quantity in cost.items()):
        return False

    for resource, quantity in cost.items():
        commandant.resources[resource] -= quantity
    commandant.save(update_fields=['resources'])
    return True


@on_server
@transaction.atomic
def add_resources(server, commandant_id, gains):
    if gains:
        commandant = Commandant.objects.select_for_update().get(id=commandant_id)
        for resource, quantity in gains.items():
            commandant.resources[resource] = commandant.resources.get(resource, 0) + quantity
        commandant.save(update_fields=['resources'])


########################################################################################################################


@on_server
def give_starting_resources(server_name, commandant_id):

    ...  # TODO
