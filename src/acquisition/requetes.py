import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
import pandas as pd
import geopandas as gpd

from src import config

_local = threading.local()


def session():
    """
    Session HTTP propre au fil courant.
    --------
    @return requests.Session reutilisee par ce fil
    """
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def lireWFS(params):
    """
    Requete WFS GetFeature, avec config.N_ESSAIS_WFS essais.
    --------
    @param[in] params : parametres de la requete WFS

    @return GeoDataFrame du resultat ; leve RuntimeError apres tous les echecs
    """
    n, pause = config.N_ESSAIS_WFS, config.PAUSE_WFS
    err = ""
    for essai in range(1, n + 1):
        try:
            contenu = session().get(config.WFS, params=params, timeout=120).content
            if b"FeatureCollection" in contenu[:300]:
                return gpd.read_file(contenu)
            err = contenu[:200].decode("utf-8", "replace")
        except Exception as e:
            err = str(e)
        if essai < n:
            time.sleep(pause * essai)
    raise RuntimeError(f"WFS a echoue {n}x : {err}")


def compter(params):
    """
    Nombre d'entites d'une requete WFS (numberMatched), avec config.N_ESSAIS_WFS essais.
    --------
    @param[in] params : parametres de la requete WFS

    @return nombre d'entites ; leve RuntimeError apres tous les echecs
    """
    n, pause = config.N_ESSAIS_WFS, config.PAUSE_WFS
    err = ""
    for essai in range(1, n + 1):
        try:
            r = session().get(config.WFS, params={**params, "COUNT": 1}, timeout=120)
            j = r.json()
            if "numberMatched" in j:
                return j["numberMatched"]
            err = r.text[:200]
        except Exception as e:
            err = str(e)
        if essai < n:
            time.sleep(pause * essai)
    raise RuntimeError(f"WFS (comptage) a echoue {n}x : {err}")


def paginer(params, cle, on_log=print):
    """
    Pagination WFS complete : SORTBY obligatoire, pages incompletes redemandees, effectif
    recompte a chaque essai.
    --------
    @param[in] params : parametres WFS (SORTBY et COUNT compris, sans STARTINDEX)
    @param[in] cle    : colonne d'identifiant unique, pour ecarter les doublons
    @param[in] on_log : callback (message) pour les avertissements (defaut print)

    @return GeoDataFrame de toutes les entites (vide si aucune) ; leve RuntimeError si incomplet
    """
    if "SORTBY" not in params:
        raise ValueError("paginer exige un SORTBY (pagination deterministe)")

    pas = params["COUNT"]
    n = compter(params)
    if n == 0:
        return gpd.GeoDataFrame()

    pages = {}
    for essai in range(1, config.N_ESSAIS_WFS + 1):
        creuses = [s for s in range(0, n, pas) if len(pages.get(s, ())) < min(pas, n - s)]
        if not creuses:
            break
        if essai > 1:
            on_log(f"[avertissement] WFS {params['TYPENAME']} : {len(creuses)} page(s) "
                   f"incomplete(s), nouvel essai ({essai}/{config.N_ESSAIS_WFS})")
        with ThreadPoolExecutor(max_workers=config.N_THREADS) as ex:
            for s, g in zip(creuses, ex.map(
                    lambda s: lireWFS({**params, "STARTINDEX": s}), creuses)):
                pages[s] = g
        n = compter(params)

    tout = pd.concat(pages.values(), ignore_index=True).drop_duplicates(cle)
    if len(tout) < n:
        raise RuntimeError(f"WFS {params['TYPENAME']} : pagination incomplete, "
                           f"{len(tout)}/{n} entites apres {config.N_ESSAIS_WFS} essais")
    return tout
