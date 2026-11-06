from django.db.models import F
from django.utils.translation import gettext as _, gettext_lazy

from backend.utils import info_from_seed
from database.schemas import on_server
from data.names import localized_name
from game.models import District, Modifier, Resource


SCOPES = {
    'coordinate': {'name': gettext_lazy("Coordonnée"), 'icon': 'fa-location-dot'},
    'district': {'name': gettext_lazy("District"), 'icon': 'fa-city'},
    'system': {'name': gettext_lazy("Système"), 'icon': 'fa-sun'},
    'commandant': {'name': gettext_lazy("Commandant"), 'icon': 'fa-flag'},
    'quadrant': {'name': gettext_lazy("Quadrant"), 'icon': 'fa-table-cells-large'},
    'sector': {'name': gettext_lazy("Secteur"), 'icon': 'fa-border-all'},
}

CATEGORIES = {
    'economic': {'name': gettext_lazy("Économique"), 'icon': 'fa-coins'},
    'military': {'name': gettext_lazy("Militaire"), 'icon': 'fa-person-rifle'},
    'other': {'name': gettext_lazy("Autre"), 'icon': 'fa-shapes'},
}

STATS = {'production': gettext_lazy("Production")}

# 'duration' : in cycles, None if permanent. 'decreasing' : the effects fade until the last cycle, else they stay fixed.
# 'effects' : 'percent' or 'flat' (per building), on all the resources or on the one of 'resource'. Negative for a malus.
MODIFIER_TYPES = {
    'colonial_optimism': {
        'name_fr': "Optimisme colonial",
        'name_en': "Colonial optimism",
        'description_fr': "Les colons d'une terre nouvelle travaillent avec un entrain que le temps finit par user.",
        'description_en': "The settlers of a new land work with an enthusiasm that time ends up wearing down.",
        'categories': ['economic'],
        'duration': 10,
        'decreasing': True,
        'effects': [{'stat': 'production', 'percent': 10}],
    },
}


########################################################################################################################
# WHAT A MODIFIER CAN TARGET


def quadrant_of(coordinate):
    # A sector measures 100 x 100 : its quadrants are its 4 quarters
    infos = info_from_seed(coordinate)
    return f"{infos['sector_id']}:{int(infos['pos_y']) // 50}{int(infos['pos_x']) // 50}"


def commandant_target(commandant_id):
    return {('commandant', str(commandant_id)): _("Tout votre empire")}


def district_targets(district):
    # Everything a district belongs to : {(scope, target): displayed name}
    colony, coordinate = district.colony.name, district.colony.coordinate
    infos = info_from_seed(coordinate)
    return {
        ('district', str(district.id)): _("District de %(colony)s") % {'colony': colony},
        ('coordinate', coordinate): colony,
        ('system', infos['system_id']): _("Système de %(colony)s") % {'colony': colony},
        ('quadrant', quadrant_of(coordinate)): _("Quadrant de %(colony)s") % {'colony': colony},
        ('sector', infos['sector_id']): _("Secteur de %(colony)s") % {'colony': colony},
    }


########################################################################################################################


@on_server
def add_modifier(server, modifier_type, scope, target):
    duration = MODIFIER_TYPES[modifier_type]['duration']
    return Modifier.objects.create(modifier_type=modifier_type, scope=scope, target=str(target), duration=duration, cycles_left=duration)


@on_server
def active_modifiers(server, targets):
    rows = Modifier.objects.filter(target__in={target for _scope, target in targets}, modifier_type__in=MODIFIER_TYPES).order_by('id')
    return [modifier for modifier in rows if (modifier.scope, modifier.target) in targets]


@on_server
def tick_modifiers(server):
    # At the end of a cycle, after they were applied a last time
    Modifier.objects.exclude(cycles_left=None).update(cycles_left=F('cycles_left') - 1)
    Modifier.objects.filter(cycles_left__lte=0).delete()


def _strength(modifier):
    # 1 during the first cycle, then each cycle takes away the same part
    return modifier.cycles_left / modifier.duration if MODIFIER_TYPES[modifier.modifier_type]['decreasing'] and modifier.duration else 1


def modified_production(modifiers, targets, resource, quantity):
    flat, percent = 0, 0

    for modifier in modifiers:
        if (modifier.scope, modifier.target) in targets:
            strength = _strength(modifier)
            for effect in MODIFIER_TYPES[modifier.modifier_type]['effects']:
                if effect['stat'] == 'production' and effect.get('resource') in (None, resource):
                    flat += effect.get('flat', 0) * strength
                    percent += effect.get('percent', 0) * strength

    return max(0, (quantity + flat) * (1 + percent / 100))


########################################################################################################################
# MODIFIERS PAGE


def _effect_label(effect, strength, resources, language):
    value = effect.get('percent', effect.get('flat', 0)) * strength
    label = f"{value:+.3g}{' %' if 'percent' in effect else ''} {STATS[effect['stat']]}"
    if effect.get('resource'):
        label += ' : ' + localized_name(resources[effect['resource']], language)
    return label


@on_server
def modifiers_of_commandant(server, commandant_id, language):
    # All that touches the empire of this commandant, on it or on any place where it has a colony

    targets = commandant_target(commandant_id)
    for district in District.objects.filter(colony__controller=commandant_id).select_related('colony'):
        targets |= district_targets(district)

    resources = {resource.internal_name: resource.data for resource in Resource.objects.all()}
    modifiers = []

    for modifier in active_modifiers(server, targets):
        modifier_type = MODIFIER_TYPES[modifier.modifier_type]
        strength = _strength(modifier)
        values = [effect.get('percent', effect.get('flat', 0)) for effect in modifier_type['effects']]

        modifiers.append({
            'name': localized_name(modifier_type, language),
            'description': modifier_type.get('description_' + language) or modifier_type['description_fr'],
            'scope': modifier.scope,
            'scope_name': SCOPES[modifier.scope]['name'],
            'target_name': targets[(modifier.scope, modifier.target)],
            'categories': modifier_type['categories'],
            'categories_names': [CATEGORIES[category]['name'] for category in modifier_type['categories']],
            'signs': ['positive'] * any(value > 0 for value in values) + ['negative'] * any(value < 0 for value in values),
            'effects': [{'label': _effect_label(effect, strength, resources, language), 'positive': value > 0}
                        for effect, value in zip(modifier_type['effects'], values)],
            'cycles_left': modifier.cycles_left,
            'decreasing': modifier_type['decreasing'],
        })

    return modifiers
