
import random

HEALTH_THRESHOLD  = 0.3   # plants below this die
REPRODUCTION_COST = 20.0  # energy required to reproduce


class Plant:

    def __init__(self, genome):
        self.genome = genome
        self.potential_height   = genome['potential_height']
        self.growth_speed       = genome['growth_speed']
        self.lifespan           = genome['lifespan']
        self.spread             = genome['spread']
        self.root_depth         = genome['root_depth']
        self.seed_distribution  = genome['seed_distribution']
        self.reproduction_time  = genome['reproduction_time']
        self.sun_need           = genome['sun_need']
        self.nutrition_need     = genome['nutrition_need']
        self.water_need         = genome['water_need']
        self.toughness          = genome['toughness']
        self.toxicity           = genome['toxicity']
        self.thorniness         = genome['thorniness']
        self.energy_storage          = genome['energy_storage']
        self.seed_hardiness          = genome['seed_hardiness']
        self.leaf_size               = genome['leaf_size']
        self.best_temperature        = genome['best_temperature']
        self.temperature_resilience  = genome['temperature_resilience']
        self.maturity_age            = genome['maturity_age']  # 0-1 maps to 1-15 ticks

        self.energy    = 30.0
        self.health    = 1.0
        self.age       = 0
        self.alive     = True
        self.is_mature = False
        self.plant_id  = None   # assigned by World when registered
        self.parent_id = None   # set by reproduce()
        self.died_tick = None   # set when plant dies

    
    def water_available(self, tile):
        return tile.rainfall_for(self) + tile.groundwater_for(self)

    def compute_health(self, tile, effective_sunlight):
        sun_ratio       = min(1.0, effective_sunlight / self.sun_need) if self.sun_need > 0 else 1.0
        water_ratio     = min(1.0, self.water_available(tile) / self.water_need) if self.water_need > 0 else 1.0
        nutrition_ratio = min(1.0, tile.nutrition_for(self) / self.nutrition_need) if self.nutrition_need > 0 else 1.0

        # Any critical resource below 0.2 makes the plant critically unhealthy
        if sun_ratio < 0.2 or water_ratio < 0.2 or nutrition_ratio < 0.2:
            self.health = 0.0
            return 0.0

        self.health = (sun_ratio + water_ratio + nutrition_ratio) / 3.0
        return self.health

    # Energy costs: traits with tradeoffs
    #   - Height, growth speed, toxin production, and defenses all cost energy
    #limit to lifespan
    #energy upkeep and capture should change as roots/plant grows and both needs and can collect more enrgy
    def upkeep_cost(self):
        base = (
            self.potential_height       * 0.10 +   # tall plants are expensive to maintain
            self.toughness              * 0.05 +   # structural resilience has a cost
            self.toxicity               * 0.10 +   # producing toxins is costly
            self.thorniness             * 0.05 +   # growing thorns costs less
            self.temperature_resilience * 0.10 +   # wider tolerance requires more cellular maintenance
            self.lifespan               * 0.08 +   # longer-lived plants invest in cell repair
            self.energy_storage         * 0.05 +   # maintaining larger storage has overhead
            self.leaf_size              * 0.05     # more leaf area to grow and maintain
        )
        # During growth phase, growth_speed drives a large extra energy cost —
        # fast growers reach maturity sooner but burn much more energy doing it
        if not self.is_mature:
            return base + self.growth_speed * 0.5 * (1.0 - self.maturity_age)
        return base

    def sprout_chance(self, tile):
        # How far the tile temperature is from this plant's optimal
        temp_diff = abs(tile.temperature - self.best_temperature)

        # If outside resilience range, can't sprout at all
        if temp_diff > self.temperature_resilience:
            return 0.0

        # Temperature factor: 1.0 at perfect temp, 0.0 at edge of resilience
        temp_factor = 1.0 - (temp_diff / self.temperature_resilience)

        # Water need at sprout time uses base water_need only — no leaves yet so no transpiration loss
        water_factor = min(1.0, self.water_available(tile) / self.water_need) if self.water_need > 0 else 1.0

        # Soil quality — use raw tile value since seed has no roots yet to compete with
        soil_factor = min(1.0, tile.soil_quality)

        # Hardiness helps with temperature extremes and poor soil, but can't substitute for water —
        # a seed needs some minimum moisture to germinate regardless of hardiness
        temp_soil_raw = (temp_factor + soil_factor) / 2.0
        temp_soil_boosted = min(1.0, temp_soil_raw + self.seed_hardiness * (1.0 - temp_soil_raw))

        # Water is a hard requirement — hardiness gives a small buffer but can't fully compensate
        water_boosted = min(1.0, water_factor + self.seed_hardiness * 0.2)

        raw_chance = (temp_soil_boosted + water_boosted) / 2.0

        # Competition: more established plants on the tile = harder to sprout
        established = len([p for p in tile.plants if p.alive])
        competition_penalty = min(0.8, established * 0.1)  # up to 80% reduction

        return max(0.0, raw_chance - competition_penalty)

    # Energy income: limited by both supply (tile) and demand (plant needs)
    #   - Healthier plants convert resources more efficiently (0.5 -> 1.0)

    def effective_water_need(self, tile):
        # Large leaves lose more water through transpiration in dry/low humidity conditions
        transpiration_loss = self.leaf_size * (1.0 - tile.humidity) * 0.3
        return self.water_need + transpiration_loss

    def energy_gain(self, tile, effective_sunlight):
        # Larger leaves capture more sunlight; drought-adapted plants (low water_need)
        # have slower metabolism and convert sunlight less efficiently
        sun_captured   = effective_sunlight * (0.5 + 0.5 * self.leaf_size) * (0.4 + 0.6 * self.water_need)
        sun_used       = min(sun_captured,                    self.sun_need)
        water_used     = min(self.water_available(tile),   self.effective_water_need(tile))
        nutrition_used = min(tile.nutrition_for(self),     self.nutrition_need)

        base_income = (sun_used + water_used + nutrition_used) / 3.0

        # Health bonus: healthy plants are more energy-efficient
        efficiency = 0.5 + 0.5 * self.health   # range [0.5, 1.0]
        return base_income * efficiency

   
    # daily update
    def update(self, tile, effective_sunlight):
        if not self.alive:
            return

        self.age += 1
        self.compute_health(tile, effective_sunlight)

        # lifespan 0-1 maps to 0-20 years (ticks)
        if self.health < HEALTH_THRESHOLD or self.age > self.lifespan * 20:
            self.alive = False
            return  # died_tick set by World.tick()

        # maturity_age 0-1 maps to 2-10 ticks; growth_speed divides that time
        # (fast growers pay energy but reach maturity sooner)
        base_ticks = 2 + self.maturity_age * 8
        maturity_ticks = min(round(base_ticks / (0.5 + self.growth_speed)), round(self.lifespan * 20 * 0.5))
        if not self.is_mature and self.age >= maturity_ticks:
            self.is_mature = True

        net = (self.energy_gain(tile, effective_sunlight) - self.upkeep_cost()) * 10
        self.energy = min(self.energy + net, self.energy_storage * 100)

        if self.energy <= 0:
            self.alive = False

    # 
    # Reproduction
    # 
    def reproduction_cost(self):
        return REPRODUCTION_COST * (1.0 + self.seed_distribution) * (1.0 + self.seed_hardiness * 0.5) * (0.5 + self.reproduction_time * 0.5)

    def can_reproduce(self):
        return (
            self.alive
            and self.is_mature
            and self.energy >= self.reproduction_cost()
        )

    def reproduce(self):
        self.energy -= self.reproduction_cost()
        child = Plant(mutate(self.genome))
        child.energy    = 30.0 * (1.0 - self.seed_distribution * 0.8)
        child.parent_id = self.plant_id  # lineage link
        return child 


# Mutation - Gaussian noise on each trait (10% std dev by default)
#
# Other options to consider:
#   A) Fixed delta:       value + random.uniform(-delta, delta)
#   B) Per-trait rates:   each trait gets its own mutation_rate in genome
#   C) Occasional large jumps + small noise (bimodal)
def mutate(genome, mutation_rate=0.10):
    child = {}
    for trait, value in genome.items():
        noise = random.gauss(0, abs(value) * mutation_rate)
        child[trait] = max(0.01, min(1.0, value + noise))  # clamp to [0.01, 1.0]
    return child


