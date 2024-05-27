
from data import colony


def check_if_colonisable(commandant, planet_id):

    # TODO check if habitable
    # TODO check the planet is not contested by a strong revendication

    return True


def colonize(server, commandant, fleet_id, coordinate, colony_name, colony_type, admin_force_action=False):

    if not admin_force_action:  # Bypass checks and needing a colonizer ship if admin action

        if not check_if_colonisable(commandant, coordinate):
            return 'Planet is not colonisable'  # TODO translation

    # TODO check the fleet has a colonizer ship
    # TODO remove the colonizer ship

    new_colony = {
        'name': colony_name,
        'owner': commandant['_id'],
        'controller': commandant['_id'],
        'coordinate': coordinate['_id'],
        'districts': [],
        'colony_type': colony_type,  # TODO more types
    }

    # TODO add districts and buildings according to colony type, planet biome and colonizing ship modules

    colony.set_colony(server, new_colony)



