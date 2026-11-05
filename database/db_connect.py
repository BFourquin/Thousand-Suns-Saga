
import pymongo

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
