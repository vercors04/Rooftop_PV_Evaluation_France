import json, os, sys
os.environ["GDAL_PAM_ENABLED"] = "NO"
import numpy as np

if getattr(sys, "frozen", False):
    if sys.platform == "win32":
        _UTILISATEUR = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        _UTILISATEUR = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    BASE      = os.path.join(_UTILISATEUR, "roofTool")  # inscriptible
    BASE_DATA = sys._MEIPASS                         # ressources embarquees
else:
    BASE      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    BASE_DATA = BASE

SETTINGS = os.path.join(BASE, "executable", "settings.json")


# ============================================================
#  Constantes fixes
# ============================================================

VERSION = "1.1.0"                                     # metadonnees, etat de reprise

# dossiers d'entree / sortie
OUT_DIR_RAW       = os.path.join(BASE, "data", "raw")                   # dalles MNS/MNT (transit)
DIR_GEOJSON       = os.path.join(BASE, "data", "processed", "geojson")  # contours de zone (.geojson)
DIR_RELIEF        = os.path.join(BASE, "data", "relief")                # MNT grossiers (horizon lointain)
OUT_DIR_PROCESSED = os.path.join(BASE, "data", "processed", "gpkg")     # resultats (.gpkg)
DIR_CARTES        = os.path.join(BASE, "data", "processed", "cartes")   # cartes .html et leurs caches
DIR_EN_COURS      = os.path.join(BASE, "data", "processed", "en_cours") # dalles calculees, reprise
DOSSIER           = os.path.join(BASE_DATA, "data", "tables")           # tables meteo (.npz)
DOSSIER_FIN       = os.path.join(DOSSIER, "fines")                      # sous-cellules (.npz)
ECARTS_FIN        = os.path.join(DOSSIER_FIN, "ecarts.csv")             # ecarts mesures par sous-cellule
DOSSIERS_SORTIE   = [OUT_DIR_RAW, DIR_GEOJSON, DIR_RELIEF, OUT_DIR_PROCESSED, DIR_CARTES,
                     DIR_EN_COURS]                                      # crees au lancement

# services distants
WFS       = "https://data.geopf.fr/wfs/ows"            # WFS IGN (batiments, dalles, protections)
URL       = "https://re.jrc.ec.europa.eu/api/v5_3/"    # PVGIS 5.3 (SARAH-3, 2005-2023)
GEOCODAGE = "https://data.geopf.fr/geocodage/search"   # adresses (IGN)
GEO_API   = "https://geo.api.gouv.fr"                  # communes, departements, regions

# fonds de carte : WMTS Geoplateforme IGN, sans cle
_WMTS_IGN = ("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
             "&LAYER={couche}&STYLE=normal&TILEMATRIXSET=PM"
             "&TILEMATRIX={{z}}&TILEROW={{y}}&TILECOL={{x}}&FORMAT={format}")
TUILES_PLAN  = _WMTS_IGN.format(couche="GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", format="image/png")
TUILES_ORTHO = _WMTS_IGN.format(couche="ORTHOIMAGERY.ORTHOPHOTOS", format="image/jpeg")
ATTRIB_IGN   = "IGN-F/Géoportail"
TUILES_SATELLITE = ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
                    "MapServer/tile/{z}/{y}/{x}")
ATTRIB_ESRI      = "Esri"

# grille meteo
PAS       = 0.10                                      # pas de la grille meteo (deg) = taille de cellule
PAS_FIN   = 0.05                                      # sous-cellule (deg) = pixel SARAH-3
ECART_FIN = 0.01                                      # ecart qui fait construire la sous-cellule
ALBEDO_TABLES = 0.20                                  # albedo du reflechi inclus dans les tables

BANDE_HORIZON_DEG = 6.5                               # hauteur de la bande de brillance d'horizon (Perez)
RAYON_ADRESSE_M   = 40                                # zone d'une adresse (m)

# grilles d'angles et calendrier (modele PV)
ALPHAS  = np.arange(0, 360, 15)                       # orientations testees (deg, 0=N, 90=E)
BETAS   = np.arange(0, 71, 10)                        # pentes testees (deg)
N_JOURS = np.array([31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31])  # jours par mois
TRIM    = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [9, 10, 11]]              # mois (index 0-11) par trimestre
SECTEURS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]              # 8 secteurs d'orientation

