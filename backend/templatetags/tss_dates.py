from django import template
from django.utils.dateformat import format as format_date

register = template.Library()


@register.filter(expects_localtime=True)
def rp_date(value):
    # shortcut: shows the real date, until the rule of the date of the game is decided
    if not value:
        return ''
    return format_date(value, 'd/m/Y H:i')
