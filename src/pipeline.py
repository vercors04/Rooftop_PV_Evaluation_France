import os
import time
import json
import shutil
import hashlib
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import numba
import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio

from src.tuile.raster import chargerDalle
from src.tuile.donnees_dalle import nomCoord, centreWGS84, tileBounds, enMetropole
from src.geometrie.extract_geom import extractGeom, makeMasques, eroderToit
from src.geometrie.horizon import compHZ
from src.geometrie.horizon_loin import mntRelief, hzLoin, reliefsZone
from src.irradiance.meteo.grille_fct import chargerTable, tablesMeteo
from src.irradiance.irr_calcul import irrPixels
from src.irradiance.pose_plat import posesBatiments, description
from src.agregation.agregation import agregerBatiment, mergeCleabs
from src.agregation.select import filtrer, hBat
from src.acquisition.telechargement import telechargerFichier, listeTelechargement, urlWms
from src.acquisition.batiments import batiments
from src.acquisition.protections import marquerProtections
from src.acquisition.zone import zone, listeDepartements
from src.acquisition.dalles import dalles
from src import config


def nomFichier(nom_zone, code_dep=None):
    """
    Nom de fichier d'une zone : espaces remplaces, caracteres interdits retires.
    --------
    @param[in] nom_zone : nom de la zone
    @param[in] code_dep : code departement ajoute en suffixe (None = aucun)

    @return nom sans extension
    """
    nom = "".join(c for c in nom_zone.replace(" ", "_") if c not in ',/:*?"<>|\\')
    return f"{nom}{code_dep or ''}"


def dossierReprise(nom_fichier):
    """
    Chemin du dossier des dalles calculees d'une zone.
    --------
    @param[in] nom_fichier : nom de la zone (voir nomFichier)

    @return chemin dans config.DIR_EN_COURS
    """
    return os.path.join(config.DIR_EN_COURS, nom_fichier)


def effacerReprise(nom_fichier):
    """
    Efface le dossier de reprise et les MNT de relief d'une zone.
    --------
    @param[in] nom_fichier : nom de la zone (voir nomFichier)

    @return None
    """
    shutil.rmtree(dossierReprise(nom_fichier), ignore_errors=True)
    for chemin in reliefsZone(nom_fichier):
        try:
            os.remove(chemin)
        except OSError:
            pass


def dossierTravail(nom_fichier, polygone, relief, on_log=print):
    """
    Dossier des dalles calculees de la zone (voir dossierReprise), vide s'il vient d'une autre
    version, d'une autre zone, d'un autre relief ou de reglages differents.
    --------
    @param[in] nom_fichier : nom de la zone (voir nomFichier)
    @param[in] polygone    : emprise de la zone (shapely, WGS84)
    @param[in] relief      : chemin du MNT de relief (voir mntRelief) ; None = sans relief
    @param[in] on_log      : callback (message)

    @return chemin du dossier
    """
    dossier = dossierReprise(nom_fichier)
    chemin = os.path.join(dossier, "etat.json")
    etat = {"version": config.VERSION,
            "zone": hashlib.sha1(polygone.wkb).hexdigest(),
            "relief": os.path.basename(relief) if relief else None,
            "parametres": {k: v for k, v in config.snapshot().items()
                           if k not in config.SANS_EFFET_DALLE}}
    if os.path.isdir(dossier):
        try:
            with open(chemin, encoding="utf-8") as f:
                meme = json.load(f) == etat
        except (OSError, ValueError):
            meme = False
        if not meme:
            on_log("dalles du calcul precedent ecartees : zone, relief ou reglages differents")
            shutil.rmtree(dossier)
    os.makedirs(dossier, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False)
    return dossier


def lireMetadonnees(chemin):
    """
    Metadonnees d'un gpkg de resultats, valeurs JSON decodees.
    --------
    @param[in] chemin : chemin du .gpkg

    @return dict {cle: valeur} ; leve une exception si le fichier est illisible
    """
    meta = pyogrio.read_info(chemin, layer="batiments")["dataset_metadata"] or {}
    lues = {}
    for cle, valeur in meta.items():
        try:
            lues[cle] = json.loads(valeur)
        except ValueError:
            lues[cle] = valeur
    return lues


