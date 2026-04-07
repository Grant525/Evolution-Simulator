import random


class Tile:

    def __init__(self, environment):
        self.environment       = environment
        self.sunlight          = environment['sunlight']
        self.groundwater       = environment['groundwater']
        self.rainfall          = environment['rainfall']
        self.soil_quality      = environment['soil_quality']
        self.humidity          = environment['humidity']
        self.temperature       = environment['temperature']
        self.wind_speed        = environment['wind_speed']        # 0-1
        self.wind_direction    = environment['wind_direction']    # (dx, dy) unit vector e.g. (1, 0) = east
        self.distance_to_water = environment['distance_to_water']
        self.elevation         = environment['elevation']         # absolute height
        self.slope             = environment['slope']             # 0-1, how steep the tile is
        self.slope_direction   = environment['slope_direction']   # (dx, dy) unit vector pointing downhill
        self.is_water          = environment['is_water']          # True if river/lake tile
        self.plants            = []

    # Competition: taller neighbours cast shade on shorter ones
    def effective_sunlight_for(self, plant):
        tallest_neighbor = max(
            (p.potential_height for p in self.plants if p is not plant and p.alive),
            default=0
        )
        # Taller plants cast real shade — height difference matters a lot
        shade = max(0.0, tallest_neighbor - plant.potential_height) * 0.6
        return max(0.0, self.sunlight - shade)

    def calculate_groundwater(self):
        # Groundwater is higher closer to water sources; falls off with distance
        self.groundwater = 1.0 / (1.0 + self.distance_to_water)

    def recharge_groundwater(self):
        # Rainfall not absorbed by plants flows downhill and adds to groundwater
        alive_plants = [p for p in self.plants if p.alive]
        total_surface_roots = sum(1.0 - p.root_depth for p in alive_plants)
        absorbed = min(self.rainfall, total_surface_roots * self.rainfall)
        runoff = (self.rainfall - absorbed) * self.slope
        self.groundwater = min(1.0, self.groundwater + runoff * 0.1)

    def _depth_similarity(self, plant, other):
        # How much two plants compete — 1.0 if same depth, 0.0 if opposite extremes
        return 1.0 - abs(plant.root_depth - other.root_depth)

    def rainfall_for(self, plant):
        # Shallow roots capture rainfall; competition is strongest between plants at similar depth
        alive_plants = [p for p in self.plants if p.alive]
        own_claim = 1.0 - plant.root_depth
        competing_claim = sum(
            (1.0 - p.root_depth) * self._depth_similarity(plant, p)
            for p in alive_plants if p is not plant
        )
        total = own_claim + competing_claim or 1.0
        return self.rainfall * (own_claim / total)

    def groundwater_for(self, plant):
        # Deep roots access groundwater; competition strongest at similar depth
        alive_plants = [p for p in self.plants if p.alive]
        own_claim = plant.root_depth
        competing_claim = sum(
            p.root_depth * self._depth_similarity(plant, p)
            for p in alive_plants if p is not plant
        )
        total = own_claim + competing_claim or 1.0
        return self.groundwater * (own_claim / total)

    def nutrition_for(self, plant):
        # Nutrients distributed through soil layers; deeper roots access more,
        # competition strongest between plants at similar depth
        alive_plants = [p for p in self.plants if p.alive]
        own_claim = plant.root_depth
        competing_claim = sum(
            p.root_depth * self._depth_similarity(plant, p)
            for p in alive_plants if p is not plant
        )
        total = own_claim + competing_claim or 1.0
        return self.soil_quality * (own_claim / total)

    def step(self):
        for plant in self.plants:
            eff_sun = self.effective_sunlight_for(plant)
            plant.update(self, eff_sun)

        seeds = []
        for plant in self.plants:
            if plant.alive and plant.can_reproduce():
                for _ in range(max(1, round(plant.seed_distribution * 5))):
                    seeds.append((plant.reproduce(), plant.spread))

        self.plants = [p for p in self.plants if p.alive]
        return seeds


# ----------------------------------------------------------------------
# Seed dispersal
# ----------------------------------------------------------------------

def disperse_seed(seed, origin_x, origin_y, world):
    """
    Determines where a seed lands.
    - Small seeds (high seed_distribution): carried by wind AND water
    - Large seeds (low seed_distribution): water only
    - Default: lands on an adjacent tile
    world is a 2D list: world[x][y] = Tile
    Returns the landing Tile.
    """
    width, height = len(world), len(world[0])
    tile = world[origin_x][origin_y]

    # All seeds start at a random adjacent tile — minimum dispersal
    neighbors = _adjacent(origin_x, origin_y, width, height)
    x, y = random.choice(neighbors)

    # --- Wind dispersal (light/small seeds only) ---
    # seed_distribution > 0.5 = small enough to catch wind
    if seed.seed_distribution > 0.5 and tile.wind_speed > 0:
        wind_reach = tile.wind_speed * (seed.seed_distribution - 0.5) * 2  # 0-1
        steps = round(wind_reach * 6 * abs(random.gauss(1, 0.3)))          # up to ~6 tiles
        dx, dy = tile.wind_direction
        x += round(dx * steps)
        y += round(dy * steps)

    # --- Rainfall washes seeds downhill along slope ---
    if tile.rainfall > 0.3 and tile.slope > 0:
        steps = round(tile.slope * tile.rainfall * 3)  # steeper + more rain = further
        dx, dy = tile.slope_direction
        x += round(dx * steps)
        y += round(dy * steps)

    # Clamp to world bounds
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))

    # --- Water dispersal: seed entered a river/lake ---
    if world[x][y].is_water:
        x, y = _travel_downstream(x, y, world)

    # Final clamp
    x = max(0, min(x, width - 1))
    y = max(0, min(y, height - 1))

    return world[x][y]


def _adjacent(x, y, width, height):
    return [
        (x + dx, y + dy)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if 0 <= x + dx < width and 0 <= y + dy < height
    ]


def _travel_downstream(start_x, start_y, world):
    """
    Seed entered water — drifts downstream along slope_direction of water tiles.
    Exit probability starts low and rises each step so most seeds
    land close to where they entered the water.
    """
    width, height = len(world), len(world[0])
    x, y = start_x, start_y

    for step in range(30):  # max 30 tiles downstream
        # Exit chance rises each step — most seeds land close to entry point
        exit_chance = 0.2 + step * 0.06  # 20% at step 0, ~80% by step 10

        land_neighbors = [
            (x + dx, y + dy)
            for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
            if 0 <= x + dx < width and 0 <= y + dy < height
            and not world[x + dx][y + dy].is_water
        ]

        if land_neighbors and random.random() < exit_chance:
            return random.choice(land_neighbors)

        # Advance downstream along the water tile's slope direction
        nx = x + round(world[x][y].slope_direction[0])
        ny = y + round(world[x][y].slope_direction[1])

        if 0 <= nx < width and 0 <= ny < height and world[nx][ny].is_water:
            x, y = nx, ny
        else:
            break

    # End of river — exit to any adjacent land tile
    land_neighbors = [
        (x + dx, y + dy)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]
        if 0 <= x + dx < width and 0 <= y + dy < height
        and not world[x + dx][y + dy].is_water
    ]
    if land_neighbors:
        return random.choice(land_neighbors)

    return start_x, start_y
