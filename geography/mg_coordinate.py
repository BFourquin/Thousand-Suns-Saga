
from data import coordinates, statistics


def create_coordinate(server, seed, coordinate_type, subtype):

    coordinate = {
        '_id': seed,
        'type': coordinate_type,
        'subtype': subtype
    }

    coordinates.set_coordinate(server, coordinate)

    # Statistics keeping

    if 'coordinate_type' not in statistics.mg_stats_buffer:
        statistics.mg_stats_buffer['coordinate_type'] = {}

    if coordinate_type not in statistics.mg_stats_buffer['coordinate_type']:
        statistics.mg_stats_buffer['coordinate_type'][coordinate_type] = 1
    else:
        statistics.mg_stats_buffer['coordinate_type'][coordinate_type] += 1
