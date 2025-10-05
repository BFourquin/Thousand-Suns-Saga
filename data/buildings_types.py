
from bson.objectid import ObjectId

from database.db_connect import databases


def get_building_type_by_id(server, id, language=None):

    client = databases['TSS_' + server]
    db = client['buildings_types']
    building = db.find_one({"_id": ObjectId(id)})

    if language:
        building['name'] = building['name_'+language]
    return building


def get_building_type(server, internal_name, language=None):

    client = databases['TSS_' + server]
    db = client['buildings_types']
    building = db.find_one({"internal_name": internal_name})

    if language:
        building['name'] = building['name_' + language]
    return building


def get_all_buildings_types(server, language=None):
    client = databases['TSS_' + server]
    db = client['buildings_types']
    buildings = list(db.find())

    if language:
        for i in range(len(buildings)):
            buildings[i]['name'] = buildings[i]['name_' + language]
    return buildings


def get_all_buildable_buildings_types(server, commandant, language=None):
    # TODO /!\ copier coller des districts à vérifier !!!

    client = databases['TSS_' + server]
    db = client['buildings_types']
    buildings = list(db.find())

    # Remove unconstructibles buildings
    for building in buildings[:]:  # Duplicate buildings list to iterate correctly while removing entries
        if building['category'] == 'central_building':  # Central building are not buildable, only upgradable
            # TODO remove unbuildable buildings limited by tech too
            buildings.remove(building)

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict
    for i in range(len(buildings)):
        buildings[i]['build_cost'] = add_infos_to_resources_dict(server, buildings[i]['build_cost'], commandant, language)
        buildings[i]['maintenance'] = add_infos_to_resources_dict(server, buildings[i]['maintenance'], commandant, language)

        # Check if any resource is missing to build it
        buildings[i]['enough_stockpiles'] = True
        for resource_dict in buildings[i]['build_cost'].values():
            if not resource_dict['enough_stockpiles']:
                buildings[i]['enough_stockpiles'] = False
                break

    if language:
        for i in range(len(buildings)):
            buildings[i]['name'] = buildings[i]['name_' + language]

    return buildings
