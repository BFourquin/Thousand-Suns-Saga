
from bson.objectid import ObjectId

from database.db_connect import databases
from data import colonies


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
    for district in districts:
        if district['category'] == 'central_district':
            # TODO remove unbuildable districts limited by tech too
            districts.remove(district)

    if language:
        for i in range(len(districts)):
            districts[i]['name'] = districts[i]['name_' + language]

    return districts
