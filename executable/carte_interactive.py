import os
import json
from pathlib import Path

import folium
import pandas as pd
import geopandas as gpd
import pyogrio

from src import config
from src.acquisition.zone import zone
from executable.tool_fct_exe import formater, cellules, echelleGpkg, fichiers, mentionIncomplet
from executable.carte_style import CSS, REMPLI, OPACITE, OPACITE_SURVOL, fondsDeCarte


DIR_CONTOURS  = os.path.join(config.BASE_DATA, "data", "contours")
FICHIER_STATS = os.path.join(config.DIR_CARTES, "stats_carte.json")
FICHIER_CARTE = os.path.join(config.DIR_CARTES, "carte.html")

REGIONS = ["auvergne-rhone-alpes", "bourgogne-franche-comte", "bretagne",
           "centre-val-de-loire", "corse", "grand-est", "hauts-de-france",
           "ile-de-france", "normandie", "nouvelle-aquitaine", "occitanie",
           "pays-de-la-loire", "provence-alpes-cote-d-azur"]

ZOOM_DEP = 8
ZOOM_COM = 11
SEUIL_DEP_COMPLET = 0.9

CSS_CARTE = """
<style>
.leaflet-popup-content { width: 300px !important; }
#panneau-details { position: fixed; top: 80px; right: 15px; width: 600px; max-height: 75%;
                   overflow-y: auto; display: none; z-index: 9999; }
#panneau-details h3 { margin: 0 0 2px 0; font-size: 15px; }
#detail-fermer { float: right; cursor: pointer; color: #7F8C8D; font-size: 16px; }
</style>"""


def chargerContours(niveau, regions=REGIONS):
    """
    Concatene les contours des regions metropolitaines pour un niveau donne.
    --------
    @param[in] niveau  : "region", "departement" ou "communes"
    @param[in] regions : sous-ensemble de REGIONS a charger (defaut : toutes)

    @return GeoDataFrame WGS84 (colonnes nom, code si present, region, geometry)
    """
    dossier, prefixe = {"region":      ("region", "region-"),
                        "departement": ("departement", "departements-"),
                        "communes":    ("communes", "communes-")}[niveau]
    morceaux = []
    for reg in regions:
        chemin = os.path.join(DIR_CONTOURS, dossier, f"{prefixe}{reg}.geojson")
        if not os.path.exists(chemin):
            continue
        g = gpd.read_file(chemin)
        g["region"] = reg.replace("-", " ").title()
        morceaux.append(g[[c for c in ("nom", "code", "region", "geometry") if c in g.columns]])
    if not morceaux:
        return gpd.GeoDataFrame(columns=["nom", "code", "region", "geometry"], crs="EPSG:4326")
    return gpd.GeoDataFrame(pd.concat(morceaux, ignore_index=True), crs="EPSG:4326")


def chargerZone(chemin_gpkg):
    """
    Contour de la zone calculee, lu dans le geojson de meme nom (variantes - et _ tolerees).
    --------
    @param[in] chemin_gpkg : chemin du .gpkg

    @return polygone shapely WGS84 ; None si le geojson est introuvable
    """
    base = os.path.splitext(os.path.basename(chemin_gpkg))[0]
    for nom in (base, base.replace("-", "_"), base.replace("_", "-")):
        contour = zone("polygone", nom)
        if contour is not None:
            return contour
    return None


def agregerGpkg(chemin, communes):
    """
    Resume un gpkg par commune : compte, somme, mediane, P10 et P90 ; communes hors du contour
    de la zone ecartees.
    --------
    @param[in] chemin   : chemin du .gpkg
    @param[in] communes : GeoDataFrame des contours de communes (code, geometry, WGS84)

    @return dict {code_insee: {"n", "somme", "med", "p10", "p90"}}
    """
    champs = set(pyogrio.read_info(chemin)["fields"])
    cols = [c for c in config.COLONNES_SORTIE if c in champs]
    gdf = gpd.read_file(chemin, columns=cols)

    pts = gpd.GeoDataFrame(gdf[cols], geometry=gdf.geometry.representative_point(),
                           crs=gdf.crs).to_crs(4326)
    minx, miny, maxx, maxy = pts.total_bounds
    proches = communes.cx[minx:maxx, miny:maxy]

    zone = chargerZone(chemin)
    if zone is not None:
        proches = proches[proches.representative_point().within(zone)]

    joint = gpd.sjoin(pts, proches[["code", "geometry"]], how="inner", predicate="within")

    grp = joint.groupby("code")[cols]
    sommes, medianes = grp.sum(), grp.median()
    p10, p90 = grp.quantile(0.10), grp.quantile(0.90)
    tailles = joint.groupby("code").size()

    return {code: {"n": int(tailles[code]),
                   "somme": {c: float(sommes.at[code, c]) for c in cols},
                   "med":   {c: float(medianes.at[code, c]) for c in cols},
                   "p10":   {c: float(p10.at[code, c]) for c in cols},
                   "p90":   {c: float(p90.at[code, c]) for c in cols}}
            for code in tailles.index}


def majStats(on_log=print):
    """
    Met a jour le cache : agrege les gpkg nouveaux ou modifies (hors zones tracees), retire les
    disparus.
    --------
    @param[in] on_log : callback (message)

    @return stats, change : contenu du cache, True s'il a change
    """
    stats = {"version": 2, "fichiers": {}}
    if os.path.exists(FICHIER_STATS):
        try:
            with open(FICHIER_STATS, encoding="utf-8") as f:
                charge = json.load(f)
            if charge.get("version") == 2:
                stats = charge
        except (json.JSONDecodeError, OSError):
            pass

    presents = {nom: os.path.getmtime(os.path.join(config.OUT_DIR_PROCESSED, nom))
                for nom in fichiers(config.OUT_DIR_PROCESSED, ".gpkg")
                if echelleGpkg(os.path.join(config.OUT_DIR_PROCESSED, nom)) != "polygone"}

    change = False
    for nom in list(stats["fichiers"]):
        if nom not in presents:
            del stats["fichiers"][nom]
            change = True

    a_faire = [nom for nom, mtime in presents.items()
               if stats["fichiers"].get(nom, {}).get("mtime") != mtime]
    if a_faire:
        communes = chargerContours("communes")
        for nom in a_faire:
            on_log(f"agregation de {nom}")
            stats["fichiers"][nom] = {
                "mtime": presents[nom],
                "communes": agregerGpkg(os.path.join(config.OUT_DIR_PROCESSED, nom), communes)}
            change = True

    if change:
        os.makedirs(os.path.dirname(FICHIER_STATS), exist_ok=True)
        with open(FICHIER_STATS, "w", encoding="utf-8") as f:
            json.dump(stats, f)
    return stats, change


def tableauCommunes(stats):
    """
    Stats par commune de tous les fichiers en un tableau plat ; commune presente dans plusieurs
    gpkg : celui au plus grand nombre de batiments.
    --------
    @param[in] stats : contenu du cache

    @return DataFrame, 1 ligne par commune (code, n, X_s, X_md, X_p10, X_p90)
    """
    communes = {}
    for fichier in stats["fichiers"].values():
        for code, d in fichier["communes"].items():
            if code not in communes or d["n"] > communes[code]["n"]:
                communes[code] = d

    lignes = []
    for code, d in communes.items():
        ligne = {"code": code, "n": d["n"]}
        ligne.update({f"{c}_s": v for c, v in d["somme"].items()})
        ligne.update({f"{c}_md": v for c, v in d["med"].items()})
        ligne.update({f"{c}_p10": v for c, v in d["p10"].items()})
        ligne.update({f"{c}_p90": v for c, v in d["p90"].items()})
        lignes.append(ligne)
    return pd.DataFrame(lignes) if lignes else pd.DataFrame(columns=["code", "n"])


def agreger(df, cle):
    """
    Somme par cle des colonnes X_s et de n.
    --------
    @param[in] df  : tableau plat (voir tableauCommunes)
    @param[in] cle : colonne de regroupement

    @return DataFrame agrege
    """
    agg = {"n": "sum"}
    agg.update({c: "sum" for c in df.columns if c.endswith("_s")})
    return df.groupby(cle, as_index=False).agg(agg)


def colonne(df, nom):
    """
    Colonne d'un DataFrame, ou colonne de NaN si absente.
    --------
    @param[in] df  : DataFrame
    @param[in] nom : nom de la colonne

    @return Series
    """
    return df[nom] if nom in df.columns else pd.Series(float("nan"), index=df.index)


def valeursDetails(ligne, colonnes):
    """
    [total, mediane, moyenne, "P10 a P90"] par entree de COLONNES_SORTIE.
    --------
    @param[in] ligne    : ligne du tableau plat
    @param[in] colonnes : colonnes disponibles

    @return liste (None si la colonne est absente)
    """
    r = {"n": ligne["n"]}
    for suffixe, cle in (("_s", "somme"), ("_md", "med"), ("_p10", "p10"), ("_p90", "p90")):
        r[cle] = {c: ligne[c + suffixe] for c in config.COLONNES_SORTIE if c + suffixe in colonnes}
    return [cellules(r, c, unite) if pd.notna(r["somme"].get(c)) and r["n"] > 0 else None
            for c, (_, unite) in config.COLONNES_SORTIE.items()]


def preparer(contours, df, cle_contours, cle_df, prefixe, details, titres):
    """
    Joint les stats aux contours et prepare les colonnes de la popup ; remplit details et
    titres pour le panneau lateral.
    --------
    @param[in] contours     : GeoDataFrame des contours du niveau
    @param[in] df           : stats du niveau (voir tableauCommunes, agreger)
    @param[in] cle_contours, cle_df : colonnes de jointure cote contours et cote stats
    @param[in] prefixe      : prefixe des cles du panneau ("r", "d" ou "c")
    @param[in] details, titres : dicts remplis pour le panneau lateral

    @return GeoDataFrame (cle, nom, geometry, colonnes de popup)
    """
    g = contours.merge(df, left_on=cle_contours, right_on=cle_df, how="left")

    n     = colonne(g, "n")
    prod  = colonne(g, "prod_an_kwh_s")
    tot   = colonne(g, "surf_m2_s")
    plate = colonne(g, "surf_m2_plat_s")
    pct   = (plate / tot * 100).where(tot > 0)

    g["p_prod"] = prod.map(lambda v: formater(v, "Wh"))
    g["p_toit"] = n.map(lambda v: formater(v, ""))
    g["p_plat"] = pct.map(lambda v: "-" if v != v else f"{v:.1f} %")
    g["p_incl"] = pct.map(lambda v: "-" if v != v else f"{100 - v:.1f} %")

    boutons = []
    for _, ligne in g.iterrows():
        if pd.notna(ligne.get("n")):
            cle = prefixe + str(ligne[cle_contours])
            details[cle] = valeursDetails(ligne, g.columns)
            titres[cle] = str(ligne["nom"])
            boutons.append(f"<button class=\"btn-sobre\" "
                           f"onclick=\"montrerDetails('{cle}')\">Voir le détail</button>")
        else:
            boutons.append("")
    g["p_btn"] = boutons
    g["p_fill"] = [1 if b else 0 for b in boutons]

    for c in ("p_prod", "p_toit", "p_plat", "p_incl"):
        g[c] = g[c].replace("-", "Non calculé")
    return g[[cle_contours, "nom", "geometry", "p_prod", "p_toit", "p_plat", "p_incl", "p_btn", "p_fill"]]


def couche(gdf, alias_nom, couleur, epaisseur, note="", champs_sup=()):
    """
    Couche folium d'un niveau : contours + tooltip + popup de synthese.
    --------
    @param[in] gdf        : sortie de preparer
    @param[in] alias_nom  : libelle de la ligne de tete de la popup
    @param[in] couleur, epaisseur : style du trait de contour
    @param[in] note       : suffixe ajoute aux libelles production / toitures
    @param[in] champs_sup : lignes de popup en plus, liste de (colonne, alias)

    @return folium.GeoJson : couche a ajouter a la carte
    """
    champs = ["nom", "p_prod", "p_toit", "p_plat", "p_incl", *(c for c, _ in champs_sup), "p_btn"]
    alias  = [alias_nom, f"Production PV / an{note} :", f"Nb de toitures{note} :",
              "Toits plats :", "Toits inclinés :", *(a for _, a in champs_sup), ""]
    return folium.GeoJson(
        gdf,
        style_function=lambda x: {"color": couleur, "weight": epaisseur, "fillColor": REMPLI,
                                  "fillOpacity": OPACITE if x["properties"]["p_fill"] else 0.0},
        highlight_function=lambda x: {"weight": epaisseur + 2, "fillOpacity": OPACITE_SURVOL},
        tooltip=folium.GeoJsonTooltip(fields=["nom"], aliases=[alias_nom]),
        popup=folium.GeoJsonPopup(fields=champs, aliases=alias))


def construireCarte(stats):
    """
    Genere le HTML de la carte depuis le cache de stats.
    --------
    @param[in] stats : contenu du cache (voir majStats)

    @return chemin du HTML ecrit (FICHIER_CARTE)
    """
    gdf_reg = chargerContours("region")
    gdf_dep = chargerContours("departement").drop_duplicates("code")
    gdf_reg["geometry"] = gdf_reg.geometry.simplify(0.002, preserve_topology=True)
    gdf_dep["geometry"] = gdf_dep.geometry.simplify(0.002, preserve_topology=True)

    df_com = tableauCommunes(stats)
    df_com["dep"] = df_com["code"].str[:2]
    dep_region = gdf_dep.set_index("code")["region"]
    regions_avec = {dep_region.get(d) for d in set(df_com["dep"])} - {None}
    gdf_com = chargerContours("communes", [r for r in REGIONS
                                           if r.replace("-", " ").title() in regions_avec])

    total_par_dep = gdf_com.groupby(gdf_com["code"].str[:2]).size()
    avec_par_dep  = df_com.groupby("dep").size()
    complets = [d for d, nb in avec_par_dep.items()
                if nb >= SEUIL_DEP_COMPLET * total_par_dep.get(d, float("inf"))]

    df_dep = agreger(df_com[df_com["dep"].isin(complets)].drop(columns="code"), "dep")
    df_dep["region"] = df_dep["dep"].map(dep_region)
    df_reg = agreger(df_dep.drop(columns="dep"), "region")

    gdf_com = gdf_com[gdf_com["code"].str[:2].isin(set(df_com["dep"]))].copy()
    gdf_com["geometry"] = gdf_com.geometry.simplify(0.001, preserve_topology=True)

    details, titres = {}, {}
    g_reg = preparer(gdf_reg, df_reg, "region", "region", "r", details, titres)
    g_dep = preparer(gdf_dep, df_dep.drop(columns="region"), "code", "dep", "d", details, titres)
    g_com = preparer(gdf_com, df_com, "code", "code", "c", details, titres)

    nb_total = gdf_dep.groupby("region").size()
    nb_ok    = df_dep.groupby("region").size()
    g_reg["p_deps"] = g_reg["region"].map(lambda r: f"{int(nb_ok.get(r, 0))} / {int(nb_total.get(r, 0))}")
    g_reg["p_fill"] = (g_reg["region"].map(nb_ok).fillna(0) >= g_reg["region"].map(nb_total)).astype(int)

    carte = folium.Map(location=(46.8, 2.3), zoom_start=6, tiles=None,
                       control_scale=True, prefer_canvas=True)
    fondsDeCarte(carte)

    fg_reg = folium.FeatureGroup(name="Régions", control=False)
    fg_dep = folium.FeatureGroup(name="Départements", control=False, show=False)
    fg_com = folium.FeatureGroup(name="Communes", control=False, show=False)
    couche(g_reg, "Région :", "#5D6D7E", 2, note=" (dép. complets)",
           champs_sup=(("p_deps", "Départements complets :"),)).add_to(fg_reg)
    couche(g_dep, "Département :", "#1A252C", 1.5).add_to(fg_dep)
    if not g_com.empty:
        couche(g_com, "Commune :", "#7F8C8D", 1.2).add_to(fg_com)
    fg_reg.add_to(carte)
    fg_dep.add_to(carte)
    fg_com.add_to(carte)
    folium.LayerControl(position="topleft", collapsed=True).add_to(carte)

    niveaux = [f"[{fg_reg.get_name()}, 0, {ZOOM_DEP}]",
               f"[{fg_dep.get_name()}, {ZOOM_DEP}, 99]",
               f"[{fg_com.get_name()}, {ZOOM_COM}, 99]"]
    js_zoom = f"""
    <script>
    document.addEventListener("DOMContentLoaded", function () {{
        var carte = {carte.get_name()};
        var niveaux = [{", ".join(niveaux)}];
        function majNiveaux() {{
            var z = carte.getZoom();
            niveaux.forEach(function (nv) {{
                if (z >= nv[1] && z < nv[2]) {{ if (!carte.hasLayer(nv[0])) carte.addLayer(nv[0]); }}
                else {{ if (carte.hasLayer(nv[0])) carte.removeLayer(nv[0]); }}
            }});
        }}
        carte.on("zoomend", majNiveaux);
        majNiveaux();
    }});
    </script>"""

    libelles = [lib for lib, _ in config.COLONNES_SORTIE.values()]
    js_details = f"""
    <div id="panneau-details" class="encart">
        <span id="detail-fermer" onclick="fermerDetails()">&#10005;</span>
        <div id="detail-contenu"></div>
    </div>
    <script>
    var LIBELLES = {json.dumps(libelles, ensure_ascii=False)};
    var TITRES = {json.dumps(titres, ensure_ascii=False)};
    var DETAILS = {json.dumps(details, ensure_ascii=False)};
    function montrerDetails(cle) {{
        var d = DETAILS[cle];
        if (!d) return;
        var html = "<h3>" + TITRES[cle] + "</h3>"
                 + "<p class='encart-note'>total, puis par bâtiment</p>";
        html += "<table class='tbl-stats'><tr class='entete'><th></th><th>total</th>"
              + "<th>médiane</th><th>moyenne</th><th>P10–P90</th></tr>";
        for (var i = 0; i < d.length; i++) {{
            if (!d[i]) continue;
            html += "<tr><th>" + LIBELLES[i] + "</th><td>" + d[i][0] + "</td><td>"
                  + d[i][1] + "</td><td>" + d[i][2] + "</td><td class='interv'>"
                  + d[i][3] + "</td></tr>";
        }}
        document.getElementById("detail-contenu").innerHTML = html + "</table>";
        document.getElementById("panneau-details").style.display = "block";
    }}
    function fermerDetails() {{
        document.getElementById("panneau-details").style.display = "none";
    }}
    </script>"""

    lignes = ""
    for affiche, nom in sorted((n.replace(".gpkg", "").replace("-", " "), n)
                               for n in stats["fichiers"]):
        lignes += (f"<li>{affiche}"
                   f"{mentionIncomplet(os.path.join(config.OUT_DIR_PROCESSED, nom))}</li>")
    secteurs = f"""
    <div id="secteurs" class="encart">
        <div class="encart-titre">Secteurs traités ({len(stats["fichiers"])})</div>
        <ul>{lignes}</ul>
    </div>"""

    for element in (CSS, CSS_CARTE, secteurs, js_details, js_zoom):
        carte.get_root().html.add_child(folium.Element(element))

    os.makedirs(os.path.dirname(FICHIER_CARTE), exist_ok=True)
    carte.save(FICHIER_CARTE)
    return FICHIER_CARTE


def genererCarte(on_log=print):
    """
    Met a jour le cache de stats puis regenere le HTML seulement si necessaire.
    --------
    @param[in] on_log : callback (message) pour suivre l'avancement

    @return chemin du HTML de la carte
    """
    stats, change = majStats(on_log)
    if change or not os.path.exists(FICHIER_CARTE):
        on_log("construction de la carte")
        construireCarte(stats)
    return FICHIER_CARTE


def viderCache():
    """
    Supprime le cache de stats et le HTML.
    --------
    @return None
    """
    for chemin in (FICHIER_STATS, FICHIER_CARTE):
        if os.path.exists(chemin):
            os.remove(chemin)


def ouvrirCarte(chemin):
    """
    Ouvre la carte dans une fenetre pywebview, ou dans le navigateur sans pywebview.
    --------
    @param[in] chemin : chemin du HTML

    @return None
    """
    try:
        import webview
    except ImportError:
        import webbrowser
        webbrowser.open(Path(chemin).resolve().as_uri())
        return
    webview.create_window("Carte des résultats", chemin, width=1200, height=800)
    webview.start()
