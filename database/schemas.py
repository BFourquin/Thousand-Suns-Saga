"""
PostgreSQL schemas : TSS_main_server holds what is common to all the game servers (accounts, list of servers),
each game server has its own schema TSS_<server name> holding the tables of the app 'game'.

The tables are found through the search_path of the connection, so the models of the app 'game' can only be used
inside server_schema() or a function decorated by on_server. Outside, the query fails : it can't read the wrong server.
"""

import threading
from contextlib import contextmanager
from functools import wraps

from django.core.management import call_command
from django.db import DatabaseError, connection
from django.db.migrations.recorder import MigrationRecorder

MAIN_SCHEMA = 'TSS_main_server'

_state = threading.local()


def schema_of(server):
    return 'TSS_' + server


def quoted(schema):
    return '"' + schema.replace('"', '""') + '"'


def current_server():
    return getattr(_state, 'server', None)


def _set_search_path(*schemas):
    with connection.cursor() as cursor:
        # As a parameter : the server name can come from a request
        cursor.execute("SELECT set_config('search_path', %s, false)", [', '.join(quoted(schema) for schema in schemas)])


@contextmanager
def server_schema(server):
    previous = current_server()
    if server == previous:  # Data functions call each other : no query for that
        yield
        return

    # Main schema after the server's one : game tables reference auth_user
    _set_search_path(schema_of(server), MAIN_SCHEMA)
    _state.server = server
    try:
        yield
    finally:
        _state.server = previous
        try:
            _set_search_path(*((schema_of(previous), MAIN_SCHEMA) if previous else (MAIN_SCHEMA,)))
        except DatabaseError:
            pass  # Transaction in error : its rollback puts the search_path back by itself


def on_server(function):
    # For the functions whose first argument is the server name

    @wraps(function)
    def wrapper(server, *args, **kwargs):
        with server_schema(server):
            return function(server, *args, **kwargs)
    return wrapper


########################################################################################################################
# CREATION AND MIGRATION


class ServerSchemaRouter:
    # 'game' tables only exist in the schemas of the game servers, all the others only in the main schema

    def allow_migrate(self, db, app_label, **hints):
        return (app_label == 'game') == (current_server() is not None)


def create_main_schema(**kwargs):
    # Receiver of pre_migrate : the first migrate needs the schema of its search_path
    with connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA IF NOT EXISTS ' + quoted(MAIN_SCHEMA))


def migrate_server(server):
    # Each server records its own migrations : with its search_path alone, Django creates that table in its schema
    _set_search_path(schema_of(server))
    MigrationRecorder(connection).ensure_schema()
    _set_search_path(MAIN_SCHEMA)

    with server_schema(server):
        call_command('migrate', 'game', verbosity=0)


def create_server_schema(server):
    with connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA ' + quoted(schema_of(server)))
    migrate_server(server)


def drop_server_schema(server):
    with connection.cursor() as cursor:
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')  # Refused otherwise if the transaction has just written in it
        cursor.execute('DROP SCHEMA IF EXISTS ' + quoted(schema_of(server)) + ' CASCADE')
