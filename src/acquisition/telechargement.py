import os, time, requests
from urllib.parse import urlparse, parse_qs

from src.acquisition.requetes import session
from src import config


def telechargerFichier(url, nom_fichier, dossier_dest):
    """
    Telecharge un fichier en streaming, avec config.N_ESSAIS essais ; pause de
    config.PAUSE_DL x numero de l'essai. Une reponse non raster ou tronquee compte comme un echec.
    --------
    @param[in] url          : lien HTTP(S) du fichier
    @param[in] nom_fichier  : nom du fichier sur le disque
    @param[in] dossier_dest : dossier cible (cree si absent)

    @return chemin local du fichier ; leve RuntimeError apres tous les echecs
    """
    n_essais, pause = config.N_ESSAIS, config.PAUSE_DL
    os.makedirs(dossier_dest, exist_ok=True)
    chemin = os.path.join(dossier_dest, nom_fichier)
    part = chemin + ".part"
    cause = ""

    for essai in range(1, n_essais + 1):
        try:
            with session().get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                type_recu = r.headers.get("content-type", "")
                if "xml" in type_recu or type_recu.startswith("text/"):
                    raise requests.RequestException(
                        f"reponse non raster ({type_recu}) : {r.text[:200]}")
                attendu, recu = int(r.headers.get("content-length", 0)), 0
                with open(part, "wb") as fic:
                    for chunk in r.iter_content(chunk_size=65536):
                        fic.write(chunk)
                        recu += len(chunk)
            if attendu and recu != attendu:
                raise requests.RequestException(f"reponse tronquee : {recu} octets sur {attendu}")
            os.replace(part, chemin)
            return chemin

        except requests.RequestException as e:
            cause = str(e)
            if essai < n_essais:
                time.sleep(pause * essai)

    if os.path.exists(part):
        os.remove(part)
    raise RuntimeError(f"echec apres {n_essais} essais : {nom_fichier} ({cause})")


def nomDalle(url):
    """
    Nom de fichier d'une dalle, lu dans le parametre FILENAME de son URL WMS.
    --------
    @param[in] url : GetMap WMS renvoye par la couche de metadonnees LiDAR HD

    @return nom du fichier (ex: LHD_FXX_0477_6593_MNS_O_0M50_LAMB93_IGN69.tif) ;
            leve KeyError si l'URL ne porte pas de parametre FILENAME
    """
    return parse_qs(urlparse(url).query)["FILENAME"][0]


def urlWms(url, marge_m=0.0, res_m=0.0, bbox=None):
    """
    Reecrit un GetMap WMS : emprise, marge et pas de pixel.
    --------
    @param[in] url     : GetMap WMS d'une dalle (voir dalles)
    @param[in] marge_m : marge de chaque cote (m) ; 0 = emprise inchangee
    @param[in] res_m   : taille de pixel (m) ; 0 = resolution inchangee
    @param[in] bbox    : (xmin, ymin, xmax, ymax) Lambert 93 avant marge ; None = emprise de
                         la dalle

    @return URL reecrite (FILENAME inchange)
    """
    if marge_m <= 0 and res_m <= 0 and bbox is None:
        return url
    tete, _, requete = url.partition("?")
    par = dict(p.split("=", 1) for p in requete.split("&"))
    if bbox is None:
        x0, y0, x1, y1 = (float(v) for v in par["BBOX"].split(","))
    else:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    res = res_m if res_m > 0 else (x1 - x0) / float(par["WIDTH"])
    if res <= 0:
        raise ValueError("resolution demandee nulle ou negative")
    par["BBOX"] = f"{x0-marge_m},{y0-marge_m},{x1+marge_m},{y1+marge_m}"
    par["WIDTH"]  = str(int(round((x1 - x0 + 2 * marge_m) / res)))
    par["HEIGHT"] = str(int(round((y1 - y0 + 2 * marge_m) / res)))
    return tete + "?" + "&".join(f"{k}={v}" for k, v in par.items())


def listeTelechargement(gdf):
    """
    Paires (MNT, MNS) a telecharger, une par dalle.
    --------
    @param[in] gdf : GeoDataFrame des dalles (url_mnt, url_mns)

    @return liste de (nom_mnt, url_mnt, nom_mns, url_mns) ; [] si aucune dalle
    """
    return [(nomDalle(l.url_mnt), l.url_mnt, nomDalle(l.url_mns), l.url_mns)
            for l in gdf.itertuples()]
