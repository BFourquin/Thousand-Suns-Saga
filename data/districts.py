
from bson.objectid import ObjectId

from database.db_connect import databases
from data import colonies, districts_types, buildings


def get_district(server, id):

    client = databases['TSS_' + server]
    db = client['districts']
    return db.find_one({"_id": ObjectId(id)})


def get_all_districts(server):
    client = databases['TSS_' + server]
    db = client['districts']
    return list(db.find())


def set_district(server, district):

    client = databases['TSS_' + server]
    db = client['districts']

    db.insert_one(district)


def update_district(server, district_id, param, value):
    # Modifies an existing document or documents in a collection

    client = databases['TSS_' + server]
    db = client['districts']
    db.update_one({"_id": ObjectId(district_id)}, {"$set": {param: value}})


def push_param_district(server, district_id, param, value):
    # Appends a specified value to an array

    client = databases['TSS_' + server]
    db = client['districts']
    db.update_one({"_id": ObjectId(district_id)}, {"$push": {param: value}})


def pull_param_district(server, district_id, param, value):
    # Removes from an existing array all instances of a value or values that match a specified condition.

    client = databases['TSS_' + server]
    db = client['districts']
    db.update_one({"_id": ObjectId(district_id)}, {"$pull": {param: value}})


########################################################################################################################


def create_district(server, colony_id, district_type, starting_buildings=None):
    # Return False if the colony has no free slot for it

    client = databases['TSS_' + server]
    db = client['districts']

    district_type_properties = districts_types.get_district_type(server, district_type)
    is_central = district_type_properties['category'] == 'central_district'

    # Central district : they define how many districts slots you have
    if is_central:
        colonies.update_colony(server, colony_id, 'districts_slots_total', district_type_properties['districts_slots'])

    district = {
        'colony_id': ObjectId(colony_id),
        'district_type': district_type,
        'category': district_type_properties['category'],
        'buildings_ids': starting_buildings if starting_buildings else [],
        'buildings_slots_free': district_type_properties['buildings_slots'],
        'buildings_slots_total': district_type_properties['buildings_slots'],
        'population': district_type_properties['build_population'],
        'population_details': None,
        'transports_needs': 0,
        'transports_cars_needs': 0,
        'transports_public_needs': 0,
        'transports_planes_needs': 0,
        'transports_spaceshuttles_needs': 0,
        'power_needs': 0,
        'power_satisfaction': 0,
        'hp': district_type_properties['hp'],
        'hp_max': district_type_properties['hp'],
        'damages': 0,
    }

    district_id = db.insert_one(district).inserted_id

    if is_central:
        colonies.push_param_colony(server, colony_id, 'districts', district_id)
    elif not colonies.add_district_if_slot_free(server, colony_id, district_id):
        db.delete_one({"_id": district_id})
        return False

    colonies.recalculate_districts_slots(server, colony_id)
    return True


def delete_district(server, commandant_id, district_id, refund_ratio=0.75):
    from data.resources import add_resources  # Placed here to prevent circular import

    client = databases['TSS_' + server]
    db = client['districts']

    # Single query : spamming the request can't refund the same district twice
    district = db.find_one_and_delete({"_id": ObjectId(district_id)})
    if not district:
        return False

    # TODO check if destruction is valid

    # Removal of it's references
    colonies.pull_param_colony(server, district['colony_id'], 'districts', ObjectId(district_id))
    colonies.recalculate_districts_slots(server, district['colony_id'])

    # TODO destruction and refund of the district's buildings, once constructing them has a cost

    # District cost refund
    district_type = districts_types.get_district_type(server, district['district_type'])
    add_resources(server, commandant_id,
                  {resource: int(quantity * refund_ratio) for resource, quantity in district_type['build_cost'].items()})
    return True


def recalculate_buildings_slots(server, district_id):
    district = get_district(server, district_id)

    slots_total = districts_types.get_district_type(server, district['district_type'])['districts_slots']
    slots_occupied = len(district['buildings_ids'])


    # TODO take into account future special buildings with different slots size
    """
    for building_id in district['buildings']:
        building = buildings.get_building(server, building_id)

        slots_total += buildings.get_building_type(server, building['building_type'])['buildings_slots']
        if building['category'] != 'central_building':
            slots_occupied += 1  

    update_district(server, district_id, 'buildings_slots_total', slots_total)
    update_district(server, district_id, 'buildings_slots_occupied', slots_occupied)
    """

    # TODO cheat log
    if slots_occupied > slots_total:
        ...
        # cheat_log()

    return slots_total, slots_occupied
