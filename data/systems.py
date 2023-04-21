

from database.db_connect import databases


# ######################################################################################################################
# Now that all systems and sectors ids are simply their seed, no need to keep those duplicates values stored in DB

def info_from_seed(seed):
    sector_id = seed[0:10]
    pos_y = seed[10:13]
    pos_x = seed[13:16]
    return sector_id, pos_y, pos_x


def remove_redundant_info(system):
    # TODO Remove easily calculable data ?
    #for info in ('seed', 'sector_id', 'pos_y', 'pos_x'):
    #    if info in system:
    #        del system[info]
    return system


def recreate_redundant_info(system):
    # TODO Remove easily calculable data ?
    #system['seed'] = system['_id']
    #system['sector_id'], system['pos_y'], system['pos_x'] = info_from_seed(system['seed'])
    return system

# ######################################################################################################################


def get_system_by_seed(server, seed):
    client = databases['TSS_' + server]
    db = client['systems']

    system = db.find_one({"_id": str(seed)})
    system = recreate_redundant_info(system) if system is not None else None
    return system


def get_system_by_position(server, sector_id, y, x):
    client = databases['TSS_' + server]
    db = client['systems']

    system = db.find_one({"sector_id": sector_id, "pos_y": y, "pos_x": x})
    system = recreate_redundant_info(system) if system is not None else None
    return system


def get_systems_in_sector(server, sector_id):
    client = databases['TSS_' + server]
    db = client['systems']

    systems = list(db.find({"sector_id": str(sector_id)}))
    #system = recreate_redundant_info(system) if system is not None else None
    #print(systems)
    return systems


def get_all_systems(server):
    client = databases['TSS_' + server]
    db = client['systems']

    return list(db.find())


def set_system(server, system):

    client = databases['TSS_' + server]
    db = client['systems']

    # Will remove previous entry if one exist
    previous_system = get_system_by_seed(server, system["_id"])
    if previous_system:
        db.delete_one(previous_system)

    system['sector_id'], system['pos_y'], system['pos_x'] = info_from_seed(system['_id'])
    system = remove_redundant_info(system) if system is not None else None
    db.insert_one(system)