# colonnes de sortie regroupees par theme
GROUPES_SORTIE = {
    "hauteur_p95_m":       ["hauteur_p95_m"],
    "nb_pixels":           ["nb_pixels"],
    "surf_m2":             ["surf_m2"],
    "surf_m2_plat":        ["surf_m2_plat"],
    "surf_m2_incl":        ["surf_m2_incl"],
    "surf_m2_or":          ["surf_m2_or"],
    "surf_m2_seuil":       ["surf_m2_seuil"],
    "surf_m2_mod":         ["surf_m2_mod"],
    "pente_moy_deg_incl":  ["pente_moy_deg_incl"],
    "surfaces_orient":     [f"surf_m2_incl_{s}" for s in SECTEURS],
    "ciel_moy":            ["ciel_moy"],
    "irr_an_kwh":          ["irr_an_kwh"],
    "puissance_kwc":       ["puissance_kwc"],
    "prod_an_kwh":         ["prod_an_kwh"],
    "irr_an_kwh_orp":      ["irr_an_kwh_orp"],
    "puissance_kwc_orp":   ["puissance_kwc_orp"],
    "prod_an_kwh_orp":     ["prod_an_kwh_orp"],
    "irr_an_kwh_seuil":    ["irr_an_kwh_seuil"],
    "puissance_kwc_seuil": ["puissance_kwc_seuil"],
    "prod_an_kwh_seuil":   ["prod_an_kwh_seuil"],
    "production_trim":     [f"prod_T{t}_kwh_orp" for t in range(1, 5)],
}

# libelle et unite d'affichage (gpkg en kWh et kWc)
COLONNES_SORTIE = {
    "hauteur_p95_m":       ("Hauteur du toit (p95 du MNH)", "m"),
    "nb_pixels":           ("Nombre de pixels de toit", ""),
    "surf_m2":             ("Surface posable (plat + incliné)", "m2"),
    "surf_m2_plat":        ("Surface plate", "m2"),
    "surf_m2_incl":        ("Surface inclinée, toutes orientations", "m2"),
    "surf_m2_or":          ("Surface inclinée orientée (azimut choisi)", "m2"),
    "surf_m2_seuil":       ("Surface au-dessus du seuil d'irradiance", "m2"),
    "surf_m2_mod":         ("Surface de modules installables", "m2"),
    **{f"surf_m2_incl_{s}": (f"Surface inclinée {s}", "m2") for s in SECTEURS},
    "pente_moy_deg_incl":  ("Pente moyenne des pans inclinés", "deg"),
    "ciel_moy":            ("Part du ciel vue par le toit", "ratio"),
    "irr_an_kwh":          ("Irradiation reçue / an, toute la toiture", "Wh"),
    "irr_an_kwh_orp":      ("Irradiation reçue / an, base installable", "Wh"),
    "irr_an_kwh_seuil":    ("Irradiation reçue / an, au-dessus du seuil", "Wh"),
    "prod_an_kwh":         ("Production PV / an, toute la toiture", "Wh"),
    "prod_an_kwh_orp":     ("Production PV / an, base installable", "Wh"),
    "prod_an_kwh_seuil":   ("Production PV / an, au-dessus du seuil", "Wh"),
    "puissance_kwc":       ("Puissance installable, toute la toiture", "Wc"),
    "puissance_kwc_orp":   ("Puissance installable, base installable", "Wc"),
    "puissance_kwc_seuil": ("Puissance installable, au-dessus du seuil", "Wc"),
    "prod_T1_kwh_orp":     ("Production T1 (jan-mars)", "Wh"),
    "prod_T2_kwh_orp":     ("Production T2 (avr-juin)", "Wh"),
    "prod_T3_kwh_orp":     ("Production T3 (juil-sept)", "Wh"),
    "prod_T4_kwh_orp":     ("Production T4 (oct-déc)", "Wh"),
}
SANS_TOTAL = ("m", "deg", "ratio")                    # unites dont la somme n'a pas de sens

# catalogues de choix de l'interface
ATTRS_BDTOPO = ['nature', 'usage_1', 'usage_2', 'construction_legere',
                'etat_de_l_objet', 'nombre_de_logements', 'nombre_d_etages',
                'materiaux_des_murs', 'materiaux_de_la_toiture', 'hauteur',
                'altitude_minimale_sol', 'altitude_minimale_toit', 'altitude_maximale_sol',
                'altitude_maximale_toit', 'date_creation', 'date_modification']
NATURES  = ['Indifférenciée', 'Industriel, agricole ou commercial', 'Château', 'Eglise',
            'Chapelle', 'Serre', 'Silo', 'Tour, donjon', 'Tribune', 'Fort, blockhaus, casemate',
            'Monument', 'Moulin à vent', 'Arène ou théâtre antique', 'Arc de triomphe']
