import os
import time

import numpy as np
import pandas as pd
import requests

from src import config


CLES_PROFILS = ("m_b", "m_d", "m_bb", "m_bd", "m_dd", "t_pond", "v_pond", "v_var",
                "f1_pond", "f2_pond")


def transpAgr(bhi, dhi, lat, lon):
    """
    Transpose chaque pas de temps (Perez), puis moyenne par (mois, heure).
    --------
    @param[in] bhi, dhi : Series (W/m2, plan horizontal), DatetimeIndex UTC
    @param[in] lat, lon : centre de la cellule (deg WGS84)

    @return B, D     : (n_alphas, n_betas, 12, 24), direct et diffus (ciel + sol), W/m2
    @return SAZ, SEL : (12, 24), azimut et elevation apparente moyens du soleil (deg)
    """
    import pvlib
    times = bhi.index
    ghi = (bhi + dhi).clip(lower=0)

    sp = pvlib.solarposition.get_solarposition(times, lat, lon)
    dni = pvlib.irradiance.dni(ghi, dhi, sp["apparent_zenith"]).fillna(0)
    dni_extra = pvlib.irradiance.get_extra_radiation(times)
    airmass = pvlib.atmosphere.get_relative_airmass(sp["apparent_zenith"])
    cles = [times.month, times.hour]

    B = np.zeros((len(config.ALPHAS), len(config.BETAS), 12, 24), np.float32)
    D = np.zeros_like(B)
    for i, a in enumerate(config.ALPHAS):
        for j, b in enumerate(config.BETAS):
            poa = pvlib.irradiance.get_total_irradiance(
                surface_tilt=b, surface_azimuth=a,
                solar_zenith=sp["apparent_zenith"], solar_azimuth=sp["azimuth"],
                dni=dni, ghi=ghi, dhi=dhi,
                dni_extra=dni_extra, airmass=airmass, albedo=config.ALBEDO_TABLES, model="perez")
            direct = poa["poa_direct"].fillna(0)
            diffus = (poa["poa_sky_diffuse"] + poa["poa_ground_diffuse"]).fillna(0)
            B[i, j] = profMH(direct, cles)
            D[i, j] = profMH(diffus, cles)

    SAZ = profMH(sp["azimuth"], cles)
    SEL = profMH(sp["apparent_elevation"], cles)
    return B, D, SAZ, SEL


def profMH(serie, cles, how="mean"):
    """
    Reduction par (mois, heure UTC), tableau (12, 24), bins absents a 0.
    --------
    @param[in] serie : Series indexee par un DatetimeIndex UTC
    @param[in] cles  : liste de Series (ex: [times.month, times.hour]) pour grouper la serie
    @param[in] how   : reduction appliquee a chaque groupe ("mean", "sum", "count")

    @return out : tableau (12, 24) de la valeur reduite par (mois, heure)
    """
    g = getattr(serie.groupby(cles), how)()
    out = np.zeros((12, 24), np.float32)
    for (m, h), v in g.items():
        out[int(m) - 1, int(h)] = v
    return out


def coefsPerez(bhi, dhi, lat, lon):
    """
    Coefficients de Perez F1 (circumsolaire) et F2 (bande d'horizon), heure par heure, lus sur
    un plan vertical.
    --------
    @param[in] bhi, dhi : Series horaires direct et diffus horizontaux (W/m2), index UTC
    @param[in] lat, lon : centre de la cellule (deg WGS84)

    @return f1, f2 : Series horaires, meme index
    """
    import pvlib
    idx = bhi.index
    sp = pvlib.solarposition.get_solarposition(idx, lat, lon)
    zen = sp["zenith"]
    cosz = np.cos(np.radians(zen)).clip(lower=0.01)
    c = pvlib.irradiance.perez(
        90.0, 180.0, dhi, (bhi / cosz).clip(upper=1400.0),
        pvlib.irradiance.get_extra_radiation(idx), zen, sp["azimuth"],
        pvlib.atmosphere.get_relative_airmass(zen), return_components=True)
    d = dhi.where(dhi > 0.0)
    f1 = (1.0 - 2.0 * c["poa_isotropic"] / d).fillna(0.0).clip(0.0, 1.0)
    f2 = (c["poa_horizon"] / d).fillna(0.0).clip(-1.0, 1.0)
    return f1, f2


