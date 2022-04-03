
from database.db_connect import clients
from django_tss.settings import DATABASES

client = clients['TSS_main_server']


def create_table(db_name, table_name):
    try:
        clients[db_name].create_collection(table_name)
        print('[' + db_name + '] ' + table_name + ' créé.')
    except Exception as e:
        print('[' + db_name + '] ERROR : ' + str(e))


# MAIN SERVER
create_table('TSS_main_server', 'auth_user_extended')
create_table('TSS_main_server', 'server_details')


# GAME SERVERS
for db_name in clients:

    if db_name == 'TSS_main_server':
        continue

    for table_name in ('commandant', 'starting_values', 'city', 'building', 'modifier', 'technology',
                       'ship_component', 'ship_design', 'fleet', 'faction', 'planet', 'system', 'sector'):
        create_table(db_name, table_name)
