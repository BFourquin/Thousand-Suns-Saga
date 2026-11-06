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
    allow_multiaccounts = models.BooleanField(default=False)
    timezone = models.CharField(max_length=50)

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


########################################################################################################################
# FORUMS


class ForumTopic(GameModel):
    # Base of the topics of each server (game.Topic) and of the out-of-character forum common to all of them (HrpTopic)
    title = models.CharField(max_length=150)
    last_post_date = models.DateTimeField()

    class Meta:
        abstract = True


class ForumPost(GameModel):
    body = models.TextField()
    datetime = models.DateTimeField()

    class Meta:
        abstract = True


class HrpTopic(ForumTopic):
    section = models.CharField(max_length=20, db_index=True)  # See data/hrp_forum.py
    # SET_NULL : a thread outlives the account of one of its authors
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    last_author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')


class HrpPost(ForumPost):
    topic = models.ForeignKey(HrpTopic, on_delete=models.CASCADE, related_name='posts')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
