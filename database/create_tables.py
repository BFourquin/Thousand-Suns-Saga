
from database.db_connect import clients
from django_tss.settings import DATABASES

client = clients['TSS_main_server']


def create_table(db_name, table_name):
    try:
        clients[db_name].create_collection(table_name)
        print('[' + db_name + '] ' + table_name + ' créé.')
    except Exception as e:
        print('[' + db_name + '] ERROR : ' + str(e))


if __name__ == '__main__':

    # MAIN SERVER
    create_table('TSS_main_server', 'auth_user_extended')
    create_table('TSS_main_server', 'server_details')

    # GAME SERVERS
    for db_name in clients:

        if db_name == 'TSS_main_server':
            continue

        for table_name in ('commandants', 'starting_values', 'cities', 'buildings', 'modifiers', 'technologies',
                           'ship_components', 'ship_designs', 'fleets', 'factions', 'coordinates', 'systems', 'sectors',
                           'map_generator', 'mg_sectors', 'mg_systems_types',  'mg_systems', 'mg_suns', 'mg_planets',
                           'statistics', 'mg_statistics'):
            create_table(db_name, table_name)
