
from bson.objectid import ObjectId

from backend import utils
from database.db_connect import collection, update_field, push_field, pull_field
from data.districts import create_district, get_district
from data.districts_types import get_district_type
from data.admin import cheat_log



def additional_colony_info(colony, add_coo_image):
    # Add id, geographic_location and images

    colony['id'] = colony['_id']
    colony['geographic_location'] = utils.info_from_seed(colony['coordinate'])
    if add_coo_image:
        colony['coordinate_image'] = 'images/placeholder/telluric.png'  # TODO get image from planet table

    return colony


def get_colony(server, id, add_coo_image=False):
    db = collection(server, 'colonies')

    colony = db.find_one({"_id": ObjectId(id)})
    colony = additional_colony_info(colony, add_coo_image)

    return colony


def get_colonies_controlled_by_commandant(server, commandant_id, add_coo_image=False):
    db = collection(server, 'colonies')

    colonies = list(db.find({"controller": commandant_id}))
    for i in range(len(colonies)):
        colonies[i] = additional_colony_info(colonies[i], add_coo_image)

    return colonies


def get_colonies_at_coordinates(server, coordinates_ids):
    # Colonies store their coordinate as an int, coordinates their id as a str
    db = collection(server, 'colonies')
    return list(db.find({"coordinate": {"$in": [int(coordinate_id) for coordinate_id in coordinates_ids]}}))


def get_all_colonies(server):
    db = collection(server, 'colonies')
    return list(db.find())



def update_colony(server, colony_id, param, value):
    update_field(server, 'colonies', colony_id, param, value)


def push_param_colony(server, colony_id, param, value):
    push_field(server, 'colonies', colony_id, param, value)


def pull_param_colony(server, colony_id, param, value):
    pull_field(server, 'colonies', colony_id, param, value)


def new_colony(server, commandant_id, colony_name, coordinate, colony_type, central_district_type):

    db = collection(server, 'colonies')

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


def add_district_if_slot_free(server, colony_id, district_id):
    # Check and add in a single query : two simultaneous builds can't take the same slot
    # The central district doesn't use a slot, hence the + 1
    # TODO take into account future special districts with different slots size

    db = collection(server, 'colonies')

    result = db.update_one({"_id": ObjectId(colony_id),
                            "$expr": {"$lt": [{"$size": "$districts"}, {"$add": ["$districts_slots_total", 1]}]}},
                           {"$push": {"districts": ObjectId(district_id)}})
    return result.modified_count == 1


def recalculate_districts_slots(server, colony_id):
    colony = get_colony(server, colony_id)

    slots_total = 0
    slots_occupied = 0

    for district_id in colony['districts']:
        district = get_district(server, district_id)

        slots_total += get_district_type(server, district['district_type'])['districts_slots']
        if district['category'] != 'central_district':
            slots_occupied += 1  # TODO take into account future special districts with different slots size

    update_colony(server, colony_id, 'districts_slots_total', slots_total)
    update_colony(server, colony_id, 'districts_slots_occupied', slots_occupied)

    if colony['districts_slots_occupied'] > colony['districts_slots_total']:
        ...
        # TODO cheat log
        # cheat_log()

    return slots_total, slots_occupied
