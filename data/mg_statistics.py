
from database.db_connect import clients

mg_stats_buffer = {}  # Used as alternative to write many thousand times updates in the DB


def get_mg_statistics(server, stats_type):

    client = clients['TSS_'+server]
    db = client['mg_statistics']
    stats_entry = db.find_one({})
    if stats_type in stats_entry:
        return stats_entry[stats_type]


def set_mg_statistics(server, stats_type, stats):

    client = clients['TSS_'+server]
    db = client['mg_statistics']

    stats_entry = db.find_one({})
    if stats_entry is None:
        stats_entry = {}
    stats_entry[stats_type] = stats

    db.upsert_one({"stats_type": stats_type, "stats": stats})


def insert_mg_statistics_buffer_into_db(server):

    for stats_type, stats in mg_stats_buffer.items():
        set_mg_statistics(server, stats_type, stats)
