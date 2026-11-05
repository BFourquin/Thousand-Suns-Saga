
from django.db import transaction

from backend.models import Resource, StartingValues


def create_starting_values(server, start_type='default_land_colony', remove_previous=False):

    # Remove previous values
    if remove_previous:
        StartingValues.objects.filter(server=server).delete()

    StartingValues.objects.create(server_id=server, start_type=start_type,
                                  starting_resources=starting_values_ressources(server, start_type='default_land_colony'))


def get_starting_values(server, start_type='default_land_colony', lock=False):
    rows = StartingValues.objects.select_for_update() if lock else StartingValues.objects
    starting_values = rows.filter(server=server, start_type=start_type).first()
    return starting_values.as_dict() if starting_values else None


########################################################################################################################
# #### AVAILABLE NATIVE PLANETS ########################################################################################


def get_available_native_planets(server):
    return StartingValues.objects.filter(server=server).first().available_native_planets


@transaction.atomic
def add_available_native_planets(server, planet_seed):
    starting_values = StartingValues.objects.select_for_update().filter(server=server).first()
    starting_values.available_native_planets.append(planet_seed)
    starting_values.save(update_fields=['available_native_planets'])


@transaction.atomic
def remove_available_native_planets(server, planet_seed):
    starting_values = StartingValues.objects.select_for_update().filter(server=server).first()
    starting_values.available_native_planets = [seed for seed in starting_values.available_native_planets if seed != planet_seed]
    starting_values.save(update_fields=['available_native_planets'])


########################################################################################################################
# #### STARTING RESOURCES ##############################################################################################

def starting_values_ressources(server, start_type='default_land_colony'):

    starting_resources = {}

    for resource in Resource.objects.filter(server=server):
        resource = resource.as_dict()
        if resource['available_from_start'] in ('True', 'true'):
            resource_name = resource['internal_name']
            quantity = resource['start_quantity'] if resource['start_quantity'] else 0
            starting_resources[resource_name] = quantity

    return starting_resources
