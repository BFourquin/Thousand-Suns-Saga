
from bson.objectid import ObjectId

from database.db_connect import databases
from data import colonies


def get_district_type_by_id(server, id):

    client = databases['TSS_' + server]
    db = client['districts_types']
    return db.find_one({"_id": ObjectId(id)})


def get_district_type(server, internal_name):

    client = databases['TSS_' + server]
    db = client['districts_types']
    return db.find_one({"internal_name": internal_name})


def get_all_districts_types(server):
    client = databases['TSS_' + server]
    db = client['districts_types']
    return list(db.find())

