import copy
import json
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime

import sumolib

import genetic_algorithm
import simulation
import traffic_generator

MAX_SEED = 1_000_000

METRICS = [
    ("Fitness (s perdidos por vehículo)", "fitness"),
    ("Tiempo perdido medio (s)", "time_loss"),
    ("Espera media (s)", "waiting_time"),
    ("Viaje medio (s)", "duration"),
    ("Teletransportes", "teleports"),
    ("Llegaron a destino", "arrived"),
]

REPORT_TITLE = "# Informe de corridas del algoritmo genético: {school}"
FITNESS_NOTE = "Menor fitness es mejor: un cambio negativo es una mejora."
SUMMARY_TITLE = "## Resultado promedio vs. caso base"
BEST_RUN_TITLE = "## Mejor corrida: corrida {number}"
BEST_RUN_LIGHTS_NOTE = "Semáforos de la mejor corrida:"
PER_TRAFFIC_TITLE = "## Resultados por tráfico"
ALL_RUNS_TITLE = "## Todas las corridas"
ALL_RUNS_NOTE = "Cada celda: *caso base → optimizado*."
RUN_DETAIL_TITLE = "## Detalle de cada corrida"
RUN_DETAIL_SUBTITLE = "### Corrida {number}"
CONFIG_TITLE = "## Configuración usada"

SUMMARY_HEADER = ["Métrica", "Caso base (promedio)", "Optimizado (promedio ± desvío)", "Cambio"]
BEST_RUN_HEADER = ["Métrica", "Caso base", "Mejor corrida", "Cambio vs. caso base",
                   "Promedio de las corridas", "Cambio vs. promedio"]
PER_TRAFFIC_HEADER = ["Tráfico", "Semilla", "Vehículos", "Fitness base", "Corridas AG",
                      "Fitness opt. mejor", "Fitness opt. promedio", "Fitness opt. peor",
                      "Desvío", "Cambio promedio"]
ALL_RUNS_HEADER = ["Corrida", "Tráfico", "Semilla tráfico", "Semilla AG", "Generaciones", "Fitness",
                   "Cambio fitness", "Tiempo perdido (s)", "Espera (s)", "Viaje (s)",
                   "Teletransportes", "Llegaron"]
LIGHTS_HEADER = ["Semáforo", "Original (verdes)", "Optimizado (verdes)"]


@dataclass
class Run:
    number: int
    traffic: int
    traffic_seed: int
    ga_seed: int
    base: dict
    optimized: dict
    best: list
    history: list

    @property
    def change(self):
        return (self.optimized["fitness"] - self.base["fitness"]) / self.base["fitness"] * 100


def ask_positive_int(message):
    while True:
        text = input(message).strip()
        if text.isdigit() and int(text) > 0:
            return int(text)
        print("  Tiene que ser un numero entero mayor que 0.")


def with_fitness(stats):
    return dict(stats, fitness=genetic_algorithm.fitness(stats))


