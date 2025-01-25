
from database.db_connect import databases
from data import colonies


def get_district(server, id):

    client = databases['TSS_' + server]
    db = client['districts']
    return db.find_one({"_id": id})


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

    district = {
        'colony_id': colony_id,
        'district_type': district_type,
        'buildings': starting_buildings if starting_buildings else [],
        'population_total': 1000000,
        'population_details': None,
        'transports_needs': 0,
        'transports_cars_needs': 0,
        'transports_public_needs': 0,
        'transports_planes_needs': 0,
        'transports_spaceshuttles_needs': 0,
        'power_needs': 0,
        'power_satisfaction': 0,
        'hp': 100,
        'hp_max': 100,
        'damages': 0,
    }

    district_id = db.insert_one(district).inserted_id
    colonies.push_param_colony(server, colony_id, 'districts', district_id)



