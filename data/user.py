
from bson.objectid import ObjectId

from django.contrib.auth.models import User

from database.db_connect import clients

client = clients['TSS_main_server']
db_user = client['auth_user']
db_extend = client['auth_user_extended']


# Django come with already managed user table that should not be altered
# Any other entry have to be stored into the 'auth_user_extended' table


def create_user_and_user_extend(username, mail, password):
    User.objects.create_user(username, mail, password)
    user = db_user.find_one({'username': username})

    extended_table = {'_id': user['_id'],
                      'id': user['id'],
                      'status': 'active',
                      'accounts': {},
                      'dead_accounts': {},
                      'banned_until': None,
                      'banned_reason': None,
                      }

    db_extend.insert_one(extended_table)


def add_user_extended(user):
    # Concatenate the auth_user_extended entry with the Django default auth_user
    if user is not None:
        print(user)
        print(db_extend.find_one({'_id': user['_id']}))
        return user | db_extend.find_one({'_id': user['_id']})
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