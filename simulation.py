import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
import xml.etree.ElementTree as ET

DEFAULT_CONFIG_FILE = "config.json"
MAPS_FOLDER = "mapas"
ESCENARIOS_FOLDER = "escenarios"
REPORTES_FOLDER = "reporte_corridas"
TEMPORAL_SUBFOLDER = ".temporal"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
ROUTES_FILE = "trafico.rou.xml"
SCHOOL_DATA_FILE = "colegio.json"
NETWORK_PATTERNS = ("*.net.xml", "*.net.xml.gz")
EXPECTED_PERCENT_TOTAL = 100
TELEPORT_TIME = "300"
REROUTING_PERIOD = "60"
GUI_DELAY = "50"
GUI_MARGIN = 80
DEFAULT_SCREEN_SIZE = (1920, 1080)
SCHOOL_EXAMPLE = """{
  "nombre": "Colegio Salesiano San Jose",
  "alumnos": 2000,
  "puertas": [
    {"calle": "Salta", "entre": ["Presidente Roca", "Espana"], "porcentaje": 60},
    {"calle": "Presidente Roca", "entre": ["Salta", "Jujuy"], "porcentaje": 40}
  ]
}"""


def load_config():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG_FILE
    with open(path, encoding="utf-8") as f:
        config = json.load(f)

    folder, network = _locate_map(config["mapa"], path)
    name = os.path.basename(os.path.normpath(folder))
    config["mapa"] = network
    config["colegio"] = {"nombre": name, **config.get("colegio", {}), **_read_school(folder)}
    config.setdefault("carpeta_escenarios", ESCENARIOS_FOLDER)
    config.setdefault("carpeta_reportes", REPORTES_FOLDER)
    total = sum(config["colegio"]["como_llegan"].values())
    if total != EXPECTED_PERCENT_TOTAL:
        print(f'Aviso: los porcentajes de "como_llegan" suman {total}, no 100.')
    return config


def _locate_map(map_name, config_path):
    if os.path.isfile(map_name):
        return os.path.dirname(map_name) or ".", map_name
    folder = map_name if os.path.isdir(map_name) else os.path.join(MAPS_FOLDER, map_name)
    if not os.path.isdir(folder):
        available = []
        if os.path.isdir(MAPS_FOLDER):
            available = sorted(d for d in os.listdir(MAPS_FOLDER)
                               if os.path.isdir(os.path.join(MAPS_FOLDER, d)))
        sys.exit(f"No encuentro el mapa '{map_name}'. Revisa \"mapa\" en {config_path}.\n"
                 f"Mapas disponibles en {MAPS_FOLDER}/: {', '.join(available) or 'ninguno'}")
    networks = sorted(path for pattern in NETWORK_PATTERNS
                      for path in glob.glob(os.path.join(folder, pattern)))
    if len(networks) != 1:
        sys.exit(f"En {folder} tiene que haber una sola red (*.net.xml o *.net.xml.gz) "
                 f"y hay {len(networks)}: {', '.join(networks) or '-'}")
    return folder, networks[0]


def _read_school(folder):
    path = os.path.join(folder, SCHOOL_DATA_FILE)
    if not os.path.isfile(path):
        sys.exit(f"Falta {path} con los datos de la escuela. Ejemplo:\n{SCHOOL_EXAMPLE}")
    with open(path, encoding="utf-8") as f:
        school = json.load(f)

    errors = []
    if not isinstance(school.get("alumnos"), int) or school["alumnos"] <= 0:
        errors.append('"alumnos" tiene que ser un numero entero mayor que 0')
    gates = school.get("puertas")
    if not gates:
        errors.append('falta "puertas" (al menos una)')
    for i, gate in enumerate(gates or [], 1):
        if not (isinstance(gate.get("calle"), str) and len(gate.get("entre", [])) == 2
                and gate.get("porcentaje", 0) > 0):
            errors.append(f'la puerta {i} tiene que tener "calle", "entre" (dos calles) y "porcentaje" > 0')
    if errors:
        sys.exit(f"Revisa {path}:\n  - " + "\n  - ".join(errors) + f"\nEjemplo:\n{SCHOOL_EXAMPLE}")

    total = sum(gate["porcentaje"] for gate in gates)
    if total != EXPECTED_PERCENT_TOTAL:
        print(f"Aviso: los porcentajes de las puertas en {path} suman {total}, no 100.")
    return school


