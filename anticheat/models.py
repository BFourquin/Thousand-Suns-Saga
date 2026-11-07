from django.contrib.auth.models import User
from django.db import models

from backend.models import Server


# All in their own PostgreSQL schema. Named with it, these tables are found whatever the search_path : a view logs from
# any server, see database/schemas.py


def in_schema(table):
    # Django quotes the whole name : this gives "TSS_anticheat"."table"
    return 'TSS_anticheat"."' + table


class ActionLog(models.Model):
    date = models.DateTimeField(db_index=True)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='+')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='+')
    commandant_id = models.BigIntegerField()  # In the schema of the server
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    params = models.JSONField(default=dict)  # See data.admin.loggable_params : never the free texts
    status = models.PositiveSmallIntegerField()
    ip = models.GenericIPAddressField(null=True)
    fingerprint = models.CharField(max_length=16)

    class Meta:
        db_table = in_schema('action_log')
        indexes = [models.Index(fields=['server', 'date'], name='action_log_server_date')]


class LoginLog(models.Model):
    date = models.DateTimeField(db_index=True)
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE, related_name='+')  # None : the login failed
    username = models.CharField(max_length=150)  # As typed
    success = models.BooleanField()
    ip = models.GenericIPAddressField(null=True)
    fingerprint = models.CharField(max_length=16)

    class Meta:
        db_table = in_schema('login_log')


class Alert(models.Model):
    # One line per suspicion, seen again and again : closed by an admin (a family behind the same IP), it stays closed
    SEVERITIES = ('low', 'medium', 'high')

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='+')
    rule = models.CharField(max_length=30)
    subject = models.CharField(max_length=200)  # Who it is about, in the words of the rule
    severity = models.CharField(max_length=10)
    message = models.TextField()
    details = models.JSONField(default=dict)
    first_seen = models.DateTimeField()
    last_seen = models.DateTimeField()
    nb_seen = models.PositiveIntegerField(default=1)
    is_open = models.BooleanField(default=True)
    handled_by = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = in_schema('alert')
        constraints = [models.UniqueConstraint(fields=['server', 'rule', 'subject'], name='alert_unique')]


class Scan(models.Model):
    # The unique constraint makes it run once a day, even when two runs overlap or when the hour has just been changed
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='+')
    local_date = models.DateField()  # In the timezone of the server
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True)
    errors = models.TextField(blank=True)

    class Meta:
        db_table = in_schema('scan')
        constraints = [models.UniqueConstraint(fields=['server', 'local_date'], name='scan_once_a_day')]
