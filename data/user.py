
from django.contrib.auth.models import User
from django.db import transaction
from django.forms.models import model_to_dict

from backend.models import CommandantAccount, UserExtended


# Django come with already managed user table that should not be altered
# Any other entry have to be stored into the UserExtended table

USER_TABLE_FIELDS = ('last_login', 'is_superuser', 'username', 'first_name', 'last_name',
                     'email', 'is_staff', 'is_active', 'date_joined')


@transaction.atomic
def create_user_and_user_extend(username, mail, password):
    UserExtended.objects.create(user=User.objects.create_user(username, mail, password))


def user_as_dict(user):
    # Concatenate the UserExtended entry with the Django default user
    if user is None:
        return None

    # Create extended entry if not existent (happen to superuser created from a console)
    extended = UserExtended.objects.get_or_create(user=user)[0]

    accounts = list(CommandantAccount.objects.filter(user=user).order_by('id').values_list('server', 'commandant_id', 'status'))
    return model_to_dict(user, exclude=['password', 'groups', 'user_permissions']) | \
        model_to_dict(extended, exclude=['user']) | \
        {'accounts': [(server, id) for server, id, status in accounts if status == 'active'],
         'dead_accounts': [(server, id) for server, id, status in accounts if status != 'active']}


def get_user_by_id(id):
    return user_as_dict(User.objects.filter(id=id).first())


def get_user_by_name(name):
    return user_as_dict(User.objects.filter(username=name).first())


def user_name_exist(name):
    return User.objects.filter(username=name).exists()


def user_mail_already_used(mail):
    return User.objects.filter(email=mail).exists()


def get_all_users(strify=False):
    # TODO improve text displayed in admin ? (strify)
    return [user_as_dict(user) for user in User.objects.order_by('id')]


def update_user(user, param, value):
    if param in USER_TABLE_FIELDS:
        User.objects.filter(id=user['id']).update(**{param: value})
    else:
        UserExtended.objects.filter(user=user['id']).update(**{param: value})