def main():
    config = simulation.load_config()
    ga_params = config["algoritmo_genetico"]
    print(f"Escuela: {config['colegio']['nombre']} | mapa: {config['mapa']}"
          f" | resultados en: {config['carpeta_reportes']}")
    n_traffics = ask_positive_int("Cantidad de traficos distintos: ")
    n_ga_runs = ask_positive_int("Corridas del algoritmo genetico por trafico: ")
    total = n_traffics * n_ga_runs

    network = sumolib.net.readNet(config["mapa"], withPrograms=True)
    traffic_lights = genetic_algorithm.read_traffic_lights(network)
    if not traffic_lights:
        sys.exit("El mapa no tiene semaforos para optimizar.")
    initial = genetic_algorithm.original_individual(traffic_lights)
    limits = genetic_algorithm.bounds(traffic_lights, ga_params)

    seeds = random.Random(config["simulacion"]["semilla"]).sample(range(1, MAX_SEED),
                                                                  n_traffics + total)
    traffic_seeds, ga_seeds = seeds[:n_traffics], seeds[n_traffics:]

    start = datetime.now()
    stamp = start.strftime(simulation.TIMESTAMP_FORMAT)
    name = simulation.map_name(config)
    reports_folder = os.path.join(config["carpeta_reportes"], f"{name}_{stamp}")
    os.makedirs(reports_folder, exist_ok=True)
    path = os.path.join(reports_folder, f"informe_corridas_{stamp}.md")
    clock = time.perf_counter()
    runs = []

    for i_traffic in range(n_traffics):
        print(f"\n=== Trafico {i_traffic + 1}/{n_traffics} (semilla {traffic_seeds[i_traffic]}) ===")
        session = os.path.join(reports_folder, f"trafico_{i_traffic + 1}")
        os.makedirs(session, exist_ok=True)
        traffic_config = copy.deepcopy(config)
        traffic_config["simulacion"]["semilla"] = traffic_seeds[i_traffic]
        traffic_config["carpeta_sesion"] = session
        traffic_generator.generate(traffic_config)
        evaluator = genetic_algorithm.Evaluator(traffic_config, traffic_lights)

        for i_ga in range(n_ga_runs):
            number = len(runs) + 1
            ga_seed = ga_seeds[number - 1]
            print(f"\n--- Corrida {number}/{total}: trafico {i_traffic + 1}, "
                  f"AG {i_ga + 1}/{n_ga_runs} (semilla {ga_seed}) ---")
            best, history = genetic_algorithm.genetic_algorithm(evaluator, limits, initial, ga_params,
                                                  random.Random(ga_seed))
            runs.append(Run(
                number, i_traffic + 1, traffic_seeds[i_traffic], ga_seed,
                with_fitness(evaluator.results[tuple(initial)]),
                with_fitness(evaluator.results[tuple(best)]),
                best, history))
            write_report(path, config, traffic_lights, initial, runs, n_traffics, n_ga_runs,
                         start, time.perf_counter() - clock)

        simulation.remove_temporal(session)

    best_run = min(runs, key=lambda run: run.change)
    print(f"\nCambio promedio del fitness: {mean(run.change for run in runs):+.1f}%"
          f" | mejor corrida: {best_run.number} ({best_run.change:+.1f}%)")
    print(f"Informe guardado en {path}")


def mean(values):
    return float(statistics.mean(values))


def std_dev(values):
    values = list(values)
    return statistics.stdev(values) if len(values) > 1 else 0.0


def format_number(x):
    return str(x) if isinstance(x, int) else f"{x:.1f}"


def format_percent(x):
    return f"{x:+.1f}%"


def table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines + [""]


def describe_light(light, greens, offset):
    return ", ".join(f"{street} {green} s" for street, green in zip(light.streets, greens)) \
        + f"; desfase {offset} s"


def lights_table(traffic_lights, initial, best):
    rows = [[light.name,
             describe_light(light, greens_before, offset_before),
             describe_light(light, greens_after, offset_after)]
            for (light, greens_before, offset_before), (_, greens_after, offset_after)
            in zip(genetic_algorithm.per_traffic_light(traffic_lights, initial),
                   genetic_algorithm.per_traffic_light(traffic_lights, best))]
    return table(LIGHTS_HEADER, rows)


