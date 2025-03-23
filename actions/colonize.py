
from data import colonies, districts, coordinates, starting_values


def check_if_colonisable(commandant, coordinate_seed):

    # TODO check if habitable
    # TODO check the planet is not contested by a strong revendication

    return True


def colonize(server, commandant_id, fleet_id, coordinate_seed, colony_type, central_district_type, colony_name=None, admin_force_action=False):

    if not admin_force_action:  # Bypass checks and needing a colonizer ship if admin action

        if not check_if_colonisable(commandant_id, coordinate_seed):
            return 'Planet is not colonisable'  # TODO translation

        # TODO check the fleet has a colonizer ship
        # TODO remove the colonizer ship

    # Keep planet name if no colony name specified
    if colony_name is None:
        colony_name = coordinates.get_coordinate(server, coordinate_seed)['name']


    colonies.new_colony(server, commandant_id, colony_name, coordinate_seed, colony_type,
                        central_district_type=central_district_type)
    starting_values.remove_available_native_planets(server, coordinate_seed)