def dallesManquantes(chemin):
    """
    Dalles manquantes d'un gpkg de resultats, lues dans ses metadonnees.
    --------
    @param[in] chemin : chemin du .gpkg

    @return liste de dict (nom, erreur) ; [] si complet ou illisible
    """
    try:
        return lireMetadonnees(chemin).get("dalles", {}).get("echecs", [])
    except Exception:
        return []


def traiterDalle(mns_path, mnt_path, gdf, relief=None, temps=None):
    """
    Traite une dalle : geometrie, masques, horizon, irradiance, agregation par batiment.
    --------
    @param[in] mns_path, mnt_path : chemins des rasters MNS / MNT IGN
    @param[in] gdf       : GeoDataFrame des batiments de la dalle (Lambert 93)
    @param[in] relief    : MNT grossier de la zone pour l'horizon lointain (voir
                           mntRelief) ; None = ombrage proche seul
    @param[in] temps     : dict optionnel rempli avec la duree de chaque etape

    @return out : GeoDataFrame, 1 ligne par batiment
    """
    mns_name = os.path.basename(mns_path)

    t0 = time.perf_counter()
    mns, mnt, meta, mns_large = chargerDalle(mns_path, mnt_path)
    pente, aspect, masque_bat, masque_haut, mnh = extractGeom(mns, mnt, gdf, meta)
    incline_or, incline, plat = makeMasques(pente, aspect, masque_bat)
    toiture = incline | plat
    utile = eroderToit(masque_bat, toiture,
                       int(round(config.RECUL_M / meta["resolution"])))
    if temps is not None: temps["geometrie"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    if mns_large.shape != mns.shape:
        m = (mns_large.shape[0] - mns.shape[0]) // 2
        toiture_large = np.zeros(mns_large.shape, np.bool_)
        toiture_large[m:m + toiture.shape[0], m:m + toiture.shape[1]] = toiture
    else:
        toiture_large = toiture
    horizon = compHZ(mns_large, toiture_large, meta["resolution"], config.N_DIRECTIONS,
                     0.0, config.DIST_MAX_M, config.CAP, config.PAS_RAYON_DIV)

    hz_loin = hzLoin(relief, meta, mns, toiture)
    if hz_loin is not None:
        horizon = np.maximum(horizon, hz_loin)
    if temps is not None: temps["horizon"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    lat, lon = centreWGS84(*nomCoord(mns_name))
    B, D, SAZ, SEL, profils = chargerTable(lat, lon)
    poses = posesBatiments(masque_bat, plat, pente, meta["resolution"], gdf,
                           tileBounds(mns_name))
    df  = irrPixels(masque_bat, pente, aspect, incline, incline_or, plat, utile,
                    meta["resolution"], B, D, SAZ, SEL, profils, horizon, lat, poses)
    if temps is not None: temps["irradiance"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    hauteur = hBat(mnh, masque_haut, 0.95)
    out = agregerBatiment(df, gdf, hauteur)
    if temps is not None: temps["agregation batiment"] = time.perf_counter() - t0

    return out


def runPipeline(echelle, nom_zone, code_dep=None, on_progress=None, on_log=print):
    """
    Traite la zone : dalles, calcul parallele, fusion, filtre, protections, ecriture du gpkg.
    Le dossier des dalles finies (voir dossierTravail) et le MNT de relief sont effaces quand
    toutes sont calculees ; sinon le gpkg porte les dalles manquantes et relancer la zone ne
    calcule qu'elles.
    --------
    @param[in] echelle, nom_zone, code_dep : definition de la zone (voir zone)
    @param[in] on_progress : callback (i, total) a chaque dalle finie (None = aucun)
    @param[in] on_log      : callback (message) pour les messages (defaut print)

    @return bilan : dict (fichier, total, echecs, moyennes_dalle, temps_globaux, batiments,
                    relief, protections) ; None si zone introuvable, hors metropole, sans
                    batiment ou sans dalle ; bilan reduit (fichier None) si aucune dalle
                    n'aboutit
    """
    t_total = time.time()
    t0 = time.time()
    polygone = zone(echelle, nom_zone, code_dep)
    if polygone is None:
        on_log("zone introuvable"); return None
    point = polygone.representative_point()
    if not enMetropole(point.y, point.x):
        on_log("zone hors metropole"); return None

    gdf_bati = batiments(polygone, on_log=on_log)
    if gdf_bati is None or gdf_bati.empty:
        on_log("aucun batiment"); return None
    t_bati = time.time() - t0

    nom_fichier = nomFichier(nom_zone, code_dep)
    zone_l93 = gpd.GeoDataFrame(geometry=[polygone], crs=4326).to_crs(2154)
    if echelle != "polygone":
        zone_l93.to_file(os.path.join(config.DIR_GEOJSON, f"{nom_fichier}.geojson"),
                         driver="GeoJSON")
    gpkg_path = os.path.join(config.OUT_DIR_PROCESSED, f"{nom_fichier}.gpkg")

    taches = []
    for nom_mnt, url_mnt, nom_mns, url_mns in listeTelechargement(dalles(polygone, on_log=on_log)):
        xmin, ymin, xmax, ymax = tileBounds(nom_mns)
        gdf_dalle = gdf_bati.cx[xmin:xmax, ymin:ymax]
        if not gdf_dalle.empty:
            taches.append((nom_mnt, url_mnt, nom_mns, url_mns, gdf_dalle))
    if not taches:
        on_log("aucune dalle LiDAR HD sous les batiments"); return None

    relief, erreur_relief = None, None
    try:
        relief = mntRelief(taches[0][1], zone_l93.total_bounds, nom_fichier, on_log)
    except Exception as e:
        erreur_relief = str(e)
        on_log(f"relief indisponible, horizon lointain ignore : {e}")
    taches = [t + (relief,) for t in taches]
    etat_relief = {"fichier": os.path.basename(relief) if relief else None,
                   "erreur": erreur_relief}

    total = len(taches)
    dossier = dossierTravail(nom_fichier, polygone, relief, on_log)
    chemins = [os.path.join(dossier, f"{t[2]}.pkl") for t in taches]
    t0 = time.time()
    temps_tous, manquantes = calculerDalles(taches, chemins, on_progress, on_log)
    t_traitement = time.time() - t0

    resultats = [r for r in (pd.read_pickle(c) for c in chemins if os.path.exists(c))
                 if not r.empty]
    if not resultats:
        on_log("aucun batiment traite")
        if not manquantes:
            effacerReprise(nom_fichier)
        return {"fichier": None, "total": total, "echecs": manquantes}

    t0 = time.time()
    g = pd.concat(resultats, ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry="geometry", crs=2154)
    n_avant = len(g)
    g = mergeCleabs(g);  n_merge  = len(g)
    g = filtrer(g);      n_filtre = len(g)
    cols = (["cleabs"] + config.ATTRS_BATI + ["pose_plat"]
            + [c for grp in config.SORTIE_GARDEES for c in config.GROUPES_SORTIE[grp]]
            + ["geometry"])
    g = g[[c for c in cols if c in g.columns]]
    g, protections = marquerProtections(g, polygone, on_log=on_log)

    centres = [centreWGS84(*nomCoord(t[2])) for t in taches]
    comptes = {"avant_merge_filtre": n_avant, "apres_merge": n_merge,
               "apres_filtre": n_filtre, "final": len(g)}
    metadonnees = {
        "version":       config.VERSION,
        "parametres":    json.dumps(config.snapshot(), ensure_ascii=False),
        "poses":         json.dumps(description([la for la, _ in centres]), ensure_ascii=False),
        "meteo":         json.dumps(tablesMeteo(centres), ensure_ascii=False),
        "zone":          json.dumps({"echelle": echelle, "nom_zone": nom_zone, "code_dep": code_dep},
                                    ensure_ascii=False),
        "batiments":     json.dumps(comptes, ensure_ascii=False),
        "dalles":        json.dumps({"total": total, "calculees": total - len(manquantes),
                                     "echecs": manquantes}, ensure_ascii=False),
        "relief":        json.dumps(etat_relief, ensure_ascii=False),
        "protections":   json.dumps(protections, ensure_ascii=False),
        "date_creation": datetime.now().isoformat(timespec="seconds"),
    }
    provisoire = os.path.join(dossier, f"{nom_fichier}.gpkg")
    g.to_file(provisoire, driver="GPKG", layer="batiments", dataset_metadata=metadonnees)
    os.replace(provisoire, gpkg_path)
    if manquantes:
        on_log(f"{len(manquantes)} dalle(s) manquante(s) apres deux essais : resultat "
               f"incomplet ; relancer la zone ne calculera qu'elles")
    else:
        effacerReprise(nom_fichier)
    t_ecriture = time.time() - t0

    def moyenne(cle):
        vals = [t[cle] for t in temps_tous if cle in t]
        return sum(vals) / len(vals) if vals else 0.0

    return {
        "fichier": f"{nom_fichier}.gpkg",
        "total":   total,
        "echecs":  manquantes,
        "moyennes_dalle": {
            "telechargement": moyenne("telechargement"),
            "geometrie":      moyenne("geometrie"),
            "horizon":        moyenne("horizon"),
            "irradiance":     moyenne("irradiance"),
            "agregation":     moyenne("agregation batiment"),
        },
        "temps_globaux": {
            "batiments":  t_bati,
            "traitement": t_traitement,
            "ecriture":   t_ecriture,
            "total":      time.time() - t_total,
        },
        "batiments":   comptes,
        "relief":      etat_relief,
        "protections": protections,
    }


def calculerDalles(taches, chemins, on_progress=None, on_log=print):
    """
    Calcule en parallele les dalles absentes du disque, avec les reglages courants ; une dalle
    en echec est retentee une fois, apres les autres. Chaque dalle finie est ecrite a son chemin.
    --------
    @param[in] taches      : dalles de la zone (voir traiterTache)
    @param[in] chemins     : fichier .pkl de chaque dalle, meme ordre
    @param[in] on_progress : callback (i, total) a chaque dalle du premier essai (None = aucun)
    @param[in] on_log      : callback (message)

    @return temps  : durees par etape des dalles calculees
    @return echecs : liste de dict (nom, erreur) des dalles en echec aux deux essais
    """
    destination = {t[2]: c for t, c in zip(taches, chemins)}
    a_faire = [t for t in taches if not os.path.exists(destination[t[2]])]
    faites = len(taches) - len(a_faire)
    on_log(f"{len(taches)} dalles a traiter" + (f", {faites} deja calculees" if faites else ""))

    temps, echecs = [], {}
    with ProcessPoolExecutor(max_workers=config.N_COEURS, initializer=initProcessus,
                             initargs=(config.snapshot(),)) as ex:
        for essai in (1, 2):
            if essai == 2:
                a_faire = [t for t in a_faire if t[2] in echecs]
                if not a_faire:
                    break
                on_log(f"{len(a_faire)} dalle(s) en echec, nouvel essai")
            for i, (out, temps_dalle) in enumerate(ex.map(traiterTache, a_faire), 1):
                nom = temps_dalle["nom"]
                if out is None:
                    echecs[nom] = temps_dalle.get("erreur", "")
                    on_log(f"echec dalle {nom}")
                else:
                    out.to_pickle(destination[nom] + ".tmp")
                    os.replace(destination[nom] + ".tmp", destination[nom])
                    temps.append(temps_dalle)
                    echecs.pop(nom, None)
                if essai == 1 and on_progress is not None:
                    on_progress(faites + i, len(taches))
    return temps, [{"nom": n, "erreur": e} for n, e in sorted(echecs.items())]


def initProcessus(reglages):
    """
    Initialise un processus de calcul : reglages du processus parent, numba sur un fil.
    --------
    @param[in] reglages : dict {NOM: valeur} (voir config.snapshot)

    @return None
    """
    config.appliquer(reglages)
    numba.set_num_threads(1)


_dl = None


def telechargeur():
    """
    Pool de deux fils du processus, reutilise d'une dalle a l'autre.
    --------
    @return ThreadPoolExecutor
    """
    global _dl
    if _dl is None:
        _dl = ThreadPoolExecutor(2)
    return _dl


def traiterTache(tache):
    """
    Traite une dalle dans un processus : telecharge MNS et MNT, calcule, supprime les fichiers.
    --------
    @param[in] tache : (nom_mnt, url_mnt, nom_mns, url_mns, gdf_dalle, relief)

    @return out, temps : GeoDataFrame de la dalle (None si echec), dict des durees par etape
    """
    temps = {}
    nom_mnt, url_mnt, nom_mns, url_mns, gdf_dalle, relief = tache
    temps["nom"] = nom_mns
    mnt_path = mns_path = None
    try:
        t0 = time.perf_counter()
        dl = telechargeur()
        f_mnt = dl.submit(telechargerFichier, urlWms(url_mnt, res_m=config.RES_MNT_M),
                          nom_mnt, config.OUT_DIR_RAW)
        f_mns = dl.submit(telechargerFichier, urlWms(url_mns, marge_m=config.DIST_MAX_M),
                          nom_mns, config.OUT_DIR_RAW)
        mnt_path, mns_path = f_mnt.result(), f_mns.result()
        temps["telechargement"] = time.perf_counter() - t0
        return traiterDalle(mns_path, mnt_path, gdf_dalle, relief, temps=temps), temps

    except Exception as e:
        temps["erreur"] = str(e)
        return None, temps
    finally:
        for pth in (mns_path, mnt_path):
            if pth and os.path.exists(pth):
                os.remove(pth)


def runPipelineDecoupe(echelle, nom_zone, on_progress=None, on_log=print):
    """
    Calcule une region ou la France departement par departement ; un echec n'arrete pas les
    suivants. Un departement dont le gpkg est complet est saute, un gpkg incomplet est complete.
    --------
    @param[in] echelle  : 'region' ou 'nationale'
    @param[in] nom_zone : nom de la region (ignore pour 'nationale')
    @param[in] on_progress, on_log : memes callbacks que runPipeline

    @return bilan : dict (fichier : phrase de synthese, total, echecs marques de leur
                    departement, departements_echec, batiments, temps_globaux) ; None si zone
                    introuvable
    """
    noms = listeDepartements(echelle, nom_zone)
    if not noms:
        on_log("zone introuvable"); return None

    t_total = time.time()
    total_dalles, n_avant, n_merge, n_filtre, n_final = 0, 0, 0, 0, 0
    t_bati_tot, t_traitement_tot, t_ecriture_tot = 0.0, 0.0, 0.0
    echecs, departements_echec, fichiers, deja_faits = [], [], [], []

    for i, nom in enumerate(noms, 1):
        gpkg_path = os.path.join(config.OUT_DIR_PROCESSED, f"{nomFichier(nom)}.gpkg")
        if os.path.exists(gpkg_path) and not dallesManquantes(gpkg_path):
            on_log(f"=== departement {nom} ({i}/{len(noms)}) : deja fait, ignore ===")
            deja_faits.append(nom)
            continue

        on_log(f"=== departement {nom} ({i}/{len(noms)}) ===")
        bilan, erreur = None, None
        for essai in range(1, config.N_ESSAIS_DEPARTEMENT + 1):
            try:
                bilan = runPipeline("departement", nom, None, on_progress=on_progress, on_log=on_log)
                erreur = None
                break
            except Exception as e:
                erreur = str(e)
                on_log(f"[ERREUR] departement {nom}, essai {essai}/{config.N_ESSAIS_DEPARTEMENT} : {e}")
                if essai < config.N_ESSAIS_DEPARTEMENT:
                    time.sleep(config.PAUSE_DEPARTEMENT)

        if erreur is not None:
            departements_echec.append({"nom": nom, "erreur": erreur})
            continue
        if bilan is None:
            on_log(f"departement {nom} : zone introuvable, sans batiment ou sans dalle")
            continue

        total_dalles += bilan.get("total", 0)
        echecs += [{**e, "departement": nom} for e in bilan.get("echecs", [])]
        bat = bilan.get("batiments", {})
        n_avant  += bat.get("avant_merge_filtre", 0)
        n_merge  += bat.get("apres_merge", 0)
        n_filtre += bat.get("apres_filtre", 0)
        n_final  += bat.get("final", 0)
        glob = bilan.get("temps_globaux", {})
        t_bati_tot       += glob.get("batiments", 0.0)
        t_traitement_tot += glob.get("traitement", 0.0)
        t_ecriture_tot   += glob.get("ecriture", 0.0)
        moy = bilan.get("moyennes_dalle", {})
        if moy:
            on_log("   temps moyen/dalle (s) : " + ", ".join(f"{k}={v:.2f}" for k, v in moy.items()))
        if bilan.get("fichier"):
            fichiers.append(bilan["fichier"])

    return {
        "fichier": (f"{len(fichiers)} fichier(s) calcules + {len(deja_faits)} deja fait(s), "
                    f"dans {config.OUT_DIR_PROCESSED}"),
        "total": total_dalles,
        "echecs": echecs,
        "departements_echec": departements_echec,
        "batiments": {"avant_merge_filtre": n_avant, "apres_merge": n_merge,
                      "apres_filtre": n_filtre, "final": n_final},
        "temps_globaux": {
            "batiments": t_bati_tot, "traitement": t_traitement_tot,
            "ecriture": t_ecriture_tot, "total": time.time() - t_total,
        },
    }