USAGE_1  = ['Agricole', 'Annexe', 'Commercial et services', 'Indifférencié',
            'Industriel', 'Religieux', 'Résidentiel', 'Sportif']
ETATS    = ['En service', 'En construction', 'En projet']
ECHELLES = ['Adresse', 'Commune ou ville', 'Département', 'Région', 'France',
            'Zone tracée']            # zone dessinee (carte_dessin)

DIVISEURS_360 = [6, 8, 9, 10, 12, 15, 18, 20, 24, 30, 36, 40, 45, 60, 72, 90]

# Faiman : U = U0 + U1 x vent (pvlib, GenericLinearModel)
POSES = {
    "libre":        (25.0, 6.84),   # chassis ventile
    "surimpose":    (27.9, 1.56),   # rails sur la couverture
    "integre":      (23.5, 1.26),   # remplace la couverture
    "personnalise": None,           # U0_FAIMAN, U1_FAIMAN saisis
}

# toits plats
POSES_PLAT      = ["à plat", "sud", "est-ouest"]
CRITERES_MIXTE  = ["surface", "usage", "nature"]
ESPACEMENTS_SUD = ["sans ombre au solstice", "taux fixé"]
THERMIQUE_PLAT  = {"à plat": "integre", "sud": "libre", "est-ouest": "surimpose"}   # cles de POSES

# reglages sans effet sur le calcul d'une dalle (modifiables avant une reprise)
SANS_EFFET_DALLE = ["N_COEURS", "N_THREADS", "COUNT", "N_ESSAIS_WFS", "PAUSE_WFS", "N_ESSAIS",
                    "PAUSE_DL", "N_ESSAIS_DEPARTEMENT", "PAUSE_DEPARTEMENT", "SURF_MIN", "HAUT_MIN",
                    "HAUT_MAX", "SORTIE_GARDEES", "PROTECTIONS_OK", "PROTECTIONS_EXCLURE"]

# protections (L111-17 du code de l'urbanisme)
# {libelle: (colonne, couche WFS, champ geometrique, filtre CQL, CRS de la BBOX)}
PROTECTIONS = {
    "Monument historique":          ("prot_monument",   "wfs_sup:generateur_sup_s", "the_geom", "suptype='ac1'", 4326),
    "Abords de monument":           ("prot_abords",     "wfs_sup:assiette_sup_s",   "the_geom", "suptype='ac1'", 4326),
    "Site patrimonial remarquable": ("prot_spr",        "wfs_sup:assiette_sup_s",   "the_geom", "suptype='ac4'", 4326),
    "Site classé ou inscrit":       ("prot_site",       "wfs_sup:assiette_sup_s",   "the_geom", "suptype='ac2'", 4326),
    "Cœur de parc national":        ("prot_coeur_parc", "patrinat_pn2:pn",          "geom",     None,           3857),
}

