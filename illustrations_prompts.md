# Illustrations des bâtiments — prompts

Source : feuille `Buildings` de `TSS_boardgame.xlsx`.
Fichier de sortie : `admin_web/static/images/colony/building/<internal_name>.png`, carré 1024×1024 (comme les images existantes).

**Déjà faits** : `farm_hunting_range`, `farm_ancient`, `farm_ecologic`, `farm_ecologic_agriculture`, `farm_biodome`, `water_pumping_station`.

Légende : **[EXT]** vue extérieure · **[INT]** intérieur d'usine, avec le produit fabriqué bien visible.

---

## 1. Propositions de style

Chaque prompt de la section 2 décrit seulement le **sujet**. Ajoute ensuite le **suffixe** du style choisi.
Negative prompt commun (si l'outil le gère) :
`text, letters, logo, watermark, signature, cartoon, illustration, painting, 3d render, cgi, plastic look, blurry, distorted hands, extra limbs`

### Style A — « Photo documentaire » (dans la lignée des images existantes)
Lumière de jour neutre, sujet centré, rendu propre. C'est le plus cohérent avec `water_pumping_station` et `farm_biodome`.
> Suffixe : `photorealistic documentary photograph, shot on a full-frame camera with a 35mm lens, natural daylight, clear sky, sharp focus, high dynamic range, realistic materials and textures, centered composition, square format`

### Style B — « Cinématique Thousand Suns »
Même réalisme, mais ambiance de film de science-fiction : heure dorée, brume, et **toujours un ciel extraterrestre** (deux soleils ou planète à anneaux à l'horizon). Fait clairement comprendre qu'on est sur une colonie lointaine, même pour les bâtiments d'époque.
> Suffixe : `cinematic photorealistic film still, golden hour light from two suns low on the horizon, a huge ringed planet faintly visible in the sky, atmospheric haze, volumetric light, anamorphic lens, rich color grading, ultra detailed, square format`
> (Pour un [INT] : remplacer « two suns… sky » par `warm light shafts through high windows, dust in the air`.)

### Style C — « Archives de l'époque »
Le rendu photo suit l'âge technologique du bâtiment : photo d'archive sépia pour l'antique/1800s, Kodachrome pour 1920-1960, pellicule 70-80s, numérique moderne pour le futur. Donne une vraie sensation de progression dans l'arbre technologique.
> Suffixe selon l'ère :
> - Antique / pré-industriel : `photorealistic, as if photographed in the field by an archaeological expedition, warm sepia tones, soft natural light, fine film grain, square format`
> - Industriel (1850-1920) : `authentic glass-plate photograph, black and white, slight vignetting, fine grain, long exposure realism, square format`
> - Motorisé (1920-1970) : `authentic Kodachrome color photograph, slightly faded colors, period-accurate details, film grain, square format`
> - Pré-spatial (1970-2000) : `35mm color negative film photograph, 1980s look, natural colors, light grain, square format`
> - Spatial / futur : utiliser le suffixe du style A.

### Style D — « Concept art réaliste »
Plus éditorial : légère contre-plongée, échelle monumentale, petits personnages pour donner l'échelle. Moins « photo de catalogue », plus spectaculaire, mais reste photoréaliste.
> Suffixe : `hyperrealistic matte painting, epic sense of scale, low camera angle, tiny human figures for scale, dramatic overcast sky with sun breaking through, crisp details, photographic textures, square format`

### Démonstration sur 3 bâtiments
Les mêmes 3 sujets, à générer dans chaque style pour comparer :

| Bâtiment | Sujet (à combiner avec A, B, C ou D) |
|---|---|
| `ancient_stone_quarry` [EXT] | `An ancient open-air limestone quarry carved in stepped terraces, workers splitting huge blocks with wooden wedges and copper chisels, a massive block on a wooden sledge being hauled up an earthen ramp with ropes` |
| `automobile_workshop` [INT] | `Inside an early 1910s automobile workshop, craftsmen in overalls hand-assembling a brass-trimmed early motor car on wooden trestles, the car body and wooden-spoke wheels clearly visible in the foreground, tools on workbenches, leather belts driving machines` |
| `nuclear_power_plant` [EXT] | `A nuclear power plant on a wide river bank, two huge hyperbolic cooling towers releasing white steam, concrete reactor containment domes, high-voltage pylons leading away` |

Exemple complet (style C, ère motorisée, `automobile_workshop` → ère industrielle) :
`Inside an early 1910s automobile workshop, craftsmen in overalls hand-assembling a brass-trimmed early motor car on wooden trestles, ... , authentic glass-plate photograph, black and white, slight vignetting, fine grain, long exposure realism, square format`

---

## 2. Prompts par bâtiment

### Besoins vitaux — Nourriture

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `farm_pasture` | Pâturages | EXT | `Wide rolling green pastures with a herd of cattle and sheep grazing, dry-stone walls and wooden fences, a small stone shepherd's hut, light morning mist in the valley` |
| `farm_fertilized_fields` | Champs fertilisés | EXT | `Early 20th-century farmland with neat rows of young wheat, a horse-drawn fertilizer spreader in the middle of the field, burlap sacks of fertilizer stacked next to a red wooden barn` |
| `farm_mechanised_fields` | Champs mécanisés | EXT | `A 1950s combine harvester and two tractors harvesting a vast golden wheat field, a truck receiving grain, tall concrete grain silos in the background, dust in the air` |
| `farm_modern_agriculture` | Agriculture moderne | EXT | `A modern farm with center-pivot irrigation systems spraying circular green fields, a large GPS-guided tractor, metal grain bins and barns with solar panels on the roofs` |
| `farm_hydroponic` | Fermes hydroponiques | INT | `Inside a vertical hydroponic farm, towering racks of lettuce and herbs stacked ten levels high under pink and purple LED grow lights, white irrigation tubes, a technician in a white coat checking a tray of lettuce in the foreground` |
| `farm_intensive_agriculture` | Agriculture intensive | EXT | `High three-quarter view of an endless monoculture landscape, a sea of white plastic greenhouses next to perfectly straight crop fields reaching the horizon, crop-spraying drones flying above` |
| `farm_food_factory` | Usine alimentaire | INT | `Inside a food processing factory, a stainless steel conveyor line filling and sealing rows of tin cans of food rations, the cans clearly visible in the foreground, workers in white coats and hairnets` |
| `farm_food_industry` | Industrie alimentaire | INT | `A vast fully automated food plant, robotic arms packing nutrient bars into silver wrappers, dozens of parallel conveyor belts, spotless white hall, the nutrient bars sharp in the foreground` |
| `farm_alguae` | Bassins d'algoculture | EXT | `Rows of long open raceway ponds filled with bright green algae, paddle wheels churning the water, a coastal processing building with pipes and tanks, sea in the background` |
| `phytoplankton_basins` | Bassins de phytoplanctons | EXT | `A futuristic coastal facility with circular basins and walls of transparent tube photobioreactors glowing teal-green, dusk light, faint bioluminescence in the water` |

### Besoins vitaux — Eau et air

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `water_well` | Puit | EXT | `An ancient stone well with a wooden winch, rope and bucket in a dusty village square, clay water jars around it, mud-brick houses behind` |
| `water_cisterns` | Citernes | INT | `Inside a huge ancient underground cistern, rows of stone columns with arches reflecting in still dark water, warm light from openings in the vaulted ceiling` |
| `water_ice_cutter` | Coupeur de glace | EXT | `19th-century workers with long hand saws cutting large blocks of ice from a frozen lake, horse-drawn sleds loaded with ice blocks, a wooden ice house on the shore, snowy pine forest` |
| `water_mechanized_ice_cutter` | Coupeur de glace mécanisé | EXT | `A heavy tracked machine with a giant circular saw cutting cubic blocks out of a blue glacier, a crane loading the ice blocks onto large haul trucks, frozen barren landscape` |
| `water_condenser` | Condensateur d'eau | EXT | `A field of tall moisture-condenser towers and fine mesh fog collectors in an arid rocky desert, water droplets on the mesh, pipes leading to white storage tanks` |
| `water_asteroid_harvester` / `ice_asteroid_harvester` | Récolteur d'astéroïdes de glace | EXT (espace) | `A large mining spacecraft clamped onto an icy asteroid in orbit, drill arms cutting chunks of glittering ice, a cargo container being filled, a planet and stars in the background, hard sunlight` |
| `atmospheric_filters` | Filtres atmosphériques | EXT | `Massive cylindrical atmospheric filtration towers with giant intake fans pulling in yellowish polluted haze and releasing clean white vapor at the top, industrial complex on a hostile barren planet` |
| `electrolyzer` | Electrolyseur | INT | `Inside an industrial electrolysis hall, rows of transparent electrolysis cells with streams of gas bubbles rising through blue-lit water, thick pipes and gas tanks, technician monitoring a panel` |

> Note : `water_asteroid_harvester` et `ice_asteroid_harvester` ont le même nom FR dans l'Excel ; une seule image peut servir aux deux (ou c'est un doublon à nettoyer).

### Besoins vitaux — Équipement de survie

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `survival_toolmakers` | Artisans outilleurs | INT | `Inside a primitive hut workshop lit by a fire, artisans knapping flint blades, making bone needles and stitching leather waterskins, finished stone axes and tools laid out on hides in the foreground` |
| `survival_manufacture` | Manufacture d'équipement | INT | `Inside an 18th-century manufactory, rows of workers sewing canvas tents and leather boots at wooden benches, finished boots, tents and hand tools stacked in the foreground` |
| `survival_factory` | Usine d'équipement de survie | INT | `A 1950s factory assembly line producing gas masks and survival kits, rows of rubber gas masks with round glass eyepieces on the conveyor clearly visible, workers in overalls` |
| `survival_industry` | Industrie d'équipement de survie | INT | `A modern automated factory producing environmental suits, robotic arms fitting pressurized helmets onto white survival suits hanging on an overhead conveyor, the suits and helmets sharp in the foreground` |

### Biens de consommation

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `goods_artisans` | Artisans de marchandises | INT | `Inside a medieval artisan workshop, a potter at a wheel and a weaver at a wooden loom, shelves of finished pottery, baskets and folded cloth in the foreground` |
| `goods_manufacture` | Manufacture de marchandises | INT | `Inside a 19th-century textile mill, long rows of mechanical power looms driven by overhead shafts and leather belts, colorful bolts of fabric stacked in the foreground` |
| `goods_factory` | Usine de marchandises | INT | `A modern assembly line producing household appliances, rows of white washing machines and toasters moving along the conveyor, workers and robotic arms, the appliances clearly visible` |

### Santé et activités illicites

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `herbalist` | Herboriste | INT | `Inside a small stone cottage, bundles of dried herbs hanging from wooden beams, a mortar and pestle, clay pots of ointment and glass jars of seeds on a rough table` |
| `apothecary` | Apothicaire | INT | `An 18th-century apothecary shop, walls of small wooden drawers, painted porcelain jars, brass scales and glass flasks of colored tinctures on the counter` |
| `pharmacy` | Pharmacie | INT | `An early 20th-century pharmaceutical laboratory, a pharmacist operating a hand-cranked tablet press, trays of white pills, amber glass bottles lined up on shelves` |
| `pharmaceutical_factory` | Usine pharmaceutique | INT | `A pharmaceutical cleanroom with a blister-packing machine, thousands of colored capsules flowing into blister packs, operators in full white cleanroom suits` |
| `psychotropic_fields` | Champs de psychotropes | EXT | `Terraced fields of red poppies hidden in a remote jungle mountain valley, wooden drying sheds, a makeshift watchtower at the edge of the field, mist on the ridges` |
| `organ_harvesting_site` | Site de prélèvement d'organes | INT | `A grim clandestine medical facility in a concrete basement, an empty steel operating table under a harsh surgical lamp, rows of medical transport coolers, flickering fluorescent light, no people, no blood` |
| `slaver_expedition` | Expédition esclavagiste | EXT | `A convoy of armored off-road trucks towing empty barred cargo cages across a dusty alien plain, armed mercenaries in rugged gear standing by the vehicles, ominous overcast sky` |

### Construction

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `ancient_stone_quarry` | Carrière ancienne de pierre | EXT | `An ancient open-air limestone quarry carved in stepped terraces, workers splitting huge blocks with wooden wedges and copper chisels, a massive block on a wooden sledge being hauled up an earthen ramp with ropes` |
| `brickworks` | Briquetterie | EXT | `A 19th-century brickworks with a tall brick chimney and round beehive kilns, long stacks of red bricks drying in the sun, wheelbarrows and a clay pit` |
| `cement_factory` | Cimenterie | EXT | `A cement plant with a long rotating kiln, a tall preheater tower, grey concrete silos and conveyor belts, a fine layer of grey dust over everything` |

### Véhicules

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `automobile_workshop` | Atelier automobile | INT | `Inside an early 1910s automobile workshop, craftsmen in overalls hand-assembling a brass-trimmed early motor car on wooden trestles, the car body and wooden-spoke wheels clearly visible in the foreground, tools on workbenches` |
| `ancient_automobile_factory` | Usine ancienne d'automobile | INT | `A 1920s moving assembly line, a long row of identical boxy black sedans in various stages of assembly, workers fitting wheels and bodies, overhead chains and pulleys` |
| `sailing_shipyard` | Chantier naval à voile | EXT | `A wooden three-masted ship hull on a slipway surrounded by scaffolding, shipwrights shaping oak timbers, piles of planks and coiled ropes, harbor in the background` |
| `steam_shipyard` | Chantier naval à vapeur | EXT | `A riveted steel steamship hull with tall funnels in a dry dock, giant gantry cranes overhead, coal smoke, workers on scaffolding, industrial harbor` |
| `train_workshop` | Atelier de trains | INT | `Inside a locomotive erecting shop, a black steam locomotive lifted by overhead cranes above its driving wheels, mechanics working on the boiler, rails on the floor` |
| `airship_workshop` | Atelier de dirigeables | INT | `Inside a gigantic hangar, the skeleton of a rigid airship made of aluminum girders, workers on scaffolding stretching silver fabric over the frame, tiny figures for scale` |
| `aircraft_workshop` | Atelier d'aéronef | INT | `A 1940s aircraft factory, a line of polished aluminum propeller fighter planes in assembly, riveters working on the fuselages, propellers and wings stacked nearby` |
| `aeronautical_workshop` | Atelier aéronautique | INT | `A modern aircraft final assembly hall, a large white jet airliner fuselage with its wings being joined, work platforms and yellow tooling around it, bright clean hall` |
| `tractor_workshop` | Atelier de tracteurs | INT | `A factory line assembling bright orange farm tractors, large rear tires being mounted, a row of finished tractors at the end of the line` |

### Aérospatial

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `pioneer_space_program` | Programme spatial pionnier | EXT | `A 1960s rocket launch pad on a flat coastline, an early white and black rocket standing next to its steel service gantry, a concrete blockhouse and fuel tanks nearby` |
| `rocket_workshop` | Atelier de fusée | INT | `Inside a towering vertical assembly building, a huge white rocket stage being stacked by a crane, engineers on multi-level work platforms, rocket engines visible at the base` |

### Mécanique

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `mechanical_workshop` | Atelier mécanique | INT | `A mechanical workshop with engine blocks on stands, gears and crankshafts on workbenches, mechanics working at a lathe, oil-stained concrete floor` |
| `machine_tool_workshop` | Atelier de machine-outils | INT | `A heavy industry hall where large lathes and milling machines are being built, half-assembled cast-iron machine tools lined up, an overhead crane lifting a machine bed` |

### Énergie

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `coal_mine` | Houillère | EXT | `A coal mine pithead with a tall steel headframe and winding wheel, black slag heaps, mine carts full of coal on rails, brick buildings` |
| `coal_power_plant` | Centrale à charbon | EXT | `A coal-fired power station with tall brick chimneys releasing dark smoke, huge coal piles, conveyor belts, cooling towers in the background` |
| `oil_well` | Puits de pétrole | EXT | `A field of oil pumpjacks and old wooden oil derricks on a flat prairie, storage tanks, pipelines, sunset sky` |
| `fuel_power_plant` | Centrale à fuel | EXT | `An oil-fired power plant on a harbor, large round fuel storage tanks, a tall smokestack, a tanker ship unloading at the pier` |
| `uranium_mine` | Mine d'uranium | EXT | `A large open-pit uranium mine in ochre and yellow rock, haul trucks on the terraced roads, a processing mill with yellow drums and radiation trefoil symbols` |
| `calutrons` | Calutrons | INT | `A 1940s hall of racetrack-shaped calutrons, giant curved electromagnets in an oval arrangement, operators seated at control panels with dials, period lighting` |
| `nuclear_program` | Programme nucléaire | EXT | `A secret 1950s nuclear research complex in the desert, barbed-wire fences, a reactor dome, laboratory buildings and a steel test tower in the distance` |
| `centrifuges` | Centrifugeuses | INT | `A vast enrichment hall with thousands of tall aluminum gas centrifuges standing in perfect rows, connected by thin pipes, a technician walking between them` |
| `nuclear_power_plant` | Centrale nucléaire | EXT | `A nuclear power plant on a wide river bank, two huge hyperbolic cooling towers releasing white steam, concrete reactor containment domes, high-voltage pylons leading away` |

### Mines

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `ancient_copper_mine` | Mine ancienne de cuivre | EXT | `A Bronze Age copper mine in a rocky hillside with green malachite veins, miners breaking rock with stone hammers and fire-setting, a small clay smelting furnace smoking` |
| `ancient_iron_mine` | Mine ancienne de fer | EXT | `A medieval iron mine entrance in a reddish hillside with timber supports, ore carts on wooden rails, a bloomery furnace and charcoal stacks nearby` |
| `mechanized_iron_mine` | Mine mécanisée de fer | EXT | `A gigantic open-pit iron ore mine with deep red terraces, huge haul trucks and an electric excavator loading ore, dust in the air` |
| `mechanized_alumina_mine` | Mine mécanisée d'alumine | EXT | `A bauxite open-pit mine with vivid red-orange earth, long conveyor belts leading to an alumina refinery with tall digesters and red mud ponds` |

### Informatique

| internal_name | Nom | Vue | Prompt (sujet) |
|---|---|---|---|
| `mechanical_computer_workshop` | Atelier de calculateurs mécaniques | INT | `A 19th-century workshop where craftsmen assemble a large brass mechanical calculating engine made of hundreds of gears and columns of numbered wheels, the machine clearly visible on the workbench` |
| `ancient_electronic_foundry` | Fonderie électronique ancienne | INT | `A 1960s semiconductor fabrication room, technicians in white gowns at microscopes, trays of early silicon wafers and vacuum tubes on the benches, yellow safety lighting` |
| `supercomputer_workshop` | Atelier de supercalculateurs | INT | `A 1970s lab assembling a cylindrical C-shaped supercomputer with colorful padded bench around its base, technicians routing dense bundles of wires inside the open towers` |
| `ancient_computer_factory` | Usine ancienne d'informatique | INT | `A 1980s factory assembly line producing beige personal computers and bulky CRT monitors, rows of computers with their cases open on the conveyor, workers in light blue smocks` |
