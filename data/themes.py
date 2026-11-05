
# Visual themes selectable from the user account preferences.
# Each theme (except 'classic') has a stylesheet in admin_web/static/css/themes/theme_<id>.css

DEFAULT_THEME = 'classic'

THEMES = {
    # id: (display name, short description, swatch colors [background, surface, accent])
    'classic':    ('Classique',            'AdminLTE standard',                   ('#454d55', '#343a40', '#007bff')),
    'console':    ('Console de commandement', 'HUD holographique cyan / ambre',   ('#070b14', '#0f1a2b', '#2de2e6')),
    'atlas':      ('Atlas stellaire',      'Carte du ciel, ivoire et or',         ('#0e1624', '#16223a', '#c9a55c')),
    'industrial': ('Industriel',           'Graphite et orange sécurité',         ('#16181d', '#20242b', '#ff6a1a')),
    'minimal':    ('Minimaliste',          'Sombre épuré, accent indigo',         ('#0b0b0f', '#14141a', '#7c6cff')),
}


def is_valid_theme(theme):
    return theme in THEMES


def get_theme_or_default(theme):
    return theme if is_valid_theme(theme) else DEFAULT_THEME


def themes_for_template():
    return [{'id': theme_id, 'name': name, 'description': description, 'swatches': swatches}
            for theme_id, (name, description, swatches) in THEMES.items()]
