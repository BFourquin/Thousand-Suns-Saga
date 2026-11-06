from django.db import migrations, models


def give_colonial_optimism_to_existing_colonies(apps, schema_editor):
    # Same values as data.modifiers.MODIFIER_TYPES at the time of this migration : new colonies receive it when founded
    Modifier = apps.get_model('game', 'Modifier')
    for coordinate in apps.get_model('game', 'Colony').objects.values_list('coordinate', flat=True):
        Modifier.objects.create(modifier_type='colonial_optimism', scope='coordinate', target=coordinate, duration=10, cycles_left=10)


class Migration(migrations.Migration):

    dependencies = [
        ('game', '0006_entente_roles'),
    ]

    operations = [
        migrations.CreateModel(
            name='Modifier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('modifier_type', models.CharField(max_length=100)),
                ('scope', models.CharField(max_length=15)),
                ('target', models.CharField(db_index=True, max_length=30)),
                ('duration', models.IntegerField(blank=True, null=True)),
                ('cycles_left', models.IntegerField(blank=True, null=True)),
            ],
        ),
        migrations.RunPython(give_colonial_optimism_to_existing_colonies, migrations.RunPython.noop),
    ]
