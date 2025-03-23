
from bson.objectid import ObjectId

from database.db_connect import databases
from data import colonies, districts_types


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


########################################################################################################################


def create_district(server, colony_id, district_type, starting_buildings=None):

    client = databases['TSS_' + server]
    db = client['districts']

    district_type_properties = districts_types.get_district_type(server, district_type)

    # Check if slot available for a new district
    if district_type_properties['category'] != 'central_district':
        slot_available = colonies.check_and_occupy_district_slot(server, colony_id)
        if not slot_available:
            ...  # TODO error message no district slot available
    # Central district : they define how many districts slots you have
    else:
        colonies.update_colony(server, colony_id, 'districts_slots_total', district_type_properties['districts_slots'])



    district = {
        'colony_id': colony_id,
        'district_type': district_type,
        'category': district_type_properties['category'],
        'buildings': starting_buildings if starting_buildings else [],
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
    colonies.push_param_colony(server, colony_id, 'districts', district_id)



