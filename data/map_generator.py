import datetime

from database.db_connect import clients


def set_map_generator_parameters(server, map_generator_params, mg_type=None):

    client = clients['TSS_'+server]

    if not mg_type:
        db = client['map_generator']
    else:
        db = client['mg_' + mg_type]

    db.delete_many({})

    for param in map_generator_params:
        db.insert_one(param)


def get_map_generator_parameters(server, mg_type=None):

    client = clients['TSS_'+server]

    if not mg_type or mg_type == 'global':
        db = client['map_generator']
        return db.find_one({})
    else:
        db = client['mg_' + mg_type]
        return list(db.find({}))


def get_mp_params_sector_type(server, sector_type):

    client = clients['TSS_'+server]
    db = client['mg_sectors']
    return db.find_one({'sector_type': sector_type})
