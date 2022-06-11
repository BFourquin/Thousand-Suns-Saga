
from database.db_connect import clients


def get_sector(server, y, x):

    client = clients['TSS_'+server]
    db = client['sectors']

    """
    # DB BENCHMARK BETWEEN XY and SEED RESEARCH

    from datetime import datetime
    from backend.utils import seed_convertor
    from data import map_generator
    
    timer_1 = datetime.now()
    db.find_one({"pos_y": y, "pos_x": x})
    timer_1 = datetime.now() - timer_1

    seed = seed_convertor((map_generator.get_map_generator_parameters(server, mg_type='global')['seed'], 6), (y, 3), (x, 3))
    timer_2 = datetime.now()
    db.find_one({"_id": seed})
    timer_2 = datetime.now() - timer_2

    #print('YX:', timer_1, '||| ID:', timer_2, '||| Diff:', timer_1 - timer_2)
    """

    return db.find_one({"pos_y": y, "pos_x": x})


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

    client = clients['TSS_'+server]
    db = client['sectors']

    # Will remove previous entry if one exist
    previous_sector = get_sector(server, sector["pos_y"], sector["pos_x"])
    if previous_sector:
        db.delete_one(previous_sector)

    db.insert_one(sector)
