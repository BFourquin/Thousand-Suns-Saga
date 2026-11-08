
from django.utils.translation import gettext_lazy as _

# Visual themes selectable from the themes page, linked from the user account preferences.
# Each theme (except 'classic') has a stylesheet in admin_web/static/css/themes/theme_<id>.css

DEFAULT_THEME = 'atlas_console'

THEMES = {
    # id: (display name, short description, swatch colors [background, surface, accent])
    'atlas_console': (_('Saga Stellaire'),    _('Ivoire et or, police du HUD'),         ('#0e1624', '#16223a', '#c9a55c')),
    'classic':    (_('Première Saga'),        _('Interface de la pré-Alpha'),           ('#454d55', '#343a40', '#007bff')),
    'tactical':   (_('État-major'),           _('Salle de guerre, kaki et sable'),      ('#15170f', '#20231a', '#c7b14a')),
    'eclipse':    (_('Éclipse'),              _('Noir et blanc, sans couleur'),         ('#000000', '#0d0d0d', '#ededed')),
    'console':    (_('Console de commandement'), _('HUD holographique cyan / ambre'),   ('#070b14', '#0f1a2b', '#2de2e6')),
    'atlas':      (_('Atlas stellaire'),      _('Carte du ciel, ivoire et or'),         ('#0e1624', '#16223a', '#c9a55c')),
    'industrial': (_('Industriel'),           _('Graphite et orange sécurité'),         ('#16181d', '#20242b', '#ff6a1a')),
    'minimal':    (_('Minimaliste'),          _('Sombre épuré, accent indigo'),         ('#0b0b0f', '#14141a', '#7c6cff')),
    'nebula':     (_('Nébuleuse'),            _('Verre dépoli violet et magenta'),      ('#120a24', '#1e1238', '#c56cff')),
    'phosphor':   (_('Terminal phosphore'),   _('Écran cathodique vert, monospace'),    ('#030a05', '#07140b', '#39ff6e')),
    'retro':      (_('Cockpit rétro'),        _('Tableau de bord ambre et bakélite'),   ('#120c06', '#1e1509', '#ffa726')),
    'imperial':   (_('Pourpre impérial'),     _('Velours cramoisi et dorures'),         ('#16060a', '#240b12', '#e8b64c')),
    'solar':      (_('Éruption solaire'),     _('Braises et plasma orangé'),            ('#140805', '#22100a', '#ff7a18')),
    'abyss':      (_('Abysses'),              _('Grands fonds et bioluminescence'),     ('#021418', '#06252b', '#19e6b8')),
    'synthwave':  (_('Néon 1984'),            _('Violet nuit, rose et cyan fluo'),      ('#12062b', '#1c0b3f', '#ff2fa0')),
    'biomech':    (_('Biomécanique'),         _('Chitine sombre et vert acide'),        ('#0b0f08', '#141b0f', '#a4e021')),
    'contrast':   (_('Haut contraste'),       _('Noir, blanc et jaune, très lisible'),  ('#000000', '#1a1a1a', '#ffe600')),
    'polar':      (_('Station polaire'),      _('Clair, blanc glacier et bleu'),        ('#e9eff5', '#ffffff', '#0b6bcb')),
    'parchment':  (_('Chroniques'),           _('Clair, parchemin et encre sépia'),     ('#efe6d0', '#f8f1df', '#8a3b12')),
    'sfw':        (_('Safe For Work'),        _('Tout blanc, sans illustration'),       ('#ffffff', '#ffffff', '#444444')),
}

# The themes with a light background : the templates and AdminLTE must not use their dark variants
LIGHT_THEMES = {'polar', 'parchment', 'sfw'}


def is_valid_theme(theme):
    return theme in THEMES


def get_theme_or_default(theme):
    return theme if is_valid_theme(theme) else DEFAULT_THEME


def themes_for_template():
    return [{'id': theme_id, 'name': name, 'description': description, 'swatches': swatches}
            for theme_id, (name, description, swatches) in THEMES.items()]
