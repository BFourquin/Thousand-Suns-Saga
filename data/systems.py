

from database.db_connect import clients


# ######################################################################################################################
# Now that all systems and sectors ids are simply their seed, no need to keep those duplicates values stored in DB

def remove_redundant_info(system):
    del system['seed']
    del system['sector_id']
    return system


def recreate_redundant_info(system):
    print(system)
    system['seed'] = system['_id']
    system['sector_id'] = system['seed'][0:12]
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


def set_system(server, system):

    client = clients['TSS_'+server]
    db = client['systems']

    # Will remove previous entry if one exist
    previous_system = get_system_by_position(server, system["sector_id"], system["pos_y"], system["pos_x"])
    if previous_system:
        db.delete_one(previous_system)

    system = remove_redundant_info(system) if system is not None else None
    db.insert_one(system)
