import os
import re

import numpy as np
import rasterio
from rasterio.windows import Window

from src.acquisition.telechargement import telechargerFichier, urlWms
from src.geometrie.horizon import compHZ
from src import config

MAX_PIXELS = 4000
ALTI_MIN_M = -100.0


def mntRelief(url_mnt, bounds, nom_zone, on_log=print):
    """
    MNT grossier de toute la zone pour l'horizon lointain, en une requete WMS ; garde sur
    disque tant que la zone est incomplete, retelecharge s'il ne la couvre pas.
    --------
    @param[in] url_mnt  : GetMap WMS d'une dalle MNT de la zone
    @param[in] bounds   : (xmin, ymin, xmax, ymax) de la zone, Lambert 93
    @param[in] nom_zone : nom de la zone (nom du cache)
    @param[in] on_log   : callback (message)

    @return chemin du GeoTIFF ; None si config.DIST_LOIN_M vaut 0
    """
    if config.DIST_LOIN_M <= 0:
        return None
    nom = f"relief_{nom_zone}_{int(config.RES_LOIN_M)}m_{int(config.DIST_LOIN_M)}m.tif"
    chemin = os.path.join(config.DIR_RELIEF, nom)
    marge = config.DIST_LOIN_M
    if os.path.exists(chemin):
        with rasterio.open(chemin) as src:
            b, tol = src.bounds, src.res[0]
        if (b.left <= bounds[0] - marge + tol and b.bottom <= bounds[1] - marge + tol
                and b.right >= bounds[2] + marge - tol and b.top >= bounds[3] + marge - tol):
            on_log(f"relief : {nom} deja present ({os.path.getsize(chemin)/1e6:.1f} Mo)")
            return chemin
        on_log(f"relief : {nom} ne couvre pas la zone, nouveau telechargement")

    cote = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) + 2 * marge
    res = max(config.RES_LOIN_M, cote / MAX_PIXELS)
    if res > config.RES_LOIN_M:
        on_log(f"relief : zone trop large, pas porte a {res:.0f} m "
               f"(demande {config.RES_LOIN_M:.0f} m)")
    url = urlWms(url_mnt, marge_m=marge, res_m=res, bbox=bounds)
    chemin = telechargerFichier(url, nom, config.DIR_RELIEF)
    on_log(f"relief : {nom} telecharge ({os.path.getsize(chemin)/1e6:.1f} Mo)")
    return chemin


def reliefsZone(nom_zone):
    """
    MNT de relief enregistres pour une zone, tous pas et portees confondus.
    --------
    @param[in] nom_zone : nom de la zone (nom du cache, voir mntRelief)

    @return liste de chemins
    """
    if not os.path.isdir(config.DIR_RELIEF):
        return []
    motif = re.compile(rf"relief_{re.escape(nom_zone)}_\d+m_\d+m\.tif")
    return [os.path.join(config.DIR_RELIEF, n) for n in os.listdir(config.DIR_RELIEF)
            if motif.fullmatch(n)]


def hzLoin(chemin, meta, mns, toiture):
    """
    Angle d'horizon du relief au-dela de la portee proche, par pixel de toit ; calcule par
    cellule du MNT grossier, depuis la mediane du MNS des toits de la cellule.
    --------
    @param[in] chemin  : GeoTIFF rendu par mntRelief (None = pas de calcul)
    @param[in] meta    : profil rasterio de la dalle (cles transform, resolution, width, height)
    @param[in] mns     : 2D float du MNS de la dalle
    @param[in] toiture : 2D bool des pixels de toit de la dalle

    @return (N_pixels_toit, config.N_DIRECTIONS) float32, ordre np.where(toiture) ; None si
            desactive ou hors du MNT de relief
    """
    if chemin is None or not toiture.any():
        return None

    t_d = meta["transform"]
    res_d = meta["resolution"]
    x0, y1 = t_d.c, t_d.f
    x1 = x0 + meta["width"] * res_d
    y0 = y1 - meta["height"] * res_d
    marge = config.DIST_LOIN_M

    with rasterio.open(chemin) as src:
        res = src.transform.a
        cx, cy = src.transform.c, src.transform.f
        c0 = max(int(np.floor((x0 - marge - cx) / res)), 0)
        r0 = max(int(np.floor((cy - y1 - marge) / res)), 0)
        c1 = min(int(np.ceil((x1 + marge - cx) / res)), src.width)
        r1 = min(int(np.ceil((cy - y0 + marge) / res)), src.height)
        if c1 <= c0 or r1 <= r0:
            return None
        fen = Window(c0, r0, c1 - c0, r1 - r0)
        z = src.read(1, window=fen).astype(np.float32)
        tw = src.window_transform(fen)
        nodata = src.nodata

    trou = ~np.isfinite(z) | (z < ALTI_MIN_M)
    if nodata is not None:
        trou |= (z == nodata)
    if trou.any():
        d = trou.copy()
        d[1:, :] |= trou[:-1, :];  d[:-1, :] |= trou[1:, :]
        d[:, 1:] |= trou[:, :-1];  d[:, :-1] |= trou[:, 1:]
        z[d] = np.nan

    lig, col = np.where(toiture)
    xs = x0 + (col + 0.5) * res_d
    ys = y1 - (lig + 0.5) * res_d
    cc = np.floor((xs - tw.c) / res).astype(np.int64)
    rr = np.floor((tw.f - ys) / res).astype(np.int64)
    dedans = (rr >= 0) & (rr < z.shape[0]) & (cc >= 0) & (cc < z.shape[1])
    if not dedans.all():
        return None

    cles, inv = np.unique(rr * z.shape[1] + cc, return_inverse=True)
    ru, cu = np.divmod(cles, z.shape[1])

    zt = mns[lig, col]
    for k in range(len(cles)):
        v = zt[inv == k]
        v = v[np.isfinite(v)]
        if v.size:
            z[ru[k], cu[k]] = np.median(v)

    depart = np.zeros(z.shape, np.bool_)
    depart[ru, cu] = True

    hz = compHZ(z, depart, res, config.N_DIRECTIONS, config.DIST_MIN_LOIN_M,
                config.DIST_LOIN_M, config.CAP, config.PAS_RAYON_DIV)
    return hz[inv]