def map_name(config):
    return os.path.basename(os.path.dirname(config["mapa"]))


def new_scenario_folder(config):
    folder = os.path.join(config["carpeta_escenarios"],
                          f"{map_name(config)}_{datetime.now().strftime(TIMESTAMP_FORMAT)}")
    os.makedirs(folder, exist_ok=True)
    return folder


def scenario_folder(config):
    return config.get("carpeta_sesion") or new_scenario_folder(config)


def last_scenario_folder(config):
    base = config["carpeta_escenarios"]
    prefix = f"{map_name(config)}_"
    if not os.path.isdir(base):
        return None
    folders = [f for f in os.listdir(base)
               if f.startswith(prefix) and os.path.isdir(os.path.join(base, f))
               and os.path.isfile(os.path.join(base, f, ROUTES_FILE))]
    return os.path.join(base, max(folders)) if folders else None


def temporal_folder(folder):
    path = os.path.join(folder, TEMPORAL_SUBFOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def remove_temporal(folder):
    shutil.rmtree(os.path.join(folder, TEMPORAL_SUBFOLDER), ignore_errors=True)


def sumo_bin(name):
    home = os.environ.get("SUMO_HOME")
    return os.path.join(home, "bin", name) if home else name


def sumo_options(network, routes, traffic_lights, duration_s, seed):
    return [
        "--net-file", os.path.abspath(network),
        "--route-files", os.path.abspath(routes),
        "--additional-files", os.path.abspath(traffic_lights),
        "--end", str(int(duration_s)),
        "--seed", str(seed),
        "--time-to-teleport", TELEPORT_TIME,
        "--device.rerouting.probability", "1",
        "--device.rerouting.period", REROUTING_PERIOD,
        "--ignore-route-errors", "true",
        "--no-step-log", "true",
        "--no-warnings", "true",
    ]


def simulate(network, routes, traffic_lights, duration_s, seed, temporal):
    with tempfile.TemporaryDirectory(dir=temporal) as folder:
        stats_path = os.path.join(folder, "stats.xml")
        command = [sumo_bin("sumo"), *sumo_options(network, routes, traffic_lights, duration_s, seed),
                   "--statistic-output", stats_path, "--duration-log.statistics", "true"]
        process = subprocess.run(command, capture_output=True, text=True)
        if process.returncode != 0:
            raise RuntimeError("SUMO fallo:\n" + process.stderr)
        root = ET.parse(stats_path).getroot()

    groups = [root.find("vehicleTripStatistics"), root.find("bikeTripStatistics")]
    groups = [g for g in groups if g is not None and int(g.get("count")) > 0]
    arrived = sum(int(g.get("count")) for g in groups)

    def average(attribute):
        return sum(int(g.get("count")) * float(g.get(attribute)) for g in groups) / max(1, arrived)

    return {
        "loaded": int(root.find("vehicles").get("loaded")),
        "arrived": arrived,
        "teleports": int(root.find("teleports").get("total")),
        "waiting_time": average("waitingTime"),
        "time_loss": average("timeLoss"),
        "duration": average("duration"),
    }


def save_scenarios(network, routes, original, optimized, duration_s, seed, folder):
    configs = []
    for name, traffic_lights in [("original", original), ("optimizado", optimized)]:
        config_path = os.path.abspath(os.path.join(folder, name + ".sumocfg"))
        subprocess.run([sumo_bin("sumo"),
                        *sumo_options(network, routes, traffic_lights, duration_s, seed),
                        "--save-configuration", config_path], check=True)
        configs.append(config_path)
    return configs


def show_side_by_side(configs, folder):
    width, height = _screen_size()
    half = width // 2
    view_path = os.path.abspath(os.path.join(folder, "vista.xml"))
    with open(view_path, "w", encoding="utf-8") as f:
        f.write('<viewsettings><scheme name="real world"/></viewsettings>\n')

    for i, config_path in enumerate(configs):
        subprocess.Popen([sumo_bin("sumo-gui"), "-c", config_path, "--gui-settings-file", view_path,
                          "--start", "true", "--delay", GUI_DELAY,
                          "--window-pos", f"{i * half},0",
                          "--window-size", f"{half},{height - GUI_MARGIN}"])


def _screen_size():
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        size = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return size
    except Exception:
        return DEFAULT_SCREEN_SIZE