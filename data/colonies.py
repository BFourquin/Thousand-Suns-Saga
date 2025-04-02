
from bson.objectid import ObjectId

from backend import utils
from database.db_connect import databases
from data.districts import create_district, get_district
from data.admin import cheat_log



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



def new_colony(server, commandant_id, colony_name, coordinate, colony_type, central_district_type):

    client = databases['TSS_' + server]
    db = client['colonies']

    new_colony = {
        'name': colony_name,
        'owner': commandant_id,
        'controller': commandant_id,
        'coordinate': coordinate,
        'districts': [],
        'colony_type': colony_type,  # TODO more types
        'districts_slots_occupied': 0,
        'districts_slots_total': 0,
    }

    colony_id = db.insert_one(new_colony).inserted_id
    from data.commandant import push_param_commandant
    push_param_commandant(server, commandant_id, 'colonies', colony_id)

    create_district(server, colony_id, central_district_type, starting_buildings=None)


########################################################################################################################
# DISTRICTS SLOTS


def check_and_occupy_district_slot(server, colony_id):
    colony = get_colony(server, id)

    # TODO take into account future special districts with different slots size

    if colony['districts_slots_occupied'] < colony['districts_slots_total']:
        update_colony(server, colony_id, 'districts_slots_occupied', colony['districts_slots_occupied']+1)
        return True
    else:
        return False


def calculate_districts_slots(server, colony_id):
    colony = get_colony(server, id)

    slots_total = 0
    slots_occupied = 0

    for district_id in colony['districts']:
        district = get_district(server, district_id)

        slots_total += district['districts_slots']
        if district['category'] != 'central_district':
            slots_occupied += 1  # TODO take into account future special districts with different slots size

    if colony['districts_slots_occupied'] > colony['districts_slots_total']:
        ...
        # TODO cheat log
        # cheat_log()