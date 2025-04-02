
from bson.objectid import ObjectId

from database.db_connect import databases


def get_district_type_by_id(server, id, language=None):

    client = databases['TSS_' + server]
    db = client['districts_types']
    district = db.find_one({"_id": ObjectId(id)})

    if language:
        district['name'] = district['name_'+language]
    return district


def get_district_type(server, internal_name, language=None):

    client = databases['TSS_' + server]
    db = client['districts_types']
    district = db.find_one({"internal_name": internal_name})

    if language:
        district['name'] = district['name_' + language]
    return district


def get_all_districts_types(server, language=None):
    client = databases['TSS_' + server]
    db = client['districts_types']
    districts = list(db.find())

    if language:
        for i in range(len(districts)):
            districts[i]['name'] = districts[i]['name_' + language]
    return districts


def get_all_buildable_districts_types(server, commandant, language=None):

    client = databases['TSS_' + server]
    db = client['districts_types']
    districts = list(db.find())

    # Remove unconstructibles districts
    for district in districts[:]:  # Duplicate districts list to iterate correctly while removing entries
        if district['category'] == 'central_district':  # Central district are not buildable, only upgradable
            # TODO remove unbuildable districts limited by tech too
            districts.remove(district)

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict
    for i in range(len(districts)):
        districts[i]['build_cost'] = add_infos_to_resources_dict(server, districts[i]['build_cost'], commandant, language)
        districts[i]['maintenance'] = add_infos_to_resources_dict(server, districts[i]['maintenance'], commandant, language)

        # Check if any resource is missing to build it
        districts[i]['enough_stockpiles'] = True
        for resource_dict in districts[i]['build_cost'].values():
            if not resource_dict['enough_stockpiles']:
                districts[i]['enough_stockpiles'] = False
                break

    if language:
        for i in range(len(districts)):
            districts[i]['name'] = districts[i]['name_' + language]

    return districts
