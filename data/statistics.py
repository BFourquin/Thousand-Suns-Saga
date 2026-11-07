
from game.models import Statistic
from database.schemas import on_server

mg_stats_buffer = {}  # Used as alternative to write many thousand times updates in the DB

"""
Statistics have one entry for each stats_category :

{
    'stats_category': 'map_generation',
    'stats': {
        'exemple1' : 0,
        'exemple2' : 1,
        }
}
"""


@on_server
def get_statistics_category(server, stats_category):
    """Get a whole stats_category"""

    stats_entry = Statistic.objects.filter(stats_category=stats_category).first()

    if stats_entry:
        return stats_entry.stats


@on_server
def set_statistics_category(server, stats_category, stats):
    Statistic.objects.update_or_create(stats_category=stats_category, defaults={'stats': stats})


"""
@on_server
def insert_statistics_buffer_into_db(server, stats_category):

    print("MG BUFFER >")
    print(mg_stats_buffer)
    for stat_name, stat_value in mg_stats_buffer.items():
        set_statistics(server, stat_name, stat_value)
"""