

from database.db_connect import clients


# ######################################################################################################################
# Now that all systems and sectors ids are simply their seed, no need to keep those duplicates values stored in DB

def info_from_seed(seed):
    sector_id = seed[0:12]
    pos_y = seed[12:15]
    pos_x = seed[15:18]
    return sector_id, pos_y, pos_x


def remove_redundant_info(system):
    for info in ('seed', 'sector_id', 'pos_y', 'pos_x'):
        if info in system:
            del system[info]
    return system


def recreate_redundant_info(system):
    system['seed'] = system['_id']
    system['sector_id'], system['pos_y'], system['pos_x'] = info_from_seed(system['seed'])
    return system

# ######################################################################################################################


def get_system_by_seed(server, seed):
    client = clients['TSS_' + server]
    db = client['systems']

    system = db.find_one({"_id": seed})
    system = recreate_redundant_info(system) if system is not None else None
    return system


def get_system_by_position(server, sector_id, y, x):
    client = clients['TSS_' + server]
    db = client['systems']

    system = db.find_one({"sector_id": sector_id, "pos_y": y, "pos_x": x})
    system = recreate_redundant_info(system) if system is not None else None
    return system


def get_all_systems(server):
    client = clients['TSS_' + server]
    db = client['systems']

    system = list(db.find())
    return system


def set_system(server, system):

    client = clients['TSS_'+server]
    db = client['systems']

    # Will remove previous entry if one exist
    previous_system = get_system_by_seed(server, system["_id"])
    if previous_system:
        db.delete_one(previous_system)

    system = remove_redundant_info(system) if system is not None else None
    db.insert_one(system)
