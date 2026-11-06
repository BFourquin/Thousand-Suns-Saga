from django.contrib.auth.models import User
from django.db import models
from django.db.models.functions import Lower
from django.forms.models import model_to_dict

from backend.models import GameModel, to_id
from database.schemas import current_server


# Tables present in the schema of each game server, see database/schemas.py


class Commandant(GameModel):
    # DO_NOTHING : Django can't follow a cascade into every schema, the database refuses to delete a user still playing
    user = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name='+')

    commandant_name = models.CharField(max_length=100)  # Unique on all the servers, see backend.CommandantAccount
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
        constraints = [models.UniqueConstraint(Lower('civilisation_name'), name='civilisation_name_unique')]

    def as_dict(self):
        return super().as_dict() | {'server': current_server(),
                                    'colonies': list(self.colonies.order_by('id').values_list('id', flat=True))}


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

    cycle_nb = models.IntegerField(unique=True)
    datetime_start = models.DateTimeField()
    datetime_end = models.DateTimeField(null=True, blank=True)
    datetime_planned_end = models.DateTimeField(null=True, blank=True)  # Long-term version : daily passing of cycles

    # Boardgame version : manual passing of cycles
    commandants_cycle_playing = models.ManyToManyField(Commandant, related_name='+')
    commandants_cycle_finished = models.ManyToManyField(Commandant, related_name='+')
    commandants_cycle_absent = models.ManyToManyField(Commandant, related_name='+')

    def as_dict(self):
        cycle = model_to_dict(self, exclude=self.COMMANDANTS_LISTS)
        for field in self.COMMANDANTS_LISTS:
            cycle[field] = sorted(getattr(self, field).values_list('id', flat=True))
        return cycle


########################################################################################################################
# FORUMS AND PRIVATE MESSAGES


class Forum(GameModel):
    # 'assembly', 'hrp' : one per server, created by the migrations, the second one only shown on the servers without
    # mandatory roleplay. 'player' (taverns), 'coalition' (always private) : managed by their owner.
    kind = models.CharField(max_length=10, default='player')
    name = models.CharField(max_length=60)
    description = models.TextField(blank=True)  # Text of ambiance displayed above the forum
    is_private = models.BooleanField(default=False)
    owner = models.ForeignKey(Commandant, on_delete=models.CASCADE, null=True, blank=True, related_name='+')

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower('name'), name='forum_name_unique'),
            models.UniqueConstraint(fields=['kind'], condition=models.Q(kind='assembly'), name='one_assembly_per_server'),
            models.UniqueConstraint(fields=['kind'], condition=models.Q(kind='hrp'), name='one_hrp_forum_per_server'),
        ]


class ForumMember(GameModel):
    forum = models.ForeignKey(Forum, on_delete=models.CASCADE, related_name='members')
    commandant = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='+')
    status = models.CharField(max_length=10)  # 'invited' | 'member' | 'banned'

    class Meta:
        constraints = [models.UniqueConstraint(fields=['forum', 'commandant'], name='forum_member_unique')]


class Topic(GameModel):
    title = models.CharField(max_length=150)
    last_post_date = models.DateTimeField()
    nb_views = models.IntegerField(default=0)  # Kept here : counting the TopicRead of each topic of a list would cost more
    forum = models.ForeignKey(Forum, on_delete=models.CASCADE, related_name='topics')
    # SET_NULL : a thread outlives one of its authors
    author = models.ForeignKey(Commandant, on_delete=models.SET_NULL, null=True, related_name='+')
    last_author = models.ForeignKey(Commandant, on_delete=models.SET_NULL, null=True, related_name='+')


class TopicRead(GameModel):
    # Where a commandant stopped reading a topic : it is unread as long as its last post is more recent
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='+')
    commandant = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='+')
    last_read_date = models.DateTimeField()
    viewed = models.BooleanField(default=False)  # Counted in Topic.nb_views

    class Meta:
        constraints = [models.UniqueConstraint(fields=['topic', 'commandant'], name='topic_read_unique')]


class ForumPost(GameModel):
    # Base of the messages of the forums and of the conversations
    body = models.TextField()
    datetime = models.DateTimeField()
    previous_versions = models.JSONField(default=list)  # [{'body': ..., 'replaced_at': ISO date}], the oldest first

    class Meta:
        abstract = True


class Post(ForumPost):
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='posts')
    author = models.ForeignKey(Commandant, on_delete=models.SET_NULL, null=True, related_name='+')


class PostVote(GameModel):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='votes')
    commandant = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='+')
    category = models.CharField(max_length=15)  # A key of data.forums.vote_categories

    class Meta:
        constraints = [models.UniqueConstraint(fields=['post', 'commandant'], name='post_vote_unique')]


class Conversation(GameModel):
    subject = models.CharField(max_length=150)
    last_message_date = models.DateTimeField()


class ConversationMember(GameModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='members')
    commandant = models.ForeignKey(Commandant, on_delete=models.CASCADE, related_name='+')
    has_unread = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)  # Removed from its list by this commandant, back at the next message

    class Meta:
        constraints = [models.UniqueConstraint(fields=['conversation', 'commandant'], name='conversation_member_unique')]


class ConversationMessage(ForumPost):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(Commandant, on_delete=models.SET_NULL, null=True, related_name='+')


class MessageFlag(GameModel):
    # A message reported to the team. What it says is copied : the flag outlives an edit or a deletion of the message.
    message_kind = models.CharField(max_length=15)  # 'post' | 'conversation'
    message_id = models.BigIntegerField()
    reporter = models.ForeignKey(Commandant, on_delete=models.SET_NULL, null=True, related_name='+')
    reason = models.TextField(blank=True)
    datetime = models.DateTimeField()
    author_name = models.CharField(max_length=100)
    location = models.CharField(max_length=300)
    body = models.TextField()
    previous_versions = models.JSONField(default=list)
    status = models.CharField(max_length=10, default='open', db_index=True)  # 'open' | 'closed'
    handled_by = models.CharField(max_length=150, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['message_kind', 'message_id', 'reporter'], name='message_flag_unique')]


########################################################################################################################
# GEOGRAPHY


class GeographyModel(GameModel):
    seed = models.CharField(max_length=18, unique=True)

    class Meta:
        abstract = True

    def as_dict(self):
        return {'id': self.seed} | model_to_dict(self, exclude=['id'])


class Sector(GeographyModel):
    pos_y = models.IntegerField()
    pos_x = models.IntegerField()
    sector_type = models.CharField(max_length=50, null=True, blank=True)
    nb_systems = models.IntegerField(null=True, blank=True)
    nb_natives_start = models.IntegerField(null=True, blank=True)
    systems_coordinates = models.JSONField(default=list)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['pos_y', 'pos_x'], name='sector_position_unique')]


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

    data = models.JSONField()

    class Meta:
        abstract = True

    def as_dict(self):
        return {'id': self.pk} | self.data


class NamedConfigurationModel(ConfigurationModel):
    internal_name = models.CharField(max_length=100, unique=True)

    class Meta:
        abstract = True


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
    stats_category = models.CharField(max_length=100, unique=True)
    stats = models.JSONField()


class StartingValues(GameModel):
    start_type = models.CharField(max_length=50, unique=True)
    available_native_planets = models.JSONField(default=list)
    starting_resources = models.JSONField(default=dict)
    starting_capital = models.JSONField(default=dict)
    starting_territories = models.JSONField(default=dict)
    starting_modifiers = models.JSONField(default=dict)
    starting_factions = models.JSONField(default=dict)
    starting_technologies = models.JSONField(default=dict)
