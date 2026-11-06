from django.apps import AppConfig
from django.db.models.signals import pre_migrate


class BackendConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'backend'

    def ready(self):
        from database.schemas import create_main_schema
        pre_migrate.connect(create_main_schema, sender=self)
