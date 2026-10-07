import os
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
from shapely.geometry import box
from shapely.prepared import prep

from src.irradiance.meteo.grille_fct import (serieBrute, transpAgr, profilsCellule, cheminTable,
                                             sousCellules, irradiationAnnuelle, surGrille)
from src import config


def grilleCellules(polygone):
    """
    Centres des cellules meteo (multiples de PAS) dont la cellule intersecte le polygone.
    --------
    @param[in] polygone : emprise de la zone (shapely, WGS84)

    @return liste de tuples (lat, lon), alignes sur la meme grille que chargerTable
    """
    minx, miny, maxx, maxy = polygone.bounds
    lats = np.round(np.arange(surGrille(miny), surGrille(maxy) + config.PAS/2, config.PAS), 2)
    lons = np.round(np.arange(surGrille(minx), surGrille(maxx) + config.PAS/2, config.PAS), 2)
    dans = prep(polygone)
    h = config.PAS / 2
    return [(la, lo) for la in lats for lo in lons
            if dans.intersects(box(lo - h, la - h, lo + h, la + h))]


def construireCellule(lat, lon, fine=False):
    """
    Construit et ecrit la table d'une cellule ou d'une sous-cellule (npz compresse, B et D en
    float16).
    --------
    @param[in] lat, lon : centre (deg WGS84)
    @param[in] fine     : True pour une sous-cellule

    @return None
    """
    bhi, dhi, temp_air, wind_speed = serieBrute(lat, lon)
    B, D, SAZ, SEL = transpAgr(bhi, dhi, lat, lon)
    profils = profilsCellule(bhi, dhi, temp_air, wind_speed, lat, lon)
    chemin = cheminTable(lat, lon, fine)
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    tmp = chemin[:-4] + ".tmp.npz"
    np.savez_compressed(tmp, B=B.astype(np.float16), D=D.astype(np.float16),
                        SAZ=SAZ, SEL=SEL, **profils,
                        alphas=config.ALPHAS, betas=config.BETAS, lat=lat, lon=lon,
                        source="PVGIS-SARAH3 2005-2023, Perez")
    os.replace(tmp, chemin)


def construireAbsente(centre, fine=False):
    """
    Construit la table d'une cellule ou d'une sous-cellule si elle est absente.
    --------
    @param[in] centre : (lat, lon) du centre
    @param[in] fine   : True pour une sous-cellule

    @return (lat, lon, etat)
    """
    lat, lon = centre
    if os.path.exists(cheminTable(lat, lon, fine)):
        return (lat, lon, "deja faite")
    try:
        construireCellule(lat, lon, fine)
        return (lat, lon, "construite")
    except Exception as e:
        return (lat, lon, f"ECHEC : {e}")


def construireTables(centres, fine=False):
    """
    Construit en parallele les tables absentes, en affichant l'avancement puis le bilan.
    --------
    @param[in] centres : (lat, lon) des centres
    @param[in] fine    : True pour des sous-cellules

    @return liste des (lat, lon) en echec
    """
    ratees, bilan, t0 = [], {}, time.time()
    with ProcessPoolExecutor(max_workers=config.N_COEURS) as ex:
        for k, (lat, lon, etat) in enumerate(
                ex.map(construireAbsente, centres, [fine] * len(centres)), 1):
            print(f"[{k}/{len(centres)}] {lat:g}, {lon:g}  {etat}")
            cle = "ECHEC" if etat.startswith("ECHEC") else etat
            bilan[cle] = bilan.get(cle, 0) + 1
            if cle == "ECHEC":
                ratees.append((lat, lon))
    print(f"Termine en {time.time() - t0:.0f}s. "
          + ", ".join(f"{n} {k}" for k, n in sorted(bilan.items())))
    return ratees


def ecartsCellule(lat, lon):
    """
    Ecart relatif de chaque sous-cellule a sa cellule sur l'irradiation annuelle : le plus
    grand du plan horizontal et du plan d'inclinaison optimale.
    --------
    @param[in] lat, lon : centre de la cellule

    @return liste de 4 tuples (lat_fin, lon_fin, ecart) ; ecart NaN sans donnee PVGIS (en mer)
    """
    centre = irradiationAnnuelle(lat, lon)
    res = []
    for la, lo in sousCellules(lat, lon):
        sous = irradiationAnnuelle(la, lo) if centre else None
        ecart = (max(abs(sous[0] / centre[0] - 1), abs(sous[1] / centre[1] - 1)) if sous
                 else float("nan"))
        res.append((la, lo, ecart))
    return res
