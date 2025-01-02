
from database.db_connect import databases


def create_starting_values(server, start_type='default_land_colony', remove_previous=False):

    client = databases['TSS_' + server]
    db = client['starting_values']

    # Remove previous values
    if remove_previous:
        db.delete_many({})

    starting_values = {
        'start_type': start_type,
        'available_native_planets': [],
        'starting_resources': starting_values_ressources(server, start_type='default_land_colony'),
        'starting_capital': {},
        'starting_territories': {},
        'starting_ressources': {},
        'starting_modifiers': {},
        'starting_factions': {},
        'starting_technologies': {},
    }

    db.insert_one(starting_values)



def get_starting_values(server, start_type='default_land_colony'):
    client = databases['TSS_' + server]
    db = client['starting_values']
    return db.find_one({'start_type': start_type})


########################################################################################################################
# #### AVAILABLE NATIVE PLANETS ########################################################################################


def get_available_native_planets(server):
    client = databases['TSS_' + server]
    db = client['starting_values']
    available_native_planets = db.find_one()
    if available_native_planets:
        return available_native_planets['available_native_planets']


def add_available_native_planets(server, planet_seed):
    client = databases['TSS_' + server]
    db = client['starting_values']
    planets_list = get_available_native_planets(server)
    if not planets_list:
        planets_list = []
    planets_list.append(planet_seed)
    db.update_one({}, {"$set": {'available_native_planets': planets_list}})


def remove_available_native_planets(server, planet_seed):
    client = databases['TSS_' + server]
    db = client['starting_values']
    planets_list = db.find_one()['available_native_planets']
    planets_list.remove(planet_seed)
    db.update_one({}, {"$set": {'planets_list': planets_list}})


########################################################################################################################
# #### STARTING RESOURCES ##############################################################################################

def starting_values_ressources(server, start_type='default_land_colony'):
    client = databases['TSS_' + server]
    resources = client['resources'].find({})

    starting_resources = {}

    for resource in resources:
        if resource['available_from_start'] in ('True', 'true'):
            resource_name = resource['internal_name']
            quantity = resource['start_quantity'] if resource['start_quantity'] else 0
            starting_resources[resource_name] = quantity

    return starting_resources


########################################################################################################################

if __name__ == '__main__':
    create_starting_values('Alpha_test', remove_previous=True)