# ============================================================
#  Reglages modifiables
# ============================================================
DEFAULTS = {
    # tri des toitures
    "SURF_MIN": 5, "HAUT_MIN": 2, "HAUT_MAX": 300,
    # WFS
    "N_ESSAIS_WFS": 8, "PAUSE_WFS": 2, "N_THREADS": 8, "COUNT": 5000,
    # region/france
    "N_ESSAIS_DEPARTEMENT": 2, "PAUSE_DEPARTEMENT": 30,
    # dalles
    "N_COEURS": 5, "N_ESSAIS": 8, "PAUSE_DL": 5,
    "RES_MNT_M": 1.0,            # pas du MNT (m)
    # pente et orientation
    "METHODE_PENTE": "plan",     # "plan" ou "differences"
    "RAYON_PLAN": 1,             # demi-fenetre (px)
    "RESIDU_MAX_M": 0.25,        # ecart max au plan (m), 0 = off
    "RESIDU_PAN_M": 0.03,        # demi-fenetre au-dela (m), 0 = off
    # selection des toits
    "BUFFER": 0.8, "MNH_MIN": 1.5, "PENTE_PLAT": 10, "PENTE_MAX": 45,
    "AZ_MIN": 90, "AZ_MAX": 270,
    # ombrage proche
    "N_DIRECTIONS": 36, "DIST_MAX_M": 100, "CAP": 75.0,
    "PAS_RAYON_DIV": 0,          # croissance du pas, 0 = exact
    # ombrage lointain
    "DIST_LOIN_M": 20000,        # portee (m), 0 = off
    "RES_LOIN_M": 50,            # pas du MNT de relief (m)
    "DIST_MIN_LOIN_M": 1000,     # portee min (m)
    # module PV
    "ALBEDO": 0.20,              # reflechi par le sol
    "RENDEMENT_MODULE": 0.22,
    "PR_HORS_TEMP": 0.79,        # pertes hors temperature
    "GAMMA_MODULE": -0.0035,     # coefficient de temperature (/degC)
    "POSE": "surimpose",         # preset de POSES
    "U0_FAIMAN": 27.9,           # W/m2/K, ecrase par le preset
    "U1_FAIMAN": 1.56,           # W.s/m3/K, ecrase par le preset
    # couverture
    "COUVERTURE_INCL": 0.60,     # part equipee, pans inclines
    "EMPRISE_PLAT": 0.75,        # part du toit plat sous le champ
    "RECUL_M": 0.0,              # erosion (m), 0 = off
    # toits plats
    "PLAT_POSE": "sud",          # POSES_PLAT ou "mixte"
    "SUD_PENTE": 15,             # deg
    "SUD_AZIMUT": 180,           # deg, 0=N
    "SUD_ESPACEMENT": "sans ombre au solstice",   # ESPACEMENTS_SUD
    "SUD_GCR": 0.60,             # taux fixe
    "EO_PENTE": 10,              # deg
    "EO_GCR": 0.90,              # modules / champ, deux faces
    "MIXTE_CRITERE": "surface",  # CRITERES_MIXTE
    "MIXTE_SEUIL_M2": 500,       # surface plate du batiment
    "MIXTE_USAGES": ["Industriel", "Commercial et services", "Agricole"],
    "MIXTE_NATURES": ["Industriel, agricole ou commercial"],
    "MIXTE_SI": "est-ouest",     # critere rempli
    "MIXTE_SINON": "sud",
    "SEUIL_IRRADIANCE": 1000,    # kWh/m2/an
    # filtre BD TOPO
    "ETAT": ["En service"], "CONSTRUCTION_LEGERE": False,
    "NATURE_OK": ['Indifférenciée', 'Industriel, agricole ou commercial'],
    "USAGE_OK":  ['Résidentiel', 'Commercial et services', 'Indifférencié', 'Industriel', 'Agricole'],
    "ATTRS_BATI": ["nature", "usage_1", "hauteur", "nombre_d_etages"],
    # sortie
    "SORTIE_GARDEES": list(GROUPES_SORTIE),
    # protections
    "PROTECTIONS_OK": list(PROTECTIONS),
    "PROTECTIONS_EXCLURE": False,
}


def snapshot():
    """
    Reglages courants.
    --------
    @return dict {cle de DEFAULTS: valeur}
    """
    return {cle: globals()[cle] for cle in DEFAULTS}


def derive():
    """
    Recalcule les reglages derives : coefficients du preset de pose, bornes de pente et de
    fenetre d'ajustement, filtres BD TOPO.
    --------
    @return None
    """
    global FILTRES_BATI, U0_FAIMAN, U1_FAIMAN, PENTE_MAX, PENTE_PLAT, RAYON_PLAN
    preset = POSES.get(POSE)
    if preset is not None:
        U0_FAIMAN, U1_FAIMAN = preset
    PENTE_MAX  = min(PENTE_MAX, float(BETAS[-1]))     # au-dela, hors grille des tables
    PENTE_PLAT = min(PENTE_PLAT, PENTE_MAX)
    RAYON_PLAN = max(int(RAYON_PLAN), 1)              # 0 : aucun plan ajustable
    FILTRES_BATI = {
        "etat_de_l_objet": ETAT,
        "nature":          NATURE_OK,
        "usage_1":         USAGE_OK,
    }
    if not CONSTRUCTION_LEGERE:
        FILTRES_BATI["construction_legere"] = False


def appliquer(reglages):
    """
    Ecrit des reglages dans les variables du module, puis recalcule les reglages derives.
    --------
    @param[in] reglages : dict {NOM: valeur}

    @return None
    """
    globals().update(reglages)
    derive()


def load():
    """
    Charge DEFAULTS, surcharges par settings.json, dans les variables du module.
    --------
    @return None
    """
    valeurs = dict(DEFAULTS)
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            valeurs.update(json.load(f))
    appliquer(valeurs)


def save(reglages):
    """
    Fusionne des reglages dans settings.json, puis recharge le module.
    --------
    @param[in] reglages : dict {NOM: valeur}

    @return None
    """
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    actuel = {}
    if os.path.exists(SETTINGS):
        with open(SETTINGS, encoding="utf-8") as f:
            actuel = json.load(f)
    actuel.update(reglages)
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(actuel, f, ensure_ascii=False, indent=2)
    load()


load()
