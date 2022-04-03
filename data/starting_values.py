
from database.db_connect import clients


def create_starting_values(user, server, pseudo):

    client = clients['TSS_'+server]
    db = client['starting_values']

    # Remove previous values
    db.delete_many({})

    starting_values = {
        'starting_planets': {},
        'starting_resources': {},
        'starting_capital': {},
        'starting_territories': {},
        'starting_modifiers': {},
        'starting_factions': {},
        'starting_technologies': {},
    }

    db.insert_one(starting_values)


#create_starting_values(None, 'Alpha', None)


def get_starting_values(server):
    client = clients['TSS_' + server]
    db = client['starting_values']
    return db.find_one()
