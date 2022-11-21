
from data import coordinates, mg_statistics


def create_coordinate(server, seed, coordinate_type, subtype):

    coordinate = {
        '_id': seed,
        'type': coordinate_type,
        'subtype': subtype
    }

    coordinates.set_coordinate(server, coordinate)

    # Statistics keeping

    if 'coordinate_type' not in mg_statistics.mg_stats_buffer:
        mg_statistics.mg_stats_buffer['coordinate_type'] = {}

    if coordinate_type  not in mg_statistics.mg_stats_buffer['coordinate_type']:
        mg_statistics.mg_stats_buffer['coordinate_type'][coordinate_type] = 1
    else:
        mg_statistics.mg_stats_buffer['coordinate_type'][coordinate_type] += 1
