

from database.db_connect import collection


def get_seed_type(seed):
    seed_types_by_length = {
        '4': 'server',
        '10': 'sector',
        '16': 'system',
        '18': 'coordinate'
    }
    if str(len(str(seed))) in seed_types_by_length.keys():
        return seed_types_by_length[str(len(str(seed)))]
    else:
        print(str(seed), seed, seed_types_by_length.keys())
        raise Exception(str(seed) + ' is not a recognized seed length')


def set_map_generator_parameters(server, map_generator_params, mg_type=None):

    db = collection(server, 'mg_' + mg_type if mg_type else 'map_generator')

    db.delete_many({})

    for param in map_generator_params:
        db.insert_one(param)


def get_map_generator_parameters(server, mg_type=None):

    if not mg_type or mg_type == 'global':
        return collection(server, 'map_generator').find_one({})
    return list(collection(server, 'mg_' + mg_type).find({}))


def get_mg_params_sector_type(server, sector_type):

    db = collection(server, 'mg_sectors')
    return db.find_one({'sector_type': sector_type})


def get_mg_system_type(server, system_type):

    db = collection(server, 'mg_systems_types')
    return db.find_one({'system_type': system_type})


def get_mg_system_composition(server, solar_type):

    db = collection(server, 'mg_systems_compositions')
    return db.find_one({'solar_type': solar_type})
