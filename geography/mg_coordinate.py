
from data import coordinates, statistics


def info_from_seed(seed):
    seed = str(seed)
    sector_id = int(seed[0:10])
    system_id = int(seed[0:16])
    sys_y = int(seed[10:13])
    sys_x = int(seed[13:16])
    sys_coordinate = int(seed[16:18])
    return sector_id, system_id, sys_y, sys_x, sys_coordinate


def create_coordinate(server, seed, coordinate_type, subtype):

    coordinate = {'_id': str(seed),
                  'type': coordinate_type,
                  'subtype': subtype,
                  'sector_id': info_from_seed(seed)[0],
                  'system_id': info_from_seed(seed)[1],
                  'sys_y': info_from_seed(seed)[2],
                  'sys_x': info_from_seed(seed)[3],
                  'sys_coordinate': info_from_seed(seed)[4],
                  'name': str(seed),
                  'fleet_modifiers': [],
                  'colony_modifiers': [],
                  'colonies': []
                  }

    coordinates.set_coordinate(server, coordinate)

    # Statistics keeping

    if 'coordinate_type' not in statistics.mg_stats_buffer:
        statistics.mg_stats_buffer['coordinate_type'] = {}

    if coordinate_type not in statistics.mg_stats_buffer['coordinate_type']:
        statistics.mg_stats_buffer['coordinate_type'][coordinate_type] = 1
    else:
        statistics.mg_stats_buffer['coordinate_type'][coordinate_type] += 1
