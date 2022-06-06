
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import random

from data import map_generator, sectors


def display_sector():

    # Define the background colour
    # using RGB color coding.
    background_colour = (0, 0, 0)

    # Define the dimensions of
    # screen object(width,height)
    screen = pygame.display.set_mode((800, 800))

    # Fill the background colour to the screen
    screen.fill(background_colour)

    for _ in range(150):
        screen.set_at((random.randint(40,760), random.randint(40,760)), (200,200,200))

    # Update the display using flip
    pygame.display.flip()

    # Variable to keep our game loop running
    running = True

    # game loop
    while running:

        # for loop through the event queue
        for event in pygame.event.get():

            # Check for QUIT event
            if event.type == pygame.QUIT:
                running = False


#display_sector()


def display_sectors(server='Alpha'):

    # Server generation parameters
    mg_params = map_generator.get_map_generator_parameters(server, mg_type='global')
    mg_sector_params = map_generator.get_map_generator_parameters(server, mg_type='sector')

    w = 100  # width per sector

    # Sector colors
    color_standard = (30, 30, 30)
    color_native = (20, 20, 50)
    color_wilderness = (20, 50, 20)
    color_void_centered = (20, 20, 10)
    color_cluster = (30, 10, 10)
    color_border = (10, 10, 10)
    color_corner = (5, 5, 5)
    color_empty = (10, 10, 10)

    # Define the dimensions of
    # screen object(width,height)
    screen = pygame.display.set_mode((w * mg_params['nb_sectors_axe_x'], w * mg_params['nb_sectors_axe_y']))

    # Fill the background colour to the screen
    screen.fill((0, 0, 0))

    for y in range(mg_params['nb_sectors_axe_y']):
        for x in range(mg_params['nb_sectors_axe_x']):

            selected_sector = sectors.get_sector(server, y, x)

            color = eval('color_'+selected_sector['sector_type'])
            pygame.draw.rect(screen, color, pygame.Rect(w*x, w*y, w, w))

            """
            # Random generation
            for _ in range(selected_sector['nb_systems']//10):
                screen.set_at((random.randint(w*x,w*x+w), random.randint(w*y,w*y+w)), (200,200,200))
            """

            for sy, sx in selected_sector['systems_coordinates']:
                screen.set_at((w*x + (sx*w)//100, y*w + (sy*w)//100), (200,200,200))

    # Update the display using flip
    pygame.display.flip()

    # Variable to keep our game loop running
    running = True

    # game loop
    while running:

        # for loop through the event queue
        for event in pygame.event.get():

            # Check for QUIT event
            if event.type == pygame.QUIT:
                running = False


if __name__ == '__main__':
    display_sectors()