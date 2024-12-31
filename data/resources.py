

from database.db_connect import databases



def get_all_resources_parameters(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources']

    return db.find({})


def get_resources_categories(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources_categories']

    return db.find({})


def get_resources_subcategories(server_name):
    client = databases['TSS_' + server_name]
    db = client['resources_subcategories']

    return db.find({})
