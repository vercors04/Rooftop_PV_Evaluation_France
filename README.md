# roofTool

Photovoltaic potential of rooftops in metropolitan France, building by
building.

roofTool reads IGN's LiDAR HD and BD TOPO, and PVGIS weather series
(SARAH-3). For an area (address, municipality, department, region, France or
drawn area), it writes a GeoPackage with one row per building: installable
area, received irradiation, peak power, annual and quarterly production,
visible sky fraction, heritage protections.

## Method

1. BD TOPO buildings and LiDAR HD tiles of the area, read from the
   Géoplateforme (WFS, WMS).
2. Slope and orientation of each roof pixel (0.5 m): plane fitted on the
   DSM. Walls, edges and slopes over 45° discarded.
3. Horizon of each pixel: buildings and vegetation up to 100 m (DSM),
   terrain up to 20 km (DTM).
4. Irradiance: weather tables per 0.10° cell (0.05° where the irradiation
   varies), Perez transposition, direct and diffuse masked by the horizon.
5. Production: module temperature (Faiman), efficiency 0.22, PR excluding
   temperature 0.79, equipped share of the roof (0.60 on pitched sections).
6. Aggregation per building, area and height filters, marking of
   protected zones.

Details of the method, limits and columns: [a_propos.md](a_propos.md),
also displayed in the "À propos" tab.

## Installation

```bash
conda env create -f environment.yml
conda activate stage-lidar
```

Data: download `data.zip` from the GitHub release and unzip it at the root of
the repository. It contains `data/tables` (weather tables), `data/contours`
(map outlines) and `data/assets` (icon). The working folders are created at
launch.

## Usage

```bash
python interface.py
```

Choose an area in the "Calcul" tab, then launch. The results are written to
`data/processed/gpkg/`. The "Carte des résultats" and "Info fichiers" tabs
display them.

## Executable

```bash
conda activate stage-lidar
pyinstaller main.spec
```

The environment must be activated, otherwise GDAL and PROJ libraries are
missing. The data must be in place: they are embedded. Build on the target OS
(Windows or Linux). Result: `dist/roofTool` folder.

## Weather tables

The tables are provided in `data.zip`. To build the tables missing for an area,
chosen in the terminal:

```bash
python -m src.irradiance.meteo.main_meteo
python -m src.irradiance.meteo.raffiner
```

The first builds the 0.10° cells, the second the 0.05° sub-cells.
