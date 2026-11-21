# Simulación y optimización de tráfico mediante algoritmos genéticos

Proyecto de simulación y optimización de tráfico vehicular desarrollado utilizando Python y SUMO.

El trabajo fue aceptado en el CONAIISI (Congreso Nacional de Ingeniería en Sistemas de Información).

📄 **[Leer el paper](https://drive.google.com/file/d/1-twNlnxBFP5kp-pBiewyu2JYnHh9rj6t/view?usp=sharing)**

## Requisitos

- Python 3
- SUMO

## Preparación

### 1. Obtener el mapa

Descargar el mapa de la zona a simular utilizando el OSM Web Wizard de SUMO.

Guardar el mapa generado dentro de la carpeta `/mapas`.

El repositorio incluye un mapa de ejemplo que puede utilizarse para ejecutar las simulaciones.

### 2. Configurar la simulación

Modificar el archivo `config.json` para establecer el mapa y los parámetros de la simulación.

La configuración incluida corresponde a la utilizada en el trabajo presentado.

## Ejecución

### Ejecutar una optimización

Para realizar una única optimización utilizando la semilla definida en `config.json`, ejecutar:

```bash
python traffic_generator.py
python genetic_algorithm.py
```

Los scripts deben ejecutarse en el orden indicado.

### Ejecutar múltiples corridas

Para realizar varias corridas y generar un informe con los resultados obtenidos, ejecutar:

```bash
python runs_report.py
```

## Tecnologías utilizadas

- **Python 3** — Implementación de la lógica de simulación y optimización.
- **SUMO** — Simulación de tráfico vehicular.
- **OpenStreetMap** — Obtención de redes viales.
- **Algoritmos genéticos** — Búsqueda y optimización de configuraciones de tráfico.