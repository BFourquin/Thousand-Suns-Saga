from django import template
from django.utils.dateformat import format as format_date
from django.utils.html import format_html
from django.utils.translation import gettext as _

register = template.Library()

RP_YEARS_AHEAD = 1000


@register.filter(expects_localtime=True)
def rp_date(value):
    # The date of the universe of the game for what happens in it, the real one when hovering it
    if not value:
        return ''
    return format_html('<span title="{}">{}</span>', _("Date réelle : %s") % format_date(value, 'd/m/Y H:i'),
                       format_date(value, f'd/m/{value.year + RP_YEARS_AHEAD} H:i'))
