
from database.db_connect import databases


def create_starting_values(server):

    client = databases['TSS_' + server]
    db = client['starting_values']

    # Remove previous values
    db.delete_many({})

    starting_values = {
        'available_native_planets': [],
        'starting_resources': {},
        'starting_capital': {},
        'starting_territories': {},
        'starting_modifiers': {},
        'starting_factions': {},
        'starting_technologies': {},
    }

    db.insert_one(starting_values)



def get_starting_values(server):
    client = databases['TSS_' + server]
    db = client['starting_values']
    return db.find_one()

#create_starting_values(None, 'Alpha', None)


# #### AVAILABLE NATIVE PLANETS #### #


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

