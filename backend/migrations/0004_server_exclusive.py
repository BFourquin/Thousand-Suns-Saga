from django.db import migrations
from django.db.models import Case, Value, When


def invert(apps, schema_editor):
    # 'multi-accounts forbidden' was what is now called exclusive
    apps.get_model('backend', 'Server').objects.update(exclusive=Case(When(exclusive=True, then=Value(False)), default=Value(True)))


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0003_forums_on_each_server'),
    ]

    operations = [
        migrations.RenameField('server', 'allow_multiaccounts', 'exclusive'),
        migrations.RunPython(invert, invert),
    ]
