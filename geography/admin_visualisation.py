
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame
import random
import time
from pathlib import Path

from data import map_generator, sectors
#from settings import



def display_sectors(server, display_sector_types=True, auto_close_visualisation=False):

    # Server generation parameters
    mg_params = map_generator.get_map_generator_parameters(server, mg_type='global')
    #g_sector_params = map_generator.get_map_generator_parameters(server, mg_type='sector')

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
            if display_sector_types:
                pygame.draw.rect(screen, color, pygame.Rect(w*x, w*y, w, w))

            """
            # Random generation
            for _ in range(selected_sector['nb_systems']//10):
                screen.set_at((random.randint(w*x,w*x+w), random.randint(w*y,w*y+w)), (200,200,200))
            """

            for sy, sx in selected_sector['systems_coordinates']:
                star_color = random.randint(70, 240)
                screen.set_at((w*x + (sx*w)//100, y*w + (sy*w)//100), (star_color, star_color, star_color))

    # Update the display using flip
    pygame.display.flip()

    # Save as image
    Path("admin_web\\static\\images\\map\\"+server+'\\map\\').mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, "admin_web\\static\\images\\map\\" + server + "\\map.png")

    # Variable to keep our game loop running
    running = True

    # game loop
    while running:

        # for loop through the event queue
        for event in pygame.event.get():

            # On Click : display sectors types
            if event.type == pygame.MOUSEBUTTONDOWN or auto_close_visualisation:
                for y in range(mg_params['nb_sectors_axe_y']):
                    for x in range(mg_params['nb_sectors_axe_x']):
                        selected_sector = sectors.get_sector(server, y, x)

                        # Draw sector
                        color = eval('color_' + selected_sector['sector_type'])
                        pygame.draw.rect(screen, color, pygame.Rect(w * x, w * y, w, w))

                        # Draw systems
                        for sy, sx in selected_sector['systems_coordinates']:
                            star_color = random.randint(70, 240)
                            screen.set_at((w * x + (sx * w) // 100, y * w + (sy * w) // 100),
                                          (star_color, star_color, star_color))

                # Update the display using flip
                pygame.display.flip()

                # Save as image
                pygame.image.save(screen, "admin_web\\static\\images\\map\\" + server + "\\map_with_sectors.png")

                if auto_close_visualisation:
                    running = False
                    break

            # Check for QUIT event
            if event.type == pygame.QUIT:
                running = False

        time.sleep(0.5)


if __name__ == '__main__':
    display_sectors('Alpha', display_sector_types=False, auto_close_visualisation=True)
