
import random

from backend.utils import probability_picker


# Multiple stars system probability
nb_stars = {'1': 0.33,
            '2': 0.48,
            '3': 0.11,
            '4': 0.04,
            '5': 0.02,
            '6': 0.01,
            '7': 0.01}


star_type_real_distribution = {'D': 0.05,  # White dwarf
                               'M': 0.8,  # Red dwarf
                               'K': 0.08,  # Orange
                               'G': 0.35,  # Yellow
                               'F': 0.02,
                               'A': 0.07,
                               'B': 0.01,
                               'O': 0.00001,  # Blue giant
                               'supergiant': 0.0001,
                               'hypergiant': 0,

                               # Giants (end of life)
                               'G giant': 0.01,
                               'K giant': 0.01,
                               'M giant': 0.01,
                               }


total = {'1': 0, '2': 0, '3': 0, '4': 0, '5': 0, '6': 0, '7': 0}


random.seed(random.random())
for _ in range(200):
    total[str(probability_picker(nb_stars, _))] += 1

print(total)


