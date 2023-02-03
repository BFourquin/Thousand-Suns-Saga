
import sys
import pymongo

from django_tss.settings import DATABASES

clients = {}
databases = {}


def db_connect(db_settings):
    client = pymongo.MongoClient('mongodb://' + db_settings['HOST'] + ':' + str(db_settings['PORT']) + '/')
    db = client[db_settings['NAME']]

    try:
        client.server_info()
    except pymongo.errors.ServerSelectionTimeoutError as e:
        #message(CRITICAL, "Unable to connect to the database at address " + DATABASE_ADDRESS)
        print("Unable to connect to the database " + db_settings['NAME'])
        client = None
        sys.exit()
    return client, db


for db_settings in DATABASES.values():
    clients[db_settings['NAME']], databases[db_settings['NAME']] = db_connect(db_settings)
