
from game.models import Sector
from database.schemas import on_server


@on_server
def get_sector(server, y, x):
    sector = Sector.objects.filter(pos_y=y, pos_x=x).first()
    return sector.as_dict() if sector else None


@on_server
def get_sector_by_seed(server, seed):
    sector = Sector.objects.filter(seed=str(seed)).first()
    return sector.as_dict() if sector else None


@on_server
def get_direct_neighbours_sectors(server, y, x):
    neighbours_sectors = [
        get_sector(server, y-1, x),
        get_sector(server, y+1, x),
        get_sector(server, y, x-1),
        get_sector(server, y, x+1)
    ]
    neighbours_sectors = [_ for _ in neighbours_sectors if _]  # Remove none
    return neighbours_sectors


@on_server
def get_diagonal_neighbours_sectors(server, y, x):
    neighbours_sectors = [
        get_sector(server, y-1, x-1),
        get_sector(server, y-1, x+1),
        get_sector(server, y+1, x-1),
        get_sector(server, y+1, x+1)
    ]
    neighbours_sectors = [_ for _ in neighbours_sectors if _]  # Remove none
    return neighbours_sectors


@on_server
def set_sector(server, sector):
    # Will replace previous entry if one exist
    Sector.objects.update_or_create(seed=sector['seed'],
                                    defaults={k: v for k, v in sector.items() if k not in ('id', 'seed')})
