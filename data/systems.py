
from backend.models import System


# ######################################################################################################################
# Now that all systems and sectors ids are simply their seed, no need to keep those duplicates values stored in DB

def info_from_seed(seed):
    sector_id = seed[0:10]
    pos_y = seed[10:13]
    pos_x = seed[13:16]
    return sector_id, pos_y, pos_x


# ######################################################################################################################


def get_system_by_seed(server, seed):
    system = System.objects.filter(server=server, seed=str(seed)).first()
    return system.as_dict() if system else None


def get_system_by_position(server, sector_id, y, x):
    system = System.objects.filter(server=server, sector_id=sector_id, pos_y=y, pos_x=x).first()
    return system.as_dict() if system else None


def get_systems_in_sector(server, sector_id):
    return [system.as_dict() for system in System.objects.filter(server=server, sector_id=str(sector_id)).order_by('seed')]


def get_all_systems(server):
    return [system.as_dict() for system in System.objects.filter(server=server).order_by('seed')]


def set_system(server, system):
    # Will replace previous entry if one exist
    sector_id, pos_y, pos_x = info_from_seed(system['seed'])
    System.objects.update_or_create(server_id=server, seed=system['seed'],
                                    defaults={'system_type': system['system_type'],
                                              'system_coordinates': system['system_coordinates'],
                                              'sector_id': sector_id, 'pos_y': pos_y, 'pos_x': pos_x})
