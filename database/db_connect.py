
import pymongo
from bson.objectid import ObjectId

from django_tss.settings import DATABASES

clients = {}
databases = {}


def db_connect(db_settings):
    # MongoClient only reaches the server on the first query : importing this module neither blocks nor stops the process
    client = pymongo.MongoClient('mongodb://' + db_settings['HOST'] + ':' + str(db_settings['PORT']) + '/',
                                 serverSelectionTimeoutMS=5000)
    return client, client[db_settings['NAME']]


for db_settings in DATABASES.values():
    clients[db_settings['NAME']], databases[db_settings['NAME']] = db_connect(db_settings)


def collection(server, name):
    return databases['TSS_' + server][name]


def update_field(server, name, _id, param, value):
    # Modifies an existing document in a collection
    collection(server, name).update_one({"_id": ObjectId(_id)}, {"$set": {param: value}})


def push_field(server, name, _id, param, value):
    # Appends a specified value to an array
    collection(server, name).update_one({"_id": ObjectId(_id)}, {"$push": {param: value}})


def pull_field(server, name, _id, param, value):
    # Removes from an existing array all instances of a value
    collection(server, name).update_one({"_id": ObjectId(_id)}, {"$pull": {param: value}})


class PaginatedCollection:
    # Lets Django's Paginator query only the displayed page of a collection

    def __init__(self, server, name):
        self.db = collection(server, name)

    def count(self):
        return self.db.count_documents({})

    def __getitem__(self, page):
        return list(self.db.find().sort('_id', 1).skip(page.start).limit(page.stop - page.start))