def profilsCellule(bhi, dhi, temp_air, wind_speed, lat, lon):
    """
    Profils (mois, heure) des heures reelles : moments d'ordre 2 de l'irradiance horizontale,
    temperature et vent ponderes, coefficients de Perez.
    --------
    @param[in] bhi, dhi   : Series horaires direct et diffus horizontaux (W/m2), index UTC
    @param[in] temp_air   : Series horaire de temperature de l'air a 2 m (degC)
    @param[in] wind_speed : Series horaire de vent a 10 m (m/s)
    @param[in] lat, lon   : centre de la cellule (deg WGS84)

    @return dict des 10 profils (12, 24) float32, cles de CLES_PROFILS
    """
    ghi  = (bhi + dhi).clip(lower=0)
    cles = [ghi.index.month, ghi.index.hour]

    s_g  = profMH(ghi, cles, "sum")
    avec = s_g > 0
    den  = np.where(avec, s_g, 1.0)

    s_gg  = profMH(ghi * ghi, cles, "sum")
    avec2 = s_gg > 0
    den2  = np.where(avec2, s_gg, 1.0)

    v_pond = np.where(avec2, profMH(ghi*ghi*wind_speed, cles, "sum") / den2,
                      profMH(wind_speed, cles))
    v_car  = np.where(avec2, profMH(ghi*ghi*wind_speed*wind_speed, cles, "sum") / den2,
                      v_pond * v_pond)

    prof = {
        "m_b":    profMH(bhi, cles),
        "m_d":    profMH(dhi, cles),
        "m_bb":   profMH(bhi * bhi, cles),
        "m_bd":   profMH(bhi * dhi, cles),
        "m_dd":   profMH(dhi * dhi, cles),
        "t_pond": np.where(avec, profMH(ghi * temp_air, cles, "sum") / den,
                           profMH(temp_air, cles)),
        "v_pond": v_pond,
        "v_var":  np.maximum(v_car - v_pond * v_pond, 0.0),
    }

    f1, f2 = coefsPerez(bhi, dhi, lat, lon)
    s_d = profMH(dhi, cles, "sum")
    den_d = np.where(s_d > 0, s_d, 1.0)
    prof["f1_pond"] = np.where(s_d > 0, profMH(dhi * f1, cles, "sum") / den_d, 0.0)
    prof["f2_pond"] = np.where(s_d > 0, profMH(dhi * f2, cles, "sum") / den_d, 0.0)
    return {k: v.astype(np.float32) for k, v in prof.items()}


def requetePvgis(service, params, delai):
    """
    Requete a l'API PVGIS, avec config.N_ESSAIS essais a delai doublant.
    --------
    @param[in] service : point d'entree (ex: "seriescalc")
    @param[in] params  : parametres de la requete
    @param[in] delai   : delai d'attente de la reponse (s)

    @return cle "outputs" de la reponse JSON ; None si PVGIS refuse le point (code 400) ; leve la
            derniere exception apres tous les echecs
    """
    for essai in range(1, config.N_ESSAIS + 1):
        try:
            r = requests.get(config.URL + service, timeout=delai, params=params)
            if r.status_code == 400:
                return None
            r.raise_for_status()
            return r.json()["outputs"]
        except (requests.RequestException, ValueError, KeyError):
            if essai == config.N_ESSAIS:
                raise
            time.sleep(min(config.PAUSE_DL * 2 ** (essai - 1), 300))


def serieBrute(lat, lon):
    """
    Series horaires PVGIS (SARAH-3, 2005-2023) du plan horizontal (voir requetePvgis).
    --------
    @param[in] lat, lon : point (deg WGS84)

    @return bhi, dhi, temp_air, wind_speed : Series horaires, DatetimeIndex UTC ; leve une
            exception si PVGIS echoue ou n'a pas de donnee au point
    """
    params = {"lat": lat, "lon": lon, "startyear": 2005, "endyear": 2023,
              "raddatabase": "PVGIS-SARAH3", "components": 1,
              "angle": 0, "aspect": -180, "usehorizon": 0, "outputformat": "json"}
    sortie = requetePvgis("seriescalc", params, 300)
    if sortie is None:
        raise ValueError(f"PVGIS n'a pas de donnee en ({lat}, {lon})")
    heures = sortie["hourly"]
    index = pd.to_datetime([e["time"] for e in heures], format="%Y%m%d:%H%M", utc=True)
    serie = lambda cle: pd.Series([e[cle] for e in heures], index=index, dtype=float)
    return (serie("Gb(i)").clip(lower=0),
            (serie("Gd(i)") + serie("Gr(i)")).clip(lower=0),
            serie("T2m"), serie("WS10m"))


