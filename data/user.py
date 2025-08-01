
from bson.objectid import ObjectId

try:
    from django.contrib.auth.models import User
except:
    ...  # Django needed, but won't be available or needed when used from create_new_server.py

from database.db_connect import databases


client = databases['TSS_main_server']
db_user = client['auth_user']
db_extend = client['auth_user_extended']


# Django come with already managed user table that should not be altered
# Any other entry have to be stored into the 'auth_user_extended' table


def create_user_and_user_extend(username, mail, password):
    User.objects.create_user(username, mail, password)
    create_user_extend(username)


def create_user_extend(username):
    user = db_user.find_one({'username': username})

    extended_table = {'_id': user['_id'],
                      'id': user['_id'],
                      'status': 'active',
                      'accounts': [],
                      'dead_accounts': [],
                      'banned_until': None,
                      'banned_reason': None,
                      'language': 'en',
                      'dark_mode': True,
                      'playing_on_server': None,
                      'playing_on_commandant': None,
                      }

    db_extend.insert_one(extended_table)
    return extended_table


def add_user_extended(user):
    # Concatenate the auth_user_extended entry with the Django default auth_user
    if user is not None:

        extended_infos = db_extend.find_one({'_id': user['_id']})

        # Create extended entry if not existent (happen to superuser created from a console)
        if extended_infos is None:
            extended_infos = create_user_extend(user['username'])

        return user | extended_infos
    return None


def get_user_by_id(id):
    user = db_user.find_one({'id': int(id)})
    user = add_user_extended(user)
    return user


def get_user_by_object_id(_id):
    user = db_user.find_one({'_id': ObjectId(_id)})
    user = add_user_extended(user)
    return user


def get_user_by_name(name):
    user = db_user.find_one({'username': name})
    user = add_user_extended(user)
    return user


def user_name_exist(name):
    return bool(db_user.find_one({'username': name}))


def user_mail_already_used(mail):
    return bool(db_user.find_one({'email': mail}))


def get_all_users(strify=False):

    users = []

    for user in list(db_user.find({})):
        user = add_user_extended(user)
        if strify:
            ...  # TODO improve text displayed in admin ?
        users.append(user)

    return users


def update_user(user, param, value):

    # Default django user table
    if param in ('last_login', 'is_superuser', 'username', 'first_name', 'last_name',
                 'email', 'is_staff', 'is_active', 'date_joined'):
        db_user.update_one({"_id": user['_id']}, {"$set": {param: value}})

    # Extended user table
    else:
        db_extend.update_one({"_id": user['_id']}, {"$set": {param: value}})


def push_param_user(user_id, param, value):

    # Default django user table
    if param in ('last_login', 'is_superuser', 'username', 'first_name', 'last_name',
                 'email', 'is_staff', 'is_active', 'date_joined'):
        db_user.update_one({"_id": user_id}, {"$push": {param: value}})

    # Extended user table
    else:
        db_extend.update_one({"_id": user_id}, {"$push": {param: value}})


def pull_param_user(user_id, param, value):

    # Default django user table
    if param in ('last_login', 'is_superuser', 'username', 'first_name', 'last_name',
                 'email', 'is_staff', 'is_active', 'date_joined'):
        db_user.update_one({"_id": user_id}, {"$pull": {param: value}})

    # Extended user table
    else:
        db_extend.update_one({"_id": user_id}, {"$pull": {param: value}})