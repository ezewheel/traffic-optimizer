# 🚦 Simulación y optimización de tráfico

Proyecto de simulación de tráfico utilizando **SUMO** y **Python**, con un algoritmo genético para optimizar la circulación vehicular.

## 📋 Requisitos

- Python 3
- SUMO

## ⚙️ Preparación

### 1. Descargar un mapa

Descargar el mapa de la zona a simular utilizando el **OSM Web Wizard de SUMO**.

Guardar el mapa generado dentro de la carpeta `/mapas`.

### 2. Configurar la simulación

Modificar el archivo `config.json` para definir el mapa y los parámetros de la simulación.

La configuración actual corresponde a la utilizada para realizar el informe.

## ▶️ Ejecución

### Una sola optimización

Para ejecutar una optimización utilizando la semilla definida en `config.json`, correr los siguientes comandos en orden:

```bash
python traffic_generator.py
python genetic_algorithm.py
```

### Varias corridas y generación de informe

Para ejecutar múltiples corridas y generar un informe con los resultados obtenidos:

```bash
python runs_report.py
```

---

## 🧬 Algoritmo genético

El proyecto utiliza un algoritmo genético para evaluar distintas configuraciones de tráfico y buscar soluciones que mejoren la circulación vehicular dentro de la simulación.

## 🛠️ Tecnologías utilizadas

- **Python 3** — Implementación del proyecto.
- **SUMO** — Simulación de tráfico.
- **OpenStreetMap** — Obtención de mapas y redes viales.
- **Algoritmo genético** — Optimización de la configuración del tráfico.
