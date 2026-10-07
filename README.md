# roofTool

Potentiel photovoltaïque des toitures de France métropolitaine, bâtiment par
bâtiment.

roofTool lit le LiDAR HD et la BD TOPO de l'IGN, et les séries météo de PVGIS
(SARAH-3). Pour une zone (adresse, commune, département, région, France ou zone
tracée), il écrit un GeoPackage avec une ligne par bâtiment : surface posable,
irradiation reçue, puissance crête, production annuelle et trimestrielle, part
de ciel visible, protections patrimoniales.

## Méthode

1. Bâtiments BD TOPO et dalles LiDAR HD de la zone, lus sur la Géoplateforme
   (WFS, WMS).
2. Pente et orientation de chaque pixel de toit (0,5 m) : plan ajusté sur le
   MNS. Murs, rives et pentes de plus de 45° écartés.
3. Horizon de chaque pixel : bâtiments et végétation jusqu'à 100 m (MNS),
   relief jusqu'à 20 km (MNT).
4. Irradiance : tables météo par cellule de 0,10° (0,05° là où l'irradiation
   varie), transposition de Perez, direct et diffus masqués par l'horizon.
5. Production : température des modules (Faiman), rendement 0,22, PR hors
   température 0,79, part du toit équipée (0,60 sur les pans inclinés).
6. Agrégation par bâtiment, filtres de surface et de hauteur, marquage des
   zones protégées.

Détail de la méthode, des limites et des colonnes : [a_propos.md](a_propos.md),
aussi affiché dans l'onglet « À propos ».

## Installation

```bash
conda env create -f environment.yml
conda activate stage-lidar
```

Données : télécharger `data.zip` depuis la release GitHub et le décompresser à
la racine du dépôt. Il contient `data/tables` (tables météo), `data/contours`
(contours des cartes) et `data/assets` (icône). Les dossiers de travail sont
créés au lancement.

## Utilisation

```bash
python interface.py
```

Choisir une zone dans l'onglet « Calcul », puis lancer. Les résultats sont
écrits dans `data/processed/gpkg/`. Les onglets « Carte des résultats » et
« Info fichiers » les affichent.

## Exécutable

```bash
conda activate stage-lidar
pyinstaller main.spec
```

L'environnement doit être activé, sinon des bibliothèques de GDAL et PROJ
manquent. Les données doivent être en place : elles sont embarquées. Construire
sur l'OS visé (Windows ou Linux). Résultat : dossier `dist/roofTool`.

## Tables météo

Les tables sont fournies dans `data.zip`. Pour construire les tables absentes
d'une zone, choisie au terminal :

```bash
python -m src.irradiance.meteo.main_meteo
python -m src.irradiance.meteo.raffiner
```

Le premier construit les cellules de 0,10°, le second les sous-cellules de
0,05°.
