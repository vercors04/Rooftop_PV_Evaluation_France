import os

import geopandas as gpd
from shapely.geometry import Point

from src.acquisition.requetes import lireWFS, session
from src.tuile.donnees_dalle import enMetropole
from src import config


def metropole(gdf):
    """
    Entites dont le point interieur tombe dans le domaine du Lambert 93.
    --------
    @param[in] gdf : GeoDataFrame WGS84

    @return GeoDataFrame filtre
    """
    if gdf.empty:
        return gdf
    return gdf[[enMetropole(p.y, p.x) for p in gdf.geometry.representative_point()]]


def zone(echelle, nom_zone, code_dep=None):
    """
    Emprise de la zone d'etude.
    --------
    @param[in] echelle  : 'adresse', 'commune', 'departement', 'region', 'nationale' ou
                          'polygone' (zone tracee)
    @param[in] nom_zone : adresse, nom du territoire ou nom de la zone tracee
    @param[in] code_dep : code departement, pour 'commune'

    @return polygone shapely WGS84 (cercle de config.RAYON_ADRESSE_M pour une adresse,
            metropole seule pour 'nationale') ; None si introuvable
    """
    if echelle == "polygone":
        chemin = os.path.join(config.DIR_GEOJSON, f"{nom_zone}.geojson")
        if not os.path.exists(chemin):
            return None
        gdf = gpd.read_file(chemin).to_crs(4326)
        return None if gdf.empty else gdf.geometry.iloc[0]

    if echelle == "nationale":
        params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
                  "TYPENAME": "BDTOPO_V3:region", "OUTPUTFORMAT": "application/json",
                  "COUNT": 100}
        gdf = metropole(lireWFS(params))
        return None if gdf.empty else gdf.geometry.union_all()

    if echelle == "adresse":
        feats = session().get(config.GEOCODAGE, params={"q": nom_zone, "limit": 1},
                              timeout=60).json()["features"]
        if not feats:
            return None
        point = gpd.GeoSeries([Point(feats[0]["geometry"]["coordinates"])], crs=4326)
        return point.to_crs(2154).buffer(config.RAYON_ADRESSE_M).to_crs(4326).iloc[0]

    nom_zone = nom_zone.replace("'", "''")
    cql = {
        "commune":     f"nom_officiel ILIKE '{nom_zone}' AND code_insee_du_departement = '{code_dep}'",
        "departement": f"nom_officiel ILIKE '{nom_zone}' OR code_insee = '{nom_zone}'",
        "region":      f"nom_officiel ILIKE '{nom_zone}'",
    }[echelle]

    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
              "TYPENAME": f"BDTOPO_V3:{echelle}", "OUTPUTFORMAT": "application/json",
              "CQL_FILTER": cql}
    gdf = lireWFS(params)
    return None if gdf.empty else gdf.geometry.iloc[0]


def listeDepartements(echelle, nom_zone):
    """
    Departements metropolitains d'une region ou de la France.
    --------
    @param[in] echelle  : 'region' ou 'nationale'
    @param[in] nom_zone : nom de la region (ignore pour 'nationale')

    @return liste triee des noms officiels ; [] si region introuvable
    """
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
              "TYPENAME": "BDTOPO_V3:departement", "OUTPUTFORMAT": "application/json",
              "COUNT": 200}
    gdf = metropole(lireWFS(params))
    if echelle == "nationale":
        return sorted(gdf["nom_officiel"].tolist())

    region_poly = zone("region", nom_zone)
    if region_poly is None:
        return []
    dans_region = gdf[gdf.geometry.representative_point().within(region_poly)]
    return sorted(dans_region["nom_officiel"].tolist())
