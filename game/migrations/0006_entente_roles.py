import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


def create_default_roles(apps, schema_editor):
    EntenteRole = apps.get_model('game', 'EntenteRole')
    EntenteMember = apps.get_model('game', 'EntenteMember')

    for entente in apps.get_model('game', 'Entente').objects.exclude(category='native'):
        role = EntenteRole.objects.create(entente=entente, is_default=True)
        EntenteMember.objects.filter(entente=entente, status='member').exclude(commandant_id=entente.owner_id).update(role=role)


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0005_ententes'),
    ]

    operations = [
        migrations.RenameField(
            model_name='entente',
            old_name='founder',
            new_name='owner',
        ),
        migrations.CreateModel(
            name='EntenteRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=40)),
                ('is_default', models.BooleanField(default=False)),
                ('options', models.JSONField(default=list)),
                ('entente', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='roles', to='game.entente')),
            ],
        ),
        migrations.AddField(
            model_name='ententemember',
            name='role',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='members', to='game.ententerole'),
        ),
        migrations.AddConstraint(
            model_name='ententerole',
            constraint=models.UniqueConstraint(condition=models.Q(('is_default', True)), fields=('entente',), name='one_default_role_per_entente'),
        ),
        migrations.AddConstraint(
            model_name='ententerole',
            constraint=models.UniqueConstraint(models.F('entente'), django.db.models.functions.text.Lower('name'), condition=models.Q(('is_default', False)), name='entente_role_name_unique'),
        ),
        migrations.RunPython(create_default_roles, migrations.RunPython.noop),
    ]
