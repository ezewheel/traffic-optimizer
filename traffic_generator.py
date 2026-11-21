import math
import os
import random
import sys
import unicodedata
import warnings

import sumolib

import simulation

warnings.filterwarnings("ignore", message="Module 'rtree' not available")

BACKGROUND_TYPE = "fondo"
WALKING_MODE = "caminando"
ROUTES_FILE = simulation.ROUTES_FILE
VEHICLE_TYPES = {
    "auto": ("passenger", "250,205,40", 1.0),
    "colectivo": ("bus", "40,120,255", 1.5),
    "moto": ("motorcycle", "255,90,40", 0.5),
    "bici": ("bicycle", "60,220,90", 0.5),
    BACKGROUND_TYPE: ("passenger", "185,190,200", 0.0),
}
PEAK_FRACTION = 0.65
MIN_STOP_S = 20
SECONDS_PER_MINUTE = 60
MIN_LANE_LENGTH_M = 20
STOP_START_MIN_M = 12
STOP_END_MARGIN_M = 5
STOP_LENGTH_M = 8
STOP_SIGMA_DIVISOR = 2
PERCENT = 100


def normalize(name):
    without_accents = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return without_accents.strip().lower()


def corner(network, street1, street2):
    points = []
    for node in network.getNodes():
        streets = {normalize(e.getName()) for e in node.getIncoming() + node.getOutgoing()}
        if normalize(street1) in streets and normalize(street2) in streets:
            points.append(node.getCoord())
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def locate_gate(network, gate):
    street, (cross1, cross2) = gate["calle"], gate["entre"]
    a, b = corner(network, street, cross1), corner(network, street, cross2)
    if a is None or b is None:
        streets = sorted({e.getName() for e in network.getEdges() if e.getName()})
        sys.exit(f"No encontre '{street} entre {cross1} y {cross2}' en el mapa.\n"
                 f"Calles del mapa: {', '.join(streets)}")
    return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2


def reachable(edge, vclass, forward=True):
    seen, pending = {edge}, [edge]
    while pending:
        current = pending.pop()
        neighbors = current.getOutgoing() if forward else current.getIncoming()
        for neighbor in neighbors:
            if neighbor not in seen and neighbor.allows(vclass):
                seen.add(neighbor)
                pending.append(neighbor)
    return seen


def boundary_edges(network, vclass):
    edges = [e for e in network.getEdges() if e.allows(vclass)]
    return ([e for e in edges if not e.getIncoming()],
            [e for e in edges if not e.getOutgoing()])


def stopping_places(network, point, radius, vclass):
    entrances, exits = boundary_edges(network, vclass)
    places = []
    for edge, _ in network.getNeighboringEdges(point[0], point[1], radius):
        lane = next((c for c in edge.getLanes() if c.allows(vclass)), None)
        if lane is None or lane.getLength() < MIN_LANE_LENGTH_M:
            continue
        before = reachable(edge, vclass, forward=False)
        after = reachable(edge, vclass)
        origins = [e for e in entrances if e in before]
        destinations = [s for s in exits if s in after]
        if origins and destinations:
            places.append((lane, origins, destinations))
    return places


def choose_edge(rng, edges):
    return rng.choices(edges, weights=[e.getLaneNumber() for e in edges])[0]