def write_report(path, config, traffic_lights, initial, runs, n_traffics, n_ga_runs, start, seconds):
    total = n_traffics * n_ga_runs
    is_complete = len(runs) == total
    best_run = min(runs, key=lambda run: run.change)
    base_mean = {key: mean(run.base[key] for run in runs) for _, key in METRICS}
    optimized_mean = {key: mean(run.optimized[key] for run in runs) for _, key in METRICS}
    changes = [run.change for run in runs]

    lines = [REPORT_TITLE.format(school=config["colegio"]["nombre"]), ""]
    lines += [f"- **Fecha:** {start:%d/%m/%Y %H:%M}",
              f"- **Escuela:** {config['colegio']['nombre']} ({config['colegio']['alumnos']} alumnos)",
              f"- **Mapa:** `{config['mapa']}`",
              f"- **Corridas:** {len(runs)} de {total} ({n_traffics} tráficos × {n_ga_runs} corridas "
              f"del AG por tráfico)" + ("" if is_complete else " (informe parcial)"),
              f"- **Duración:** {int(seconds // 60)} min {int(seconds % 60)} s",
              ""]
    lines += [FITNESS_NOTE, ""]

    lines += [SUMMARY_TITLE, ""]
    lines += table(SUMMARY_HEADER,
                   [[title, format_number(base_mean[key]),
                     f"{format_number(optimized_mean[key])} ± "
                     f"{format_number(std_dev(run.optimized[key] for run in runs))}",
                     genetic_algorithm.percent_change(base_mean[key], optimized_mean[key])] for title, key in METRICS])
    lines += [f"Cambio del fitness por corrida: promedio **{format_percent(mean(changes))}**, "
              f"desvío {format_number(std_dev(changes))} puntos, mejor {format_percent(min(changes))}, "
              f"peor {format_percent(max(changes))}.", ""]

    lines += [BEST_RUN_TITLE.format(number=best_run.number), "",
              f"Tráfico {best_run.traffic} (semilla {best_run.traffic_seed}), AG con semilla "
              f"{best_run.ga_seed}, {len(best_run.history)} generaciones. Cambio del fitness: "
              f"**{format_percent(best_run.change)}** (promedio: {format_percent(mean(changes))}).", ""]
    lines += table(BEST_RUN_HEADER,
                   [[title, format_number(best_run.base[key]), format_number(best_run.optimized[key]),
                     genetic_algorithm.percent_change(best_run.base[key], best_run.optimized[key]),
                     format_number(optimized_mean[key]),
                     genetic_algorithm.percent_change(optimized_mean[key], best_run.optimized[key])]
                    for title, key in METRICS])
    lines += [BEST_RUN_LIGHTS_NOTE, ""]
    lines += lights_table(traffic_lights, initial, best_run.best)

    lines += [PER_TRAFFIC_TITLE, ""]
    rows = []
    for traffic in sorted({run.traffic for run in runs}):
        traffic_runs = [run for run in runs if run.traffic == traffic]
        fits = [run.optimized["fitness"] for run in traffic_runs]
        first = traffic_runs[0]
        rows.append([traffic, first.traffic_seed, first.base["loaded"],
                     format_number(first.base["fitness"]), len(traffic_runs),
                     format_number(min(fits)), format_number(mean(fits)), format_number(max(fits)),
                     format_number(std_dev(fits)),
                     format_percent(mean(run.change for run in traffic_runs))])
    lines += table(PER_TRAFFIC_HEADER, rows)

    lines += [ALL_RUNS_TITLE, "", ALL_RUNS_NOTE, ""]
    rows = []
    for run in runs:
        row = [run.number, run.traffic, run.traffic_seed, run.ga_seed, len(run.history)]
        row += [f"{format_number(run.base[key])} → {format_number(run.optimized[key])}"
                for _, key in METRICS]
        row.insert(6, format_percent(run.change))
        rows.append(row)
    lines += table(ALL_RUNS_HEADER, rows)

    lines += [RUN_DETAIL_TITLE, ""]
    for run in runs:
        lines += [RUN_DETAIL_SUBTITLE.format(number=run.number), "",
                  f"Tráfico {run.traffic} (semilla {run.traffic_seed}), semilla del AG {run.ga_seed}. "
                  f"Cambio del fitness: {format_percent(run.change)}.", "",
                  "- Mejor fitness por generación: "
                  + " → ".join(format_number(best) for best, _ in run.history),
                  "- Fitness promedio de la población: "
                  + " → ".join(format_number(avg) for _, avg in run.history),
                  ""]
        lines += lights_table(traffic_lights, initial, run.best)

    lines += [CONFIG_TITLE, "",
              "```json", json.dumps(config, ensure_ascii=False, indent=2), "```", ""]

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()