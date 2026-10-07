import pandas as pd
import geopandas as gpd

from src import config
from src.irradiance.pose_plat import LIBELLES


def agregerBatiment(df, gdf, hauteur):
    """
    Agrege les pixels par batiment, applique le modele PV et joint la BD TOPO ; production et
    puissance orp : plat + incline dans la fenetre d'azimut.
    --------
    @param[in] df      : sortie de irrPixels (1 ligne par pixel)
    @param[in] gdf     : GeoDataFrame des batiments (index = df.id)
    @param[in] hauteur : Series de hauteur par batiment (index = df.id)

    @return GeoDataFrame, 1 ligne par batiment ayant au moins un pixel de toit
    """
    pv = config.RENDEMENT_MODULE * config.PR_HORS_TEMP

    inc     = df[df.incline]
    inc_or  = df[df.incline_or]
    plat    = df[~df.incline]
    oriente = df[df.incline_or | ~df.incline]
    seuil   = df[df.energie / df.surf >= config.SEUIL_IRRADIANCE]

    res = pd.DataFrame({
        "irr_an_kwh":          df.groupby("id").energie.sum(),
        "irr_an_kwh_orp":      oriente.groupby("id").energie.sum(),
        "irr_an_kwh_seuil":    seuil.groupby("id").energie.sum(),
        "_eff":                df.groupby("id").energie_eff.sum(),
        "_eff_orp":            oriente.groupby("id").energie_eff.sum(),
        "_eff_seuil":          seuil.groupby("id").energie_eff.sum(),
        "surf_m2_mod":         df.groupby("id").surf_mod.sum(),
        "_mod_orp":            oriente.groupby("id").surf_mod.sum(),
        "_mod_seuil":          seuil.groupby("id").surf_mod.sum(),
        "surf_m2_incl":        inc.groupby("id").surf.sum(),
        "surf_m2_or":          inc_or.groupby("id").surf.sum(),
        "surf_m2_plat":        plat.groupby("id").surf.sum(),
        "surf_m2_seuil":       seuil.groupby("id").surf.sum(),
        "pente_moy_deg_incl":  inc.groupby("id").pente.mean(),
        "ciel_moy":            df.groupby("id").ciel.mean(),
        "nb_pixels":           df.groupby("id").size(),
    })
    for s, nom in enumerate(config.SECTEURS):
        res[f"surf_m2_incl_{nom}"] = inc[inc.secteur == s].groupby("id").surf.sum()
    for t in range(1, 5):
        res[f"prod_T{t}_kwh_orp"] = oriente.groupby("id")[f"energie_eff_T{t}"].sum() * pv

    res["hauteur_p95_m"] = hauteur

    res = res.fillna(0.0)
    res["pose_plat"] = (plat.groupby("id").pose.first().map(LIBELLES)
                        .reindex(res.index).fillna(""))

    kwc = config.RENDEMENT_MODULE
    res["surf_m2"]             = res.surf_m2_incl + res.surf_m2_plat
    res["puissance_kwc"]       = res.surf_m2_mod   * kwc
    res["puissance_kwc_orp"]   = res["_mod_orp"]   * kwc
    res["puissance_kwc_seuil"] = res["_mod_seuil"] * kwc
    res["prod_an_kwh"]         = res["_eff"]       * pv
    res["prod_an_kwh_orp"]     = res["_eff_orp"]   * pv
    res["prod_an_kwh_seuil"]   = res["_eff_seuil"] * pv

    out = gdf.join(res, how="inner")
    return out[["cleabs", *config.ATTRS_BATI, "pose_plat",
                *(c for cols in config.GROUPES_SORTIE.values() for c in cols), "geometry"]]


def mergeCleabs(gdf):
    """
    Recolle les morceaux d'un meme batiment a cheval sur plusieurs dalles (meme cleabs) :
    somme les grandeurs additives, moyennes ponderees de la pente et du ciel, garde la hauteur
    max.
    --------
    @param[in] gdf : sortie de agregerBatiment (plusieurs lignes possibles par cleabs)

    @return GeoDataFrame : 1 ligne par cleabs (morceaux recolles)
    """
    gdf = gdf.copy()
    gdf["_pente_pond"] = gdf.pente_moy_deg_incl * gdf.surf_m2_incl
    gdf["_ciel_pond"]  = gdf.ciel_moy * gdf.nb_pixels
    agg = {c: "sum" for c in gdf.columns
           if c.startswith(("surf_", "irr_", "prod_", "puissance_"))
           or c in ("nb_pixels", "_pente_pond", "_ciel_pond")}
    agg.update({a: "first" for a in config.ATTRS_BATI})
    agg.update(hauteur_p95_m="max", geometry="first", pose_plat="max")
    out = gdf.groupby("cleabs", as_index=False).agg(agg)
    out["pente_moy_deg_incl"] = (out._pente_pond / out.surf_m2_incl).fillna(0.0)
    out["ciel_moy"] = out._ciel_pond / out.nb_pixels
    out = out.drop(columns=["_pente_pond", "_ciel_pond"])
    return gpd.GeoDataFrame(out, geometry="geometry", crs=gdf.crs)