def irradiationAnnuelle(lat, lon):
    """
    Irradiation annuelle moyenne PVGIS (SARAH-3, 2005-2023, sans horizon) du plan horizontal
    et du plan d'inclinaison optimale (voir requetePvgis).
    --------
    @param[in] lat, lon : point (deg WGS84)

    @return h, h_opt : kWh/m2/an ; None si PVGIS n'a pas de donnee au point (en mer)
    """
    params = {"lat": lat, "lon": lon, "startyear": 2005, "endyear": 2023,
              "raddatabase": "PVGIS-SARAH3", "horirrad": 1, "optrad": 1, "usehorizon": 0,
              "outputformat": "json"}
    sortie = requetePvgis("MRcalc", params, 120)
    if sortie is None:
        return None
    mois = sortie["monthly"]
    ans = len({m["year"] for m in mois})
    return sum(m["H(h)_m"] for m in mois) / ans, sum(m["H(i_opt)_m"] for m in mois) / ans


def cheminTable(lat, lon, fine=False):
    """
    Chemin de la table d'une cellule ou d'une sous-cellule.
    --------
    @param[in] lat, lon : centre de la cellule ou de la sous-cellule
    @param[in] fine     : True pour une sous-cellule

    @return chemin du .npz (ex: data/tables/lat_46/table_46.50_0.30.npz)
    """
    sous = f"lat_{int(lat)}"
    if fine:
        return os.path.join(config.DOSSIER_FIN, sous, f"table_{lat + 0.0:.3f}_{lon + 0.0:.3f}.npz")
    return os.path.join(config.DOSSIER, sous, f"table_{lat + 0.0:.2f}_{lon + 0.0:.2f}.npz")


def sousCellules(lat, lon):
    """
    Centres des quatre sous-cellules d'une cellule, un pixel SARAH-3 chacune.
    --------
    @param[in] lat, lon : centre de la cellule (multiples de PAS)

    @return liste de 4 tuples (lat, lon)
    """
    d = config.PAS_FIN / 2
    return [(round(lat + a, 3), round(lon + b, 3)) for a in (-d, d) for b in (-d, d)]


def surGrille(v):
    """
    Coordonnee ramenee au centre de cellule le plus proche (multiple de PAS).
    --------
    @param[in] v : latitude ou longitude (deg)

    @return coordonnee arrondie a 2 decimales
    """
    return round(round(v / config.PAS) * config.PAS, 2)


def celluleMeteo(lat, lon):
    """
    Table d'un point : sa sous-cellule si elle a ete construite, sinon sa cellule.
    --------
    @param[in] lat, lon : coordonnees quelconques (deg WGS84)

    @return lat_c, lon_c : centre de la table
    @return fine         : True pour une sous-cellule
    """
    la, lo = surGrille(lat), surGrille(lon)
    d = config.PAS_FIN / 2
    fla, flo = round(la + (d if lat >= la else -d), 3), round(lo + (d if lon >= lo else -d), 3)
    if os.path.exists(cheminTable(fla, flo, fine=True)):
        return fla, flo, True
    return la, lo, False


def tablesMeteo(points):
    """
    Tables meteo lues par des dalles, pour les metadonnees.
    --------
    @param[in] points : (lat, lon) des centres des dalles

    @return dict : pas des cellules et sous-cellules, nombre de dalles sur chacune
    """
    fines = sum(celluleMeteo(lat, lon)[2] for lat, lon in points)
    return {"pas_deg": config.PAS, "pas_fin_deg": config.PAS_FIN,
            "dalles_cellule": len(points) - fines, "dalles_sous_cellule": fines}


_cache = {}


def chargerTable(lat, lon):
    """
    Table meteo d'un point quelconque, en cache : sa sous-cellule si elle existe, sinon sa
    cellule.
    --------
    @param[in] lat, lon : point (deg WGS84)

    @return B, D     : (n_alphas, n_betas, 12, 24), direct et diffus (ciel + sol), W/m2
    @return SAZ, SEL : (12, 24), azimut et elevation du soleil (deg)
    @return profils  : dict des 10 profils (12, 24) de CLES_PROFILS
    """
    la, lo, fine = celluleMeteo(lat, lon)

    if (la, lo) not in _cache:
        chemin = cheminTable(la, lo, fine)
        if not os.path.exists(chemin):
            raise FileNotFoundError(f"Table meteo absente ({la}, {lo}) : {chemin} ; "
                                    f"construire avec main_meteo.")
        with np.load(chemin) as d:
            _cache[(la, lo)] = (d["B"].astype(np.float32), d["D"].astype(np.float32),
                                d["SAZ"], d["SEL"], {cle: d[cle] for cle in CLES_PROFILS})

    return _cache[(la, lo)]
