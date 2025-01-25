
from database.db_connect import databases
from data.districts import create_district


def get_colony(server, id):
    client = databases['TSS_' + server]
    db = client['colonies']
    return db.find_one({"_id": id})


def get_colonies_controlled_by_commandant(server, commandant_id):
    client = databases['TSS_' + server]
    db = client['colonies']
    return list(db.find({"controller": commandant_id}))


def get_all_colonies(server):
    client = databases['TSS_' + server]
    db = client['colonies']
    return list(db.find())



def update_colony(server, colony_id, param, value):
    # Modifies an existing document or documents in a collection

    client = databases['TSS_' + server]
    db = client['colonies']
    db.update_one({"_id": colony_id}, {"$set": {param: value}})


def push_param_colony(server, colony_id, param, value):
    # Appends a specified value to an array

    client = databases['TSS_' + server]
    db = client['colonies']
    db.update_one({"_id": colony_id}, {"$push": {param: value}})


def pull_param_colony(server, colony_id, param, value):
    # Removes from an existing array all instances of a value or values that match a specified condition.

    client = databases['TSS_' + server]
    db = client['colonies']
    db.update_one({"_id": colony_id}, {"$pull": {param: value}})



def new_colony(server, commandant_id, colony_name, coordinate, colony_type, districts=None):

    client = databases['TSS_' + server]
    db = client['colonies']

    new_colony = {
        'name': colony_name,
        'owner': commandant_id,
        'controller': commandant_id,
        'coordinate': coordinate,
        'districts': [],
        'colony_type': colony_type,  # TODO more types
    }

    # TODO add districts and buildings according to colony type, planet biome and colonizing ship modules
    district_type = 'world_capital'

    colony_id = db.insert_one(new_colony).inserted_id

    create_district(server, colony_id, district_type, starting_buildings=None)



