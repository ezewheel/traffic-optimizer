import os
import random
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import sumolib

import simulation

MAX_OFFSET = 119
NOT_ARRIVED_PENALTY = 900
TELEPORT_PENALTY = 300
MIN_GREEN_PHASES = 2
GREEN_STATES = "Gg"
YELLOW_STATE = "y"
PROGRAM_ID = "ga"
RESERVED_CPUS = 1
SECONDS_PER_MINUTE = 60
GENE_SWAP_PROB = 0.5
MUTATION_SIGMA_DIVISOR = 6
IMPROVEMENT_THRESHOLD = 1

RESULT_METRICS = [
    ("Tiempo perdido medio (s)", "time_loss"),
    ("Espera media (s)", "waiting_time"),
    ("Viaje medio (s)", "duration"),
]


@dataclass
class TrafficLight:
    id: str
    streets: list
    phases: list
    green_indices: list
    offset: int

    @property
    def name(self):
        return " y ".join(dict.fromkeys(self.streets))

    @property
    def greens(self):
        return [int(self.phases[i][1]) for i in self.green_indices]


class TrafficLights(list):

    def __init__(self, optimizable, fixed):
        super().__init__(optimizable)
        self.fixed = fixed


def read_traffic_lights(network):
    optimizable, fixed = [], []
    for tls in network.getTrafficLights():
        incoming = {i: lane.getEdge().getName() or "calle sin nombre"
                    for lane, _, i in tls.getConnections()}
        program = list(tls.getPrograms().values())[0]
        phases = [(phase.state, float(phase.duration)) for phase in program.getPhases()]
        streets, green_indices = [], []
        in_green = False
        for k, (state, _) in enumerate(phases):
            green_streets = [incoming[i] for i, c in enumerate(state)
                             if c in GREEN_STATES and i in incoming]
            if YELLOW_STATE in state or not green_streets:
                in_green = False
            elif not in_green:
                in_green = True
                streets.append(Counter(green_streets).most_common(1)[0][0])
                green_indices.append(k)
        offset = int(float(program.getOffset() or 0))
        light = TrafficLight(tls.getID(), streets, phases, green_indices, offset)
        (optimizable if len(green_indices) >= MIN_GREEN_PHASES else fixed).append(light)
    return TrafficLights(optimizable, fixed)


def per_traffic_light(traffic_lights, individual):
    i = 0
    for light in traffic_lights:
        n = len(light.green_indices)
        yield light, individual[i:i + n], individual[i + n]
        i += n + 1


