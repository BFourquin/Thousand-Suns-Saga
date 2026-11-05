from django.contrib.auth.models import User
from django.db import models
from django.db.models.functions import Lower
from django.forms.models import model_to_dict


def to_id(value):
    # Ids come from the requests : anything but an integer matches nothing
    return int(value) if str(value).isdecimal() else None


class GameModel(models.Model):
    # The data layer hands plain dicts to the views and templates, foreign keys under their short name

    class Meta:
        abstract = True

    def as_dict(self):
        return model_to_dict(self)


########################################################################################################################
# ACCOUNTS AND SERVERS


class Server(GameModel):
    server_name = models.CharField(primary_key=True, max_length=100)
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
        commandants = list(self.commandants.values_list('id', 'status', 'user_id'))
        return model_to_dict(self) | {
            'active_commandants': [id for id, status, _ in commandants if status == 'active'],
            'dead_commandants': [id for id, status, _ in commandants if status != 'active'],
            'active_users': sorted({user_id for _, status, user_id in commandants if status == 'active'}),
        }


class Commandant(GameModel):
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='commandants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commandants')

    commandant_name = models.CharField(max_length=100)
    civilisation_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=10)
    portrait = models.CharField(max_length=255)
    flag = models.CharField(max_length=255)
    status = models.CharField(max_length=10, default='active')
    creation_date = models.DateTimeField()

    # Starting position
    native_entente = models.CharField(max_length=100, null=True, blank=True)
    native_sector = models.CharField(max_length=10)
    native_system = models.CharField(max_length=16)
    native_planet = models.CharField(max_length=18)

    # Empire and allegiances
    capital = models.CharField(max_length=18, null=True, blank=True)
    resources = models.JSONField(default=dict)
    technologies = models.JSONField(default=dict)
    player_modifiers = models.JSONField(default=dict)
    owned_ship_designs = models.JSONField(default=list)
    orientations = models.JSONField(default=dict)

    nb_unread_reports = models.IntegerField(default=0)

    time_last_activity = models.DateTimeField(null=True, blank=True)
    time_cycle_finished = models.DateTimeField(null=True, blank=True)
    tutorial_step = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('commandant_name'), name='commandant_name_unique'),
            models.UniqueConstraint(Lower('civilisation_name'), 'server', name='civilisation_name_unique_on_server'),
        ]

    def as_dict(self):
        return super().as_dict() | {'colonies': list(self.colonies.order_by('id').values_list('id', flat=True))}


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
    playing_on_commandant = models.ForeignKey(Commandant, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')


########################################################################################################################
# COLONIES


class Colony(GameModel):
    name = models.CharField(max_length=100)
    owner = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='colonies')
    controller = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='+')
    coordinate = models.CharField(max_length=18)
    colony_type = models.CharField(max_length=50)
    districts_slots_occupied = models.IntegerField(default=0)
    districts_slots_total = models.IntegerField(default=0)

    def as_dict(self):
        return super().as_dict() | {'districts': list(self.districts.order_by('id').values_list('id', flat=True))}


class District(GameModel):
    colony = models.ForeignKey(Colony, on_delete=models.CASCADE, related_name='districts')
    district_type = models.CharField(max_length=100)
    category = models.CharField(max_length=50)
    buildings_slots_free = models.IntegerField(default=0)
    buildings_slots_total = models.IntegerField(default=0)
    population = models.BigIntegerField(null=True, blank=True)
    population_details = models.JSONField(null=True, blank=True)
    transports_needs = models.FloatField(default=0)
    transports_cars_needs = models.FloatField(default=0)
    transports_public_needs = models.FloatField(default=0)
    transports_planes_needs = models.FloatField(default=0)
    transports_spaceshuttles_needs = models.FloatField(default=0)
    power_needs = models.FloatField(default=0)
    power_satisfaction = models.FloatField(default=0)
    hp = models.IntegerField(null=True, blank=True)
    hp_max = models.IntegerField(null=True, blank=True)
    damages = models.IntegerField(default=0)


class Building(GameModel):
    name_fr = models.CharField(max_length=100, null=True, blank=True)
    name_en = models.CharField(max_length=100, null=True, blank=True)
    building_type = models.CharField(max_length=100)
    home_district = models.ForeignKey(District, on_delete=models.CASCADE, related_name='buildings')
    local_modifiers = models.JSONField(default=list)
    player_modifiers = models.JSONField(default=list)
    faction_modifiers = models.JSONField(default=list)
    activation_percent = models.IntegerField(default=100)
    last_cycle_missing_resources = models.JSONField(default=dict)
    last_cycle_production = models.FloatField(default=0)
    last_cycle_productivity_percent = models.FloatField(default=0)


########################################################################################################################
# REPORTS AND CYCLES


class Report(GameModel):
    owner = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='reports')
    status = models.CharField(max_length=10, default='unread')  # 'unread' | 'read' | 'archived'
    category = models.CharField(max_length=50)
    category_icon = models.CharField(max_length=50)
    datetime = models.DateTimeField()
    tss_calendar = models.DateTimeField()
    illustration = models.CharField(max_length=255, null=True, blank=True)
    title = models.TextField()
    message = models.TextField()
    sender = models.CharField(max_length=100, null=True, blank=True)
    sender_image = models.CharField(max_length=255, null=True, blank=True)


class Cycle(GameModel):
    COMMANDANTS_LISTS = ('commandants_cycle_playing', 'commandants_cycle_finished', 'commandants_cycle_absent')

    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='cycles')
    cycle_nb = models.IntegerField()
    datetime_start = models.DateTimeField()
    datetime_end = models.DateTimeField(null=True, blank=True)
    datetime_planned_end = models.DateTimeField(null=True, blank=True)  # Long-term version : daily passing of cycles

    # Boardgame version : manual passing of cycles
    commandants_cycle_playing = models.ManyToManyField(Commandant, related_name='+')
    commandants_cycle_finished = models.ManyToManyField(Commandant, related_name='+')
    commandants_cycle_absent = models.ManyToManyField(Commandant, related_name='+')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['server', 'cycle_nb'], name='cycle_nb_unique_on_server')]

    def as_dict(self):
        cycle = model_to_dict(self, exclude=self.COMMANDANTS_LISTS)
        for field in self.COMMANDANTS_LISTS:
            cycle[field] = sorted(getattr(self, field).values_list('id', flat=True))
        return cycle


########################################################################################################################
# GEOGRAPHY


class GeographyModel(GameModel):
    # A seed is only unique inside a server : two servers can be generated from the same Excel file

    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    seed = models.CharField(max_length=18)

    class Meta:
        abstract = True
        constraints = [models.UniqueConstraint(fields=['server', 'seed'], name='%(class)s_seed_unique_on_server')]

    def as_dict(self):
        return {'id': self.seed} | model_to_dict(self, exclude=['id', 'server'])


class Sector(GeographyModel):
    pos_y = models.IntegerField()
    pos_x = models.IntegerField()
    sector_type = models.CharField(max_length=50, null=True, blank=True)
    nb_systems = models.IntegerField(null=True, blank=True)
    nb_natives_start = models.IntegerField(null=True, blank=True)
    systems_coordinates = models.JSONField(default=list)

    class Meta(GeographyModel.Meta):
        constraints = GeographyModel.Meta.constraints + [
            models.UniqueConstraint(fields=['server', 'pos_y', 'pos_x'], name='sector_position_unique_on_server')]


class System(GeographyModel):
    system_type = models.CharField(max_length=50)
    system_coordinates = models.JSONField(default=dict)
    sector_id = models.CharField(max_length=10, db_index=True)
    pos_y = models.CharField(max_length=3)
    pos_x = models.CharField(max_length=3)


class Coordinate(GeographyModel):
    type = models.CharField(max_length=50)
    subtype = models.CharField(max_length=50, null=True, blank=True)
    sector_id = models.CharField(max_length=10)
    system_id = models.CharField(max_length=16)
    sys_y = models.IntegerField()
    sys_x = models.IntegerField()
    sys_coordinate = models.IntegerField()
    name = models.CharField(max_length=100)
    fleet_modifiers = models.JSONField(default=list)
    colony_modifiers = models.JSONField(default=list)
    colonies = models.JSONField(default=list)


########################################################################################################################
# SERVER CONFIGURATION, LOADED FROM ITS EXCEL FILE


class ConfigurationModel(models.Model):
    # The columns of these rows are decided by the Excel file, hence a JSON document

    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    data = models.JSONField()

    class Meta:
        abstract = True

    def as_dict(self):
        return {'id': self.pk} | self.data


class NamedConfigurationModel(ConfigurationModel):
    internal_name = models.CharField(max_length=100)

    class Meta:
        abstract = True
        constraints = [models.UniqueConstraint(fields=['server', 'internal_name'], name='%(class)s_name_unique_on_server')]


class Resource(NamedConfigurationModel):
    ...


class ResourceCategory(NamedConfigurationModel):
    ...


class ResourceSubcategory(NamedConfigurationModel):
    ...


class Technology(NamedConfigurationModel):
    ...


class DistrictType(NamedConfigurationModel):
    ...


class BuildingType(NamedConfigurationModel):
    ...


class MapGeneratorParameter(ConfigurationModel):
    mg_type = models.CharField(max_length=30)  # 'global' | 'sectors' | 'systems_types' | 'systems_compositions'


class Statistic(GameModel):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    stats_category = models.CharField(max_length=100)
    stats = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['server', 'stats_category'], name='statistic_unique_on_server')]


class StartingValues(GameModel):
    server = models.ForeignKey(Server, on_delete=models.CASCADE)
    start_type = models.CharField(max_length=50)
    available_native_planets = models.JSONField(default=list)
    starting_resources = models.JSONField(default=dict)
    starting_capital = models.JSONField(default=dict)
    starting_territories = models.JSONField(default=dict)
    starting_modifiers = models.JSONField(default=dict)
    starting_factions = models.JSONField(default=dict)
    starting_technologies = models.JSONField(default=dict)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['server', 'start_type'], name='starting_values_unique_on_server')]
