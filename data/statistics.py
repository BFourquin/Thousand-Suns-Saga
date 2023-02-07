
from database.db_connect import databases

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


def get_statistics_category(server, stats_category):
    """Get a whole stats_category"""

    client = databases['TSS_' + server]
    db = client['statistics']
    stats_entry = db.find_one({"stats_category": stats_category})

    if stats_entry:
        return stats_entry["stats"]


def get_statistic(server, stats_category, stat_name):
    """Get a single stat in a stats_category"""

    stats = get_statistics_category(server, stats_category)
    if stat_name in stats:
        return stats[stat_name]
    

def set_statistics_category(server, stats_category, stats):

    client = databases['TSS_' + server]
    db = client['statistics']

    db.delete_one({"stats_category": stats_category})
    db.insert_one({"stats_category": stats_category, "stats": stats})


def set_statistic(server, stats_category, stat_name, stat_value):

    stats = get_statistics_category(server, stats_category)
    stats[stat_name] = stat_value

    set_statistics_category(server, stats_category, stats)

"""
def insert_statistics_buffer_into_db(server, stats_category):

    print("MG BUFFER >")
    print(mg_stats_buffer)
    for stat_name, stat_value in mg_stats_buffer.items():
        set_statistics(server, stat_name, stat_value)
"""