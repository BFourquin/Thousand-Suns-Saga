
from bson.objectid import ObjectId

from backend import utils
from database.db_connect import databases
from data.districts import create_district


def additional_colony_info(colony, add_coo_image):
    # Add id, geographic_location and images

    colony['id'] = colony['_id']
    colony['geographic_location'] = utils.info_from_seed(colony['coordinate'])
    if add_coo_image:
        colony['coordinate_image'] = 'images/placeholder/telluric.png'  # TODO get image from planet table

    return colony


def get_colony(server, id, add_coo_image=False):
    client = databases['TSS_' + server]
    db = client['colonies']

    colony = db.find_one({"_id": ObjectId(id)})
    colony = additional_colony_info(colony, add_coo_image)

    return colony


def get_colonies_controlled_by_commandant(server, commandant_id, add_coo_image=False):
    client = databases['TSS_' + server]
    db = client['colonies']

    colonies = list(db.find({"controller": commandant_id}))
    for i in range(len(colonies)):
        colonies[i] = additional_colony_info(colonies[i], add_coo_image)

    return colonies


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



def new_colony(server, commandant_id, colony_name, coordinate, colony_type, colony_size, districts=None):

    client = databases['TSS_' + server]
    db = client['colonies']

    new_colony = {
        'name': colony_name,
        'owner': commandant_id,
        'controller': commandant_id,
        'coordinate': coordinate,
        'districts': [],
        'colony_type': colony_type,  # TODO more types
        'colony_size': colony_size,
    }

    # TODO add districts and buildings according to colony type, planet biome and colonizing ship modules
    district_type = 'world_capital'

    colony_id = db.insert_one(new_colony).inserted_id

    create_district(server, colony_id, district_type, starting_buildings=None)



