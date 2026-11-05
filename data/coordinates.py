
from database.db_connect import collection


def get_coordinate(server, seed):

    db = collection(server, 'coordinates')
    return db.find_one({"_id": str(seed)})


def get_all_coordinates(server):
    db = collection(server, 'coordinates')
    return list(db.find())


def set_coordinate(server, coordinate):

    db = collection(server, 'coordinates')

    # Will remove previous entry if one exist
    previous_coordinate = get_coordinate(server, coordinate['_id'])
    if previous_coordinate:
        db.delete_one(previous_coordinate)

    db.insert_one(coordinate)
