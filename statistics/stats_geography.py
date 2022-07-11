
from data import systems


def statistics_systems_types_per_sector(server):
    """Count every system types in every sector"""

    systems_list = systems.get_all_systems(server)
    system_types_stats = {}

    for system in systems_list:

        system_type = system['system_type']
        sector_id = system['_id'][:12]

        if system_type not in system_types_stats:
            system_types_stats[system_type] = {}

        if sector_id not in system_types_stats[system_type]:
            system_types_stats[system_type][sector_id] = 1
        else:
            system_types_stats[system_type][sector_id] += 1

    return system_types_stats


def statistics_systems_types_global(server):
    """Count every system types in the whole server"""

    stats = statistics_systems_types_per_sector(server)
    for system_type, values in stats.items():
        stats[system_type] = sum(values.values())

    return stats