def write_traffic_lights(path, traffic_lights, individual):
    xml = ["<additional>"]
    for light, greens, offset in per_traffic_light(traffic_lights, individual):
        xml += _tl_logic_xml(light, greens, offset)
    for light in traffic_lights.fixed:
        xml += _tl_logic_xml(light, [], light.offset)
    xml.append("</additional>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(xml) + "\n")


def _tl_logic_xml(light, greens, offset):
    durations = [seconds for _, seconds in light.phases]
    for i, green in zip(light.green_indices, greens):
        durations[i] = green
    xml = [f'    <tlLogic id="{light.id}" type="static" programID="{PROGRAM_ID}" offset="{offset}">']
    xml += [f'        <phase duration="{seconds:g}" state="{state}"/>'
            for (state, _), seconds in zip(light.phases, durations)]
    return xml + ["    </tlLogic>"]


def fitness(result):
    not_arrived = result["loaded"] - result["arrived"]
    lost = (result["arrived"] * result["time_loss"] + not_arrived * NOT_ARRIVED_PENALTY
            + result["teleports"] * TELEPORT_PENALTY)
    return lost / max(1, result["loaded"])


class Evaluator:

    def __init__(self, config, traffic_lights):
        self.config = config
        self.traffic_lights = traffic_lights
        self.folder = config["carpeta_sesion"]
        self.routes = os.path.join(self.folder, simulation.ROUTES_FILE)
        self.results = {}

    def evaluate(self, population):
        new = list({tuple(ind) for ind in population} - self.results.keys())
        with ThreadPoolExecutor(max_workers=max(1, os.cpu_count() - RESERVED_CPUS)) as pool:
            for individual, stats in zip(new, pool.map(self._simulate, new)):
                self.results[individual] = stats
        return [fitness(self.results[tuple(ind)]) for ind in population]

    def _simulate(self, individual):
        temporal = simulation.temporal_folder(self.folder)
        with tempfile.TemporaryDirectory(dir=temporal) as folder:
            path = os.path.join(folder, "semaforos.add.xml")
            write_traffic_lights(path, self.traffic_lights, individual)
            sim = self.config["simulacion"]
            return simulation.simulate(self.config["mapa"], self.routes, path,
                                       sim["duracion_min"] * SECONDS_PER_MINUTE, sim["semilla"],
                                       temporal)


def bounds(traffic_lights, params):
    result = []
    for light in traffic_lights:
        result += ([(params["verde_min"], params["verde_max"])] * len(light.green_indices)
                   + [(0, MAX_OFFSET)])
    return result


def random_individual(bounds, rng):
    return [rng.randint(low, high) for low, high in bounds]


def tournament(population, fits, k, rng):
    chosen = rng.sample(range(len(population)), k)
    return population[min(chosen, key=lambda i: fits[i])]


def crossover(a, b, rng):
    return [x if rng.random() < GENE_SWAP_PROB else y for x, y in zip(a, b)]


def mutate(individual, bounds, prob, rng):
    child = []
    for gene, (low, high) in zip(individual, bounds):
        if rng.random() < prob:
            gene = round(gene + rng.gauss(0, (high - low) / MUTATION_SIGMA_DIVISOR))
        child.append(min(high, max(low, gene)))
    return child


def original_individual(traffic_lights):
    return [gene for light in traffic_lights for gene in light.greens + [light.offset]]


def genetic_algorithm(evaluator, bounds, initial, params, rng):
    population = [initial] + [random_individual(bounds, rng) for _ in range(params["poblacion"] - 1)]
    best, best_fit, no_improvement = initial, float("inf"), 0
    history = []

    for generation in range(1, params["generaciones"] + 1):
        fits = evaluator.evaluate(population)
        order = sorted(range(len(population)), key=lambda i: fits[i])
        no_improvement = 0 if fits[order[0]] < best_fit - IMPROVEMENT_THRESHOLD else no_improvement + 1
        if fits[order[0]] < best_fit:
            best, best_fit = population[order[0]], fits[order[0]]
        history.append((best_fit, sum(fits) / len(fits)))
        print(f"Generacion {generation:2d}/{params['generaciones']}: mejor {best_fit:6.1f} s"
              f" | promedio {history[-1][1]:6.1f} s")
        if no_improvement >= params["paciencia"]:
            print(f"{no_improvement} generaciones sin mejorar: corto antes.")
            break

        new_population = [population[i] for i in order[:params["elite"]]]
        while len(new_population) < params["poblacion"]:
            a = tournament(population, fits, params["torneo"], rng)
            b = tournament(population, fits, params["torneo"], rng)
            child = crossover(a, b, rng) if rng.random() < params["prob_cruce"] else list(a)
            new_population.append(mutate(child, bounds, params["prob_mutacion"], rng))
        population = new_population
    return best, history


def percent_change(a, b):
    return f"{(b - a) / a * 100:+.1f}%" if a else "-"


def print_results(traffic_lights, initial, best, before, after):
    print(f"\n{'RESULTADO':<28}{'original':>10}{'optimizado':>12}{'cambio':>9}")
    for title, key in RESULT_METRICS:
        a, b = before[key], after[key]
        print(f"  {title:<26}{a:>10.1f}{b:>12.1f}{percent_change(a, b):>9}")
    a, b = before["teleports"], after["teleports"]
    print(f"  {'Teletransportes':<26}{a:>10}{b:>12}{percent_change(a, b):>9}")
    arrived = [f"{r['arrived']}/{r['loaded']}" for r in (before, after)]
    print(f"  {'Llegaron a destino':<26}{arrived[0]:>10}{arrived[1]:>12}")
    a, b = fitness(before), fitness(after)
    print(f"  {'Fitness':<26}{a:>10.1f}{b:>12.1f}{percent_change(a, b):>9}")

    print("\nSEMAFOROS (original -> optimizado)")
    for (light, greens_before, offset_before), (_, greens_after, offset_after) in zip(
            per_traffic_light(traffic_lights, initial), per_traffic_light(traffic_lights, best)):
        greens = " | ".join(f"verde {street} {a}s -> {b}s"
                            for street, a, b in zip(light.streets, greens_before, greens_after))
        print(f"  {light.name}: {greens} | desfase {offset_before}s -> {offset_after}s")


def main():
    config = simulation.load_config()
    params = config["algoritmo_genetico"]
    folder = simulation.last_scenario_folder(config)
    if folder is None:
        sys.exit("No hay ningun escenario. Corre primero traffic_generator.py.")
    config["carpeta_sesion"] = folder

    network = sumolib.net.readNet(config["mapa"], withPrograms=True)
    traffic_lights = read_traffic_lights(network)
    if not traffic_lights:
        sys.exit("El mapa no tiene semaforos para optimizar.")
    print(f"{len(traffic_lights)} semaforos a optimizar:")
    for light in traffic_lights:
        print(f"  {light.name}: "
              + " | ".join(f"verde {street} {green}s"
                           for street, green in zip(light.streets, light.greens)))
    if traffic_lights.fixed:
        print(f"{len(traffic_lights.fixed)} semaforos fijos (sin optimizar).")
    print()

    evaluator = Evaluator(config, traffic_lights)
    initial = original_individual(traffic_lights)
    rng = random.Random(config["simulacion"]["semilla"])
    best, _ = genetic_algorithm(evaluator, bounds(traffic_lights, params), initial, params, rng)

    original_path = os.path.join(folder, "semaforos_original.add.xml")
    optimized_path = os.path.join(folder, "semaforos_optimizado.add.xml")
    write_traffic_lights(original_path, traffic_lights, initial)
    write_traffic_lights(optimized_path, traffic_lights, best)
    print_results(traffic_lights, initial, best,
                  evaluator.results[tuple(initial)], evaluator.results[tuple(best)])

    sim = config["simulacion"]
    scenario_configs = simulation.save_scenarios(
        config["mapa"], evaluator.routes, original_path, optimized_path,
        sim["duracion_min"] * SECONDS_PER_MINUTE, sim["semilla"], folder)
    print(f"\nEscenario guardado en {folder}")
    simulation.remove_temporal(folder)
    if sim.get("abrir_simuladores", True):
        print("\nAbriendo SUMO (original | optimizado).")
        simulation.show_side_by_side(scenario_configs, folder)

if __name__ == "__main__":
    main()