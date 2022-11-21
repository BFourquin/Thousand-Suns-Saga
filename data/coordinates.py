
from database.db_connect import clients


def get_coordinate(server, seed):

    client = clients['TSS_'+server]
    db = client['coordinates']
    return db.find_one({"_id": seed})


def set_coordinate(server, coordinate):

    client = clients['TSS_'+server]
    db = client['coordinates']

    # Will remove previous entry if one exist
    previous_coordinate = get_coordinate(server, coordinate['_id'])
    if previous_coordinate:
        db.delete_one(previous_coordinate)

    db.insert_one(coordinate)
