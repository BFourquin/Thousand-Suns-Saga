
from database.db_connect import databases
import coordinates


def get_colony(server, id):

    client = databases['TSS_' + server]
    db = client['colony']
    return db.find_one({"_id": id})


def get_all_colonies(server):
    client = databases['TSS_' + server]
    db = client['colony']
    return list(db.find())


def set_colony(server, colony):

    client = databases['TSS_' + server]
    db = client['colony']

    # Will remove previous entry if one exist
    previous_colony = get_colony(server, colony['_id'])
    if previous_colony:
        db.delete_one(previous_colony)


    home_coordinate = coordinates.get_coordinate(server, colony['coordinate'])
    colony['coordinate'] = home_coordinate

    db.insert_one(colony)


