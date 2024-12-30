

from database.db_connect import databases



def get_all_resources_parameters(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources']

    return db.find({})
