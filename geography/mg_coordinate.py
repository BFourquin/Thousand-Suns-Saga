
from data import coordinates


def create_coordinate(seed, coordinate_type, subtype):

    coordinate = {
        '_id': seed,
        'type': coordinate_type,
        'subtype': subtype
    }

    coordinates.set_coordinate(coordinate)