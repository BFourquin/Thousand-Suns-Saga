
from database.db_connect import databases

mg_stats_buffer = {}  # Used as alternative to write many thousand times updates in the DB


def get_mg_statistics(server, stats_type):

    client = databases['TSS_' + server]
    db = client['mg_statistics']
    stats_entry = db.find_one({"stats_type": stats_type})

    if stats_entry:
        del stats_entry["stats_type"]
        return stats_entry


def set_mg_statistics(server, stats_type, stats):

    client = databases['TSS_' + server]
    db = client['mg_statistics']

    db.delete_one({"stats_type": stats_type})
    db.insert_one({"stats_type": stats_type, **stats})


def insert_mg_statistics_buffer_into_db(server):

    for stats_type, stats in mg_stats_buffer.items():
        set_mg_statistics(server, stats_type, stats)