def generate(config):
    school = config["colegio"]
    rng = random.Random(config["simulacion"]["semilla"])
    network = sumolib.net.readNet(config["mapa"])
    window = school["ventana_llegada_min"] * SECONDS_PER_MINUTE

    modes = school["como_llegan"]
    for mode in modes:
        if mode not in VEHICLE_TYPES and mode != WALKING_MODE:
            sys.exit(f"'{mode}' no es un vehiculo valido. Opciones: auto, colectivo, moto, bici, caminando")
    choices = rng.choices(list(modes), weights=list(modes.values()), k=school["alumnos"])
    students = {mode: choices.count(mode) for mode in modes}
    vehicles = {
        "auto": round(students.get("auto", 0) / school["chicos_por_auto"]),
        "colectivo": math.ceil(students.get("colectivo", 0) / school["chicos_por_colectivo"]),
        "moto": students.get("moto", 0),
        "bici": students.get("bici", 0),
    }
    print(f"Alumnos: {school['alumnos']} -> " + ", ".join(f"{m} {n}" for m, n in students.items()))
    print("Vehiculos al colegio: " + ", ".join(f"{t} {n}" for t, n in vehicles.items()))

    gates = school["puertas"]
    places = {}
    for i, gate in enumerate(gates):
        point = locate_gate(network, gate)
        for vehicle_type in vehicles:
            places[i, vehicle_type] = stopping_places(network, point, school["radio_descenso_m"],
                                                      VEHICLE_TYPES[vehicle_type][0])
        print(f"Puerta {gate['calle']} entre {' y '.join(gate['entre'])} "
              f"({gate['porcentaje']}%): {len(places[i, 'auto'])} cuadras para parar")

    trips = []
    for vehicle_type, count in vehicles.items():
        for n in range(count):
            gate = rng.choices(range(len(gates)), weights=[g["porcentaje"] for g in gates])[0]
            if not places[gate, vehicle_type]:
                continue
            lane, origins, destinations = rng.choices(
                places[gate, vehicle_type],
                weights=[lane.getLength() for lane, _, _ in places[gate, vehicle_type]])[0]
            depart = rng.triangular(0, window, PEAK_FRACTION * window)
            stop_s = max(MIN_STOP_S, rng.gauss(school["parada_media_s"],
                                               school["parada_media_s"] / STOP_SIGMA_DIVISOR))
            stop_s *= VEHICLE_TYPES[vehicle_type][2]
            stop_end = rng.uniform(STOP_START_MIN_M, lane.getLength() - STOP_END_MARGIN_M)
            parking = rng.random() >= school["doble_fila_pct"] / PERCENT
            origin = choose_edge(rng, origins)
            destination = choose_edge(rng, destinations)
            trips.append((depart,
                f'    <trip id="{vehicle_type}_{n}" type="{vehicle_type}" depart="{depart:.1f}" '
                f'from="{origin.getID()}" to="{destination.getID()}" '
                f'departLane="best" departSpeed="max">\n'
                f'        <stop lane="{lane.getID()}" startPos="{stop_end - STOP_LENGTH_M:.1f}" '
                f'endPos="{stop_end:.1f}" '
                f'duration="{stop_s:.0f}" parking="{str(parking).lower()}"/>\n'
                f'    </trip>\n'))

    entrances, exits = boundary_edges(network, "passenger")
    destinations_by_origin = {e: [s for s in exits if s in reachable(e, "passenger") and s != e]
                              for e in entrances}
    entrances = [e for e in entrances if destinations_by_origin[e]]
    for n in range(config["trafico_fondo"]["autos"]):
        origin = choose_edge(rng, entrances)
        depart = rng.uniform(0, window)
        destination = choose_edge(rng, destinations_by_origin[origin])
        trips.append((depart,
            f'    <trip id="{BACKGROUND_TYPE}_{n}" type="{BACKGROUND_TYPE}" depart="{depart:.1f}" '
            f'from="{origin.getID()}" to="{destination.getID()}" '
            f'departLane="best" departSpeed="max"/>\n'))

    folder = simulation.scenario_folder(config)
    path = os.path.join(folder, ROUTES_FILE)
    with open(path, "w", encoding="utf-8") as f:
        f.write("<routes>\n")
        for vehicle_type, (vclass, color, _) in VEHICLE_TYPES.items():
            f.write(f'    <vType id="{vehicle_type}" vClass="{vclass}" color="{color}"/>\n')
        for _, xml in sorted(trips, key=lambda trip: trip[0]):
            f.write(xml)
        f.write("</routes>\n")
    print(f"{len(trips)} viajes guardados en {path}")


if __name__ == "__main__":
    generate(simulation.load_config())