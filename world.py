import random
from noise import pnoise2
from environment import Tile, disperse_seed
from plants import Plant

def _noise(x, y, scale, offset_x=0, offset_y=0, octaves=4):
    """Returns a 0-1 value from Perlin noise at (x, y)."""
    raw = pnoise2((x + offset_x) * scale, (y + offset_y) * scale, octaves=octaves)
    return (raw + 1) / 2  # remap from [-1, 1] to [0, 1]


class World:

    def __init__(self, width, height):
        self.width       = width
        self.height      = height
        self.tick_count  = 0
        self._next_id    = 0
        self.registry    = {}   # plant_id -> snapshot dict
        self.children_of = {}   # plant_id -> [child_ids]
        self.grid        = self._generate(width, height)   # grid[x][y] = Tile

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def _register(self, plant, tile_x, tile_y):
        pid = self._next_id
        self._next_id += 1
        plant.plant_id = pid

        self.registry[pid] = {
            "id":         pid,
            "parent_id":  plant.parent_id,
            "born_tick":  self.tick_count,
            "died_tick":  None,
            "birth_tile": (tile_x, tile_y),
            "traits":     {k: round(v, 3) for k, v in plant.genome.items()},
        }

        # Register this plant as a child of its parent
        if plant.parent_id is not None:
            self.children_of.setdefault(plant.parent_id, []).append(pid)
        self.children_of.setdefault(pid, [])

    def lineage(self, plant_id):
        """Returns ancestors (oldest first) and children of a plant."""
        if plant_id not in self.registry:
            return None

        # Walk up the ancestor chain
        ancestors = []
        pid = self.registry[plant_id]["parent_id"]
        while pid is not None and pid in self.registry:
            ancestors.insert(0, self.registry[pid])
            pid = self.registry[pid]["parent_id"]

        children = [
            self.registry[cid]
            for cid in self.children_of.get(plant_id, [])
            if cid in self.registry
        ]

        return {
            "plant":     self.registry[plant_id],
            "ancestors": ancestors,
            "children":  children,
        }

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _generate(self, width, height):
        # Each layer gets a random offset so they're independent of each other
        ox = [random.uniform(0, 1000) for _ in range(8)]
        oy = [random.uniform(0, 1000) for _ in range(8)]
        scale = 0.08  # lower = larger, smoother regions

        grid = []
        for x in range(width):
            col = []
            for y in range(height):
                elevation   = _noise(x, y, scale,        ox[0], oy[0])
                temperature = _noise(x, y, scale * 0.7,  ox[1], oy[1])
                rainfall    = _noise(x, y, scale * 0.9,  ox[2], oy[2])
                soil_quality = _noise(x, y, scale * 1.2, ox[3], oy[3])
                humidity    = _noise(x, y, scale * 0.8,  ox[4], oy[4])
                wind_speed  = _noise(x, y, scale * 1.5,  ox[5], oy[5]) * 0.6
                sunlight    = max(0.3, 1.0 - rainfall * 0.5)  # cloudier = more rain, less sun

                # High elevation = colder, drier, windier
                temperature = max(0.0, temperature - elevation * 0.4)
                rainfall    = max(0.0, rainfall    - elevation * 0.3)
                humidity    = max(0.0, humidity    - elevation * 0.2)

                is_water = False  # rivers carved separately in _carve_rivers

                # Slope: magnitude and direction derived from elevation gradient
                # (computed after all tiles exist; placeholder for now)
                slope           = 0.0
                slope_direction = (0, 1)

                env = {
                    "sunlight":          round(sunlight,     2),
                    "groundwater":       0.0,
                    "rainfall":          round(rainfall,     2),
                    "soil_quality":      round(soil_quality, 2),
                    "humidity":          round(humidity,     2),
                    "temperature":       round(temperature,  2),
                    "wind_speed":        round(wind_speed,   2),
                    "wind_direction":    random.choice([(1,0),(-1,0),(0,1),(0,-1)]),
                    "elevation":         round(elevation,    2),
                    "slope":             slope,
                    "slope_direction":   slope_direction,
                    "distance_to_water": 0.0,
                    "is_water":          is_water,
                }
                tile   = Tile(env)
                tile.x = x
                tile.y = y
                if not is_water and random.random() < 0.2:
                    genome = {
                        'potential_height':       random.uniform(0.2, 0.8),
                        'growth_speed':           random.uniform(0.1, 0.7),
                        'lifespan':               random.uniform(0.3, 0.9),
                        'spread':                 random.uniform(0.1, 0.6),
                        'root_depth':             random.uniform(0.1, 0.9),
                        'seed_distribution':      random.uniform(0.1, 0.9),
                        'reproduction_time':      random.uniform(0.2, 0.8),
                        'sun_need':               random.uniform(0.2, 0.8),
                        'nutrition_need':         random.uniform(0.1, 0.7),
                        'water_need':             random.uniform(0.1, 0.7),
                        'toughness':              random.uniform(0.1, 0.7),
                        'toxicity':               random.uniform(0.0, 0.5),
                        'thorniness':             random.uniform(0.0, 0.5),
                        'energy_storage':         random.uniform(0.3, 0.9),
                        'seed_hardiness':         random.uniform(0.1, 0.7),
                        'leaf_size':              random.uniform(0.2, 0.8),
                        'best_temperature':       random.uniform(0.2, 0.8),
                        'temperature_resilience': random.uniform(0.1, 0.5),
                        'maturity_age':           random.uniform(0.1, 0.6),
                    }
                    p = Plant(genome)
                    tile.plants.append(p)
                    self._register(p, x, y)
                col.append(tile)
            grid.append(col)

        self._calculate_slopes(grid, width, height)
        self._carve_rivers(grid, width, height, num_rivers=6)
        self._calculate_distances(grid, width, height)
        self._calculate_groundwater(grid, width, height)
        return grid

    def _carve_rivers(self, grid, width, height, num_rivers=6):
        """Start rivers from high elevation points and flow downhill to the map edge."""
        # Pick starting tiles from the top 20% elevation
        all_tiles = [(x, y) for x in range(width) for y in range(height)]
        all_tiles.sort(key=lambda t: grid[t[0]][t[1]].elevation, reverse=True)
        top_tiles = all_tiles[:max(1, len(all_tiles) // 5)]

        starts = random.sample(top_tiles, min(num_rivers, len(top_tiles)))

        for sx, sy in starts:
            x, y = sx, sy
            visited = set()
            for _ in range(width + height):  # max river length
                grid[x][y].is_water = True
                visited.add((x, y))

                # Move to the lowest unvisited neighbor
                neighbors = [
                    (x + dx, y + dy)
                    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]
                    if 0 <= x + dx < width and 0 <= y + dy < height
                    and (x + dx, y + dy) not in visited
                ]
                if not neighbors:
                    break

                nx, ny = min(neighbors, key=lambda t: grid[t[0]][t[1]].elevation)

                # Stop if we've reached the map edge
                if nx == 0 or nx == width-1 or ny == 0 or ny == height-1:
                    grid[nx][ny].is_water = True
                    break

                x, y = nx, ny

    def _calculate_slopes(self, grid, width, height):
        """Set each tile's slope and slope_direction from elevation differences."""
        for x in range(width):
            for y in range(height):
                tile = grid[x][y]
                neighbors = [
                    (x + dx, y + dy, dx, dy)
                    for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]
                    if 0 <= x + dx < width and 0 <= y + dy < height
                ]
                if not neighbors:
                    continue
                # Find steepest downhill neighbor
                steepest = min(neighbors, key=lambda n: grid[n[0]][n[1]].elevation)
                nx, ny, dx, dy = steepest
                drop = tile.elevation - grid[nx][ny].elevation
                tile.slope           = max(0.0, round(drop * 5, 2))  # scale drop to 0-1 range
                tile.slope_direction = (dx, dy) if drop > 0 else (0, 0)

    def _calculate_distances(self, grid, width, height):
        """BFS from every water tile to set distance_to_water on all tiles."""
        from collections import deque
        queue = deque()

        for x in range(width):
            for y in range(height):
                if grid[x][y].is_water:
                    grid[x][y].distance_to_water = 0
                    queue.append((x, y))
                else:
                    grid[x][y].distance_to_water = float('inf')

        while queue:
            x, y = queue.popleft()
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    new_dist = grid[x][y].distance_to_water + 1
                    if new_dist < grid[nx][ny].distance_to_water:
                        grid[nx][ny].distance_to_water = new_dist
                        queue.append((nx, ny))

    def _calculate_groundwater(self, grid, width, height):
        for x in range(width):
            for y in range(height):
                grid[x][y].calculate_groundwater()

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick(self):
        self.tick_count += 1
        seeds = []   # [(Plant, origin_x, origin_y)]

        # Step every tile — updates plants and collects seeds
        for x in range(self.width):
            for y in range(self.height):
                tile = self.grid[x][y]
                alive_before = {p.plant_id for p in tile.plants if p.alive}
                tile_seeds = tile.step()
                for seed, spread in tile_seeds:
                    seeds.append((seed, x, y))

                # Record death tick for any plants that just died
                for p in tile.plants:
                    if not p.alive and p.plant_id in alive_before and p.plant_id in self.registry:
                        self.registry[p.plant_id]["died_tick"] = self.tick_count

        # Recharge groundwater from rainfall runoff
        for x in range(self.width):
            for y in range(self.height):
                self.grid[x][y].recharge_groundwater()

        # Disperse, sprout, and register new plants
        for seed, origin_x, origin_y in seeds:
            landing_tile = disperse_seed(seed, origin_x, origin_y, self.grid)
            if random.random() < seed.sprout_chance(landing_tile):
                landing_tile.plants.append(seed)
                self._register(seed, landing_tile.x, landing_tile.y)

    # ------------------------------------------------------------------
    # Serialisation — called by the server to send state to the frontend
    # ------------------------------------------------------------------

    def stats(self):
        all_plants = [
            p for x in range(self.width)
              for y in range(self.height)
              for p in self.grid[x][y].plants
              if p.alive
        ]
        n = len(all_plants)
        if n == 0:
            return {"total_plants": 0, "tick": self.tick_count}

        def avg(attr):
            return round(sum(getattr(p, attr) for p in all_plants) / n, 3)

        def mn(attr):
            return round(min(getattr(p, attr) for p in all_plants), 3)

        def mx(attr):
            return round(max(getattr(p, attr) for p in all_plants), 3)

        mature_count = sum(1 for p in all_plants if p.is_mature)

        return {
            "tick":            self.tick_count,
            "total_plants":    n,
            "mature_plants":   mature_count,

            # Runtime state
            "avg_health":      avg("health"),  "min_health":  mn("health"),
            "avg_age":         round(sum(p.age for p in all_plants) / n, 1),
            "max_age":         max(p.age for p in all_plants),
            "avg_energy":      round(sum(p.energy for p in all_plants) / n, 1),

            # Growth / structure
            "avg_height":      avg("potential_height"),  "min_height": mn("potential_height"), "max_height": mx("potential_height"),
            "avg_leaf_size":   avg("leaf_size"),          "min_leaf":   mn("leaf_size"),        "max_leaf":   mx("leaf_size"),
            "avg_growth_speed":avg("growth_speed"),
            "avg_maturity_age":avg("maturity_age"),
            "avg_lifespan":    avg("lifespan"),

            # Resources
            "avg_water_need":  avg("water_need"),   "min_water": mn("water_need"),  "max_water": mx("water_need"),
            "avg_sun_need":    avg("sun_need"),      "min_sun":   mn("sun_need"),    "max_sun":   mx("sun_need"),
            "avg_nutrition_need": avg("nutrition_need"),
            "avg_root_depth":  avg("root_depth"),   "min_root":  mn("root_depth"),  "max_root":  mx("root_depth"),
            "avg_energy_storage": avg("energy_storage"),

            # Reproduction
            "avg_seed_distribution":  avg("seed_distribution"),
            "avg_seed_hardiness":     avg("seed_hardiness"),
            "avg_reproduction_time":  avg("reproduction_time"),
            "avg_spread":             avg("spread"),

            # Environment adaptation
            "avg_best_temperature":       avg("best_temperature"),
            "avg_temperature_resilience": avg("temperature_resilience"),

            # Defenses
            "avg_toughness":   avg("toughness"),
            "avg_toxicity":    avg("toxicity"),
            "avg_thorniness":  avg("thorniness"),
        }

    def tile_detail(self, x, y):
        """Full trait breakdown for every plant on a tile — used when user clicks a hex."""
        tile = self.grid[x][y]
        return {
            "x": x, "y": y,
            "environment": {
                "sunlight":     round(tile.sunlight, 2),
                "rainfall":     round(tile.rainfall, 2),
                "groundwater":  round(tile.groundwater, 2),
                "soil_quality": round(tile.soil_quality, 2),
                "humidity":     round(tile.humidity, 2),
                "temperature":  round(tile.temperature, 2),
                "elevation":    round(tile.elevation, 2),
            },
            "plants": [
                {
                    "plant_id":             p.plant_id,
                    "parent_id":            p.parent_id,
                    "health":               round(p.health, 2),
                    "age":                  p.age,
                    "energy":               round(p.energy, 2),
                    "potential_height":     round(p.potential_height, 2),
                    "growth_speed":         round(p.growth_speed, 2),
                    "lifespan":             round(p.lifespan, 2),
                    "spread":               round(p.spread, 2),
                    "root_depth":           round(p.root_depth, 2),
                    "seed_distribution":    round(p.seed_distribution, 2),
                    "reproduction_time":    round(p.reproduction_time, 2),
                    "sun_need":             round(p.sun_need, 2),
                    "nutrition_need":       round(p.nutrition_need, 2),
                    "water_need":           round(p.water_need, 2),
                    "toughness":            round(p.toughness, 2),
                    "toxicity":             round(p.toxicity, 2),
                    "thorniness":           round(p.thorniness, 2),
                    "energy_storage":       round(p.energy_storage, 2),
                    "seed_hardiness":       round(p.seed_hardiness, 2),
                    "leaf_size":            round(p.leaf_size, 2),
                    "best_temperature":     round(p.best_temperature, 2),
                    "temperature_resilience": round(p.temperature_resilience, 2),
                    "maturity_age":           round(p.maturity_age, 2),
                    "is_mature":              p.is_mature,
                }
                for p in tile.plants if p.alive
            ]
        }

    def to_json(self):
        tiles = []
        for x in range(self.width):
            for y in range(self.height):
                tile = self.grid[x][y]
                alive = [p for p in tile.plants if p.alive]
                tiles.append({
                    "x":            x,
                    "y":            y,
                    "sunlight":     round(tile.sunlight, 2),
                    "rainfall":     round(tile.rainfall, 2),
                    "groundwater":  round(tile.groundwater, 2),
                    "soil_quality": round(tile.soil_quality, 2),
                    "humidity":     round(tile.humidity, 2),
                    "temperature":  round(tile.temperature, 2),
                    "elevation":    round(tile.elevation, 2),
                    "is_water":     tile.is_water,
                    "plant_count":  len(alive),
                    # Average traits across plants on this tile for visualisation
                    "avg_health":       round(sum(p.health for p in alive) / len(alive), 2) if alive else 0,
                    "avg_root_depth":   round(sum(p.root_depth for p in alive) / len(alive), 2) if alive else 0,
                    "avg_height":       round(sum(p.potential_height for p in alive) / len(alive), 2) if alive else 0,
                })
        return {"width": self.width, "height": self.height, "tiles": tiles}
