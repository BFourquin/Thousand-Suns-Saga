
from game.models import Sector
from database.schemas import on_server


@on_server
def get_sector_by_seed(server, seed):
    sector = Sector.objects.filter(seed=str(seed)).first()
    return sector.as_dict() if sector else None

