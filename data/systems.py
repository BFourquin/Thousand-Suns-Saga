
from game.models import System
from database.schemas import on_server


@on_server
def get_system_by_seed(server, seed):
    system = System.objects.filter(seed=str(seed)).first()
    return system.as_dict() if system else None


@on_server
def get_system_by_position(server, sector_id, y, x):
    system = System.objects.filter(sector_id=sector_id, pos_y=y, pos_x=x).first()
    return system.as_dict() if system else None


@on_server
def get_systems_in_sector(server, sector_id):
    return [system.as_dict() for system in System.objects.filter(sector_id=str(sector_id)).order_by('seed')]


@on_server
def get_all_systems(server):
    return [system.as_dict() for system in System.objects.all().order_by('seed')]
