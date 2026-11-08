from django import template

from data.locations import readable

register = template.Library()


@register.filter
def place(seed):
    # {{ seed|place }} : C6-12.55-3 instead of the 18 digits of a seed, see data.locations
    return readable(seed)
