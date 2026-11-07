from django.contrib.auth.models import User
from django.db import models
from django.db.models.functions import Lower
from django.forms.models import model_to_dict


# Tables of the main schema, common to all the game servers. The tables of each server are in the app 'game'.


def to_id(value):
    # Ids come from the requests : anything but an integer matches nothing
    return int(value) if str(value).isdecimal() else None


class GameModel(models.Model):
    # The data layer hands plain dicts to the views and templates, foreign keys under their short name

    class Meta:
        abstract = True

    def as_dict(self):
        return model_to_dict(self)


# The game is over there : see backend.utils.orders_closed
FINISHED_SERVER_STATUSES = ('stop', 'dead')

# Local hours of the server, from the sheet Config of its Excel
SERVER_HOURS = ('hour_cycle', 'hour_first_combat_round', 'hour_second_combat_round', 'hour_third_combat_round', 'hour_anticheat_checks')


class Server(GameModel):
    server_name = models.CharField(primary_key=True, max_length=59)  # Its schema has 'TSS_' more, and 63 characters at most
    version = models.FloatField()
    gameplay = models.CharField(max_length=20)
    status = models.CharField(max_length=10)
    admin_only_visibility = models.BooleanField(default=True)
    creation_date = models.DateTimeField()
    opening_date = models.DateTimeField()
    end_date = models.DateTimeField(null=True, blank=True)
    language = models.CharField(max_length=20)
    roleplay = models.CharField(max_length=10)
    exclusive = models.BooleanField(default=False)  # A serious server, asking a lot of time : a player can only be on one of them
    timezone = models.CharField(max_length=50)
    hour_cycle = models.PositiveSmallIntegerField(default=22)
    hour_first_combat_round = models.PositiveSmallIntegerField(default=8)
    hour_second_combat_round = models.PositiveSmallIntegerField(default=13)
    hour_third_combat_round = models.PositiveSmallIntegerField(default=20)
    hour_anticheat_checks = models.PositiveSmallIntegerField(default=4)

    class Meta:
        # Also for the values changed by hand in the database
        constraints = [models.CheckConstraint(check=models.Q(**{hour + '__lte': 23}), name=hour + '_is_an_hour') for hour in SERVER_HOURS]

    def as_dict(self):
        accounts = list(self.commandant_accounts.values_list('commandant_id', 'status', 'user_id'))
        return model_to_dict(self) | {
            'active_commandants': [id for id, status, _ in accounts if status == 'active'],
            'dead_commandants': [id for id, status, _ in accounts if status != 'active'],
            'active_users': sorted({user_id for _, status, user_id in accounts if status == 'active'}),
        }


class CommandantAccount(models.Model):
    # Who plays which commandant on which server. A constraint can't span schemas : the names unique on all the servers
    # and the commandants of a player are kept here, the commandant itself being in the schema of its server.
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='commandant_accounts')
    commandant_id = models.BigIntegerField()
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commandant_accounts')
    commandant_name = models.CharField(max_length=100)
    status = models.CharField(max_length=10, default='active')

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('commandant_name'), name='commandant_name_unique'),
            models.UniqueConstraint(fields=['server', 'commandant_id'], name='commandant_unique_on_server'),
        ]


class UserExtended(models.Model):
    # Django come with already managed user table that should not be altered
    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    status = models.CharField(max_length=10, default='active')
    banned_until = models.DateTimeField(null=True, blank=True)
    banned_reason = models.TextField(null=True, blank=True)
    language = models.CharField(max_length=2, default='en')
    dark_mode = models.BooleanField(default=True)
    theme = models.CharField(max_length=20, default='classic')
    playing_on_server = models.ForeignKey(Server, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    playing_on_commandant = models.BigIntegerField(null=True, blank=True)  # In the schema of playing_on_server
