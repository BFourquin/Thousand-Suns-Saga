
from database.db_connect import databases


def get_sector(server, y, x):
    client = databases['TSS_' + server]
    db = client['sectors']
    return db.find_one({"pos_y": y, "pos_x": x})


def get_all_sectors(server):
    client = databases['TSS_' + server]
    db = client['sectors']
    return list(db.find())


def get_sector_by_seed(server, seed):
    client = databases['TSS_' + server]
    db = client['sectors']
    return db.find_one({"_id": str(seed)})


def get_direct_neighbours_sectors(server, y, x):
    neighbours_sectors = [
        get_sector(server, y-1, x),
        get_sector(server, y+1, x),
        get_sector(server, y, x-1),
        get_sector(server, y, x+1)
    ]
    neighbours_sectors = [_ for _ in neighbours_sectors if _]  # Remove none
    return neighbours_sectors


def get_diagonal_neighbours_sectors(server, y, x):
    neighbours_sectors = [
        get_sector(server, y-1, x-1),
        get_sector(server, y-1, x+1),
        get_sector(server, y+1, x-1),
        get_sector(server, y+1, x+1)
    ]
    neighbours_sectors = [_ for _ in neighbours_sectors if _]  # Remove none
    return neighbours_sectors


def set_sector(server, sector):

    client = databases['TSS_' + server]
    db = client['sectors']

    # Will remove previous entry if one exist
    previous_sector = get_sector(server, sector["pos_y"], sector["pos_x"])
    if previous_sector:
        db.delete_one(previous_sector)

    db.insert_one(sector)
