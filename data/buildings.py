
from bson.objectid import ObjectId

from database.db_connect import databases
from data import colonies, buildings_types, districts


def get_building(server, id):

    client = databases['TSS_' + server]
    db = client['buildings']
    return db.find_one({"_id": ObjectId(id)})


def get_all_buildings(server):
    client = databases['TSS_' + server]
    db = client['buildings']
    return list(db.find())


def set_building(server, building):

    client = databases['TSS_' + server]
    db = client['buildings']

    db.insert_one(building)


########################################################################################################################


def construct_building(server, district_id, building_type):

    client = databases['TSS_' + server]
    db = client['buildings']

    home_district = districts.get_district(server, district_id)
    building_type_properties = buildings_types.get_building_type(server, building_type)
    print(building_type_properties)

    # Check if slot available for a new building
    if home_district['buildings_slots_free'] < 1:
        return False
    # Resources
    # TODO

    building = {
        'name_fr': building_type_properties['name_fr'],
        'name_en': building_type_properties['name_en'],
        'building_type': building_type,
        'home_district': ObjectId(district_id),
        'local_modifiers': [],
        'player_modifiers': [],
        'faction_modifiers': [],
        'activation_percent': 100,
        'last_cycle_missing_resources': {},
        'last_cycle_production': 0,
        'last_cycle_productivity_percent': 0,
    }

    building_id = db.insert_one(building).inserted_id
    districts.push_param_district(server, district_id, 'buildings_ids', ObjectId(building_id))  # Add to district's list of buildings
    districts.recalculate_buildings_slots(server, district_id)


def delete_building(server, building_id, refund_ratio=0.75):

    client = databases['TSS_' + server]
    db = client['buildings']

    building = db.find_one({"_id": ObjectId(building_id)})
    if not building:
        return False


    # TODO check if destruction is valid

    # Removal of the entry and it's references
    districts.pull_param_district(server, building['home_district'], 'buildings_ids', ObjectId(building_id))
    db.delete_one({"_id": ObjectId(building_id)})


    # RESOURCES REFUNDING (done after to prevent multiple refunding by spamming faster than DB deletion)
    resources_refund = {}

    # Building cost refund
    building_type = buildings_types.get_building_type(server, building['building_type'])
    for resource, quantity in building_type['build_cost']:
        if resource in resources_refund:
            resources_refund[resource] += quantity * refund_ratio
        else:
            resources_refund[resource] = quantity * refund_ratio
            # TODO refund on destruction



if __name__ == "__main__":
    ...
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "farm_modern_agriculture")
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "water_pumping_station")
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "survival_industry")
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "survival_factory")
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "goods_factory")
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "pharmaceutical_factory")
    construct_building("Alpha_Boardgame", "688547b1529e0f1b4c48fb25", "machine_tool_workshop")
    builds = get_all_buildings("Alpha_Boardgame")
    print(builds)
    #for build in builds:
    #    print(">>", build)
    #    delete_building("Alpha_Boardgame", build['_id'], refund_ratio=0)
