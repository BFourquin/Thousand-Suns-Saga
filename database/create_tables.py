
from database.db_connect import databases
from django_tss.settings import DATABASES

client = databases['TSS_main_server']


server_tables_names = ('commandants', 'starting_values', 'cities', 'buildings', 'modifiers', 'technologies',
                       'ship_components', 'ship_designs', 'fleets', 'factions', 'coordinates', 'systems', 'sectors',
                       'map_generator', 'mg_sectors', 'mg_systems_types',  'mg_systems', 'mg_suns', 'mg_planets',
                       'statistics')



def create_table(db_name, table_name, printing=True):
    try:
        databases[db_name].create_collection(table_name)
        if printing:
            print('[' + db_name + '] ' + table_name + ' créé.')
    except Exception as e:
        if printing:
            print('[' + db_name + '] ERROR : ' + str(e))


def create_server_database(db_name):

    # MAIN SERVER

    # in case it's the first time you deploy a server
    create_table('TSS_main_server', 'auth_user_extended')
    create_table('TSS_main_server', 'server_details')

    # GAME SERVERS
    for table_name in server_tables_names:
        create_table(db_name, table_name)



if __name__ == '__main__':

    for db_name in databases:
        if db_name != 'TSS_main_server':
            create_server_database(db_name)
