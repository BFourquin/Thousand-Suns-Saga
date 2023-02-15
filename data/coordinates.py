
from database.db_connect import databases


def get_coordinate(server, seed):

    client = databases['TSS_' + server]
    db = client['coordinates']
    return db.find_one({"_id": seed})


def get_all_coordinates(server):
    client = databases['TSS_' + server]
    db = client['sectors']
    return list(db.find())


def set_coordinate(server, coordinate):

    client = databases['TSS_' + server]
    db = client['coordinates']

    # Will remove previous entry if one exist
    previous_coordinate = get_coordinate(server, coordinate['_id'])
    if previous_coordinate:
        db.delete_one(previous_coordinate)

    db.insert_one(coordinate)
