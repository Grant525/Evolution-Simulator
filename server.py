"""
FastAPI server — bridges the simulation and the web frontend.

Endpoints:
  GET  /           — serves index.html
  GET  /state      — full grid state for redrawing the map
  POST /tick       — advance simulation one step
  GET  /tile/{x}/{y} — full plant trait detail for a clicked tile
"""

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from world import World

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

world = World(width=20, height=20)


@app.get("/")
def index():
    return FileResponse("index.html")


@app.post("/restart")
def restart():
    global world
    world = World(width=20, height=20)
    return {"status": "ok"}


@app.get("/state")
def get_state():
    return world.to_json()


@app.post("/tick")
def tick():
    world.tick()
    return {"status": "ok"}


@app.post("/ticks/{n}")
def tick_n(n: int):
    for _ in range(min(n, 1000)):  # cap at 1000 to prevent freezing
        world.tick()
    return {"status": "ok", "tick": world.tick_count}


@app.get("/stats")
def get_stats():
    return world.stats()


@app.get("/lineage/{plant_id}")
def get_lineage(plant_id: int):
    result = world.lineage(plant_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Plant not found")
    return result


@app.get("/tile/{x}/{y}")
def get_tile(x: int, y: int):
    if not (0 <= x < world.width and 0 <= y < world.height):
        raise HTTPException(status_code=404, detail="Tile out of bounds")
    return world.tile_detail(x, y)
