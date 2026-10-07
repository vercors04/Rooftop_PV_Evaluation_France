import os
import json
import threading
from pathlib import Path

import folium
import geopandas as gpd
import pyogrio
from folium.plugins import Draw
from shapely.geometry import box, shape
from shapely import make_valid

from src import config
from src.acquisition.zone import zone
from executable.tool_fct_exe import resume, cellules, echelleGpkg, fichiers, mentionIncomplet
from executable.carte_style import CSS, TRAIT, REMPLI, OPACITE, OPACITE_SURVOL, fondsDeCarte

FICHIER_STATS = os.path.join(config.DIR_CARTES, "stats_polygones.json")
FICHIER_CARTE = os.path.join(config.DIR_CARTES, "carte_dessin.html")
FICHIER_TRACE = os.path.join(config.DIR_CARTES, "dernier_trace.json")
FICHIER_LISTE = os.path.join(config.DIR_CARTES, "zones_tracees.json")

COTE_DALLE = 1000.0
MAX_CASES  = 40000
SEUIL_ATTENTION = 40
SEUIL_GRAVE     = 200
SEC_PAR_DALLE   = 12

LOCALE = """
<script>
var d = L.drawLocal.draw;
d.toolbar.buttons.polygon   = "Tracer un polygone";
d.toolbar.buttons.rectangle = "Tracer un rectangle";
d.toolbar.actions.title = "Annuler";  d.toolbar.actions.text = "Annuler";
d.toolbar.finish.title  = "Terminer"; d.toolbar.finish.text  = "Terminer";
d.toolbar.undo.title = "Retirer le dernier point"; d.toolbar.undo.text = "Dernier point";
d.handlers.polygon.tooltip.start = "Cliquez pour commencer.";
d.handlers.polygon.tooltip.cont  = "Cliquez pour continuer.";
d.handlers.polygon.tooltip.end   = "Cliquez le premier point pour fermer.";
d.handlers.rectangle.tooltip.start = "Cliquez-glissez pour tracer.";
d.handlers.simpleshape.tooltip.end = "Relachez pour terminer.";
</script>
"""

PANNEAU = """
<div id="panneau" class="encart"
     style="position:fixed;top:10px;right:10px;z-index:9999;width:290px">
  <div class="encart-titre">Tracer une zone</div>
  <div id="infos"></div>
  <div id="bloc-nom" style="margin-top:8px;display:none">
    <label>Nom de la zone<br>
      <input id="nom" type="text" style="width:100%;box-sizing:border-box;padding:4px"
             placeholder="ex : quartier_gare"></label>
    <div style="margin-top:8px;display:flex;gap:6px">
      <button id="valider" class="btn-sobre" style="flex:1">Valider</button>
      <button id="effacer" class="btn-sobre" style="flex:1">Effacer</button>
    </div>
  </div>
</div>
"""

SCRIPT = """
document.addEventListener('DOMContentLoaded', function () {
  var trace = null, couche = null;
  var carte = CARTE;
  var infos = document.getElementById('infos');
  var blocNom = document.getElementById('bloc-nom');
  var COULEURS = {ok: '#1E8449', attention: '#B9770E', grave: '#922B21'};

  function afficher(r) {
    infos.innerHTML = '<div style="color:' + (COULEURS[r.niveau] || '#333') + '">'
                    + '<b>' + r.surface + ' km²</b><br>' + r.message + '</div>';
    blocNom.style.display = 'block';
  }

  function effacer() {
    if (couche) { carte.removeLayer(couche); couche = null; }
    trace = null;
    infos.innerHTML = '';
    blocNom.style.display = 'none';
  }

  function pont() {
    return window.pywebview && window.pywebview.api ? window.pywebview.api : null;
  }

  function horsApp() {
    infos.innerHTML = "<div style='color:#922B21'>Ouvert hors de l'application : "
                    + "le tracé ne peut pas être renvoyé.</div>";
  }

  carte.on('draw:created', function (e) {
    effacer();
    couche = e.layer;
    carte.addLayer(couche);
    trace = couche.toGeoJSON();
    var api = pont();
    if (api) { api.estimer(trace).then(afficher); } else { horsApp(); }
  });

  document.getElementById('effacer').onclick = effacer;
  document.getElementById('valider').onclick = function () {
    if (!trace) { return; }
    var api = pont();
    if (!api) { horsApp(); return; }
    api.valider(trace, document.getElementById('nom').value.trim()).then(function (r) {
      if (!r.ok) { infos.innerHTML = '<div style="color:#922B21">' + r.message + '</div>'; }
    });
  };
});
"""


def estimerDalles(polygone_l93):
    """
    Majorant du nombre de dalles : cases kilometriques Lambert 93 touchees par le polygone, ou
    par sa boite au-dela de MAX_CASES.
    --------
    @param[in] polygone_l93 : geometrie shapely Lambert 93

    @return n_dalles : majorant
    @return serre    : True si le compte suit le contour, False s'il suit la boite
    """
    minx, miny, maxx, maxy = polygone_l93.bounds
    i0, i1 = int(minx // COTE_DALLE), int(maxx // COTE_DALLE)
    j0, j1 = int(miny // COTE_DALLE), int(maxy // COTE_DALLE)
    cases = (i1 - i0 + 1) * (j1 - j0 + 1)
    if cases > MAX_CASES:
        return cases, False
    n = sum(1 for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)
            if polygone_l93.intersects(box(i * COTE_DALLE, j * COTE_DALLE,
                                           (i + 1) * COTE_DALLE, (j + 1) * COTE_DALLE)))
    return n, True


def avertissement(n_dalles, serre):
    """
    Niveau et message d'avertissement selon la taille de la zone.
    --------
    @param[in] n_dalles : majorant du nombre de dalles (voir estimerDalles)
    @param[in] serre    : True si le majorant suit le contour

    @return niveau  : "ok", "attention" ou "grave"
    @return message : texte du panneau
    """
    duree = n_dalles * SEC_PAR_DALLE / 60.0
    duree_txt = f"{duree:.0f} min" if duree < 90 else f"{duree/60:.1f} h"
    combien = (f"jusqu'à {n_dalles} dalles" if serre
               else f"bien plus de {n_dalles} dalles")
    fin = "Les dalles sans bâtiment sont sautées : le calcul sera plus court."
    if n_dalles >= SEUIL_GRAVE:
        return "grave", (f"{combien}, au plus {duree_txt}. Une zone tracée n'est pas découpée "
                         "en sous-tâches (un calcul interrompu reprend aux dalles manquantes). "
                         "Préférez plusieurs zones plus petites.")
    if n_dalles >= SEUIL_ATTENTION:
        return "attention", f"{combien}, soit au plus {duree_txt} de calcul. {fin}"
    return "ok", f"{combien}, au plus {duree_txt}. {fin}"


def tracesCalculees():
    """
    Zones tracees deja calculees : gpkg dont les metadonnees portent echelle="polygone".
    --------
    @return dict {nom_gpkg: chemin}
    """
    chemins = {nom: os.path.join(config.OUT_DIR_PROCESSED, nom)
               for nom in fichiers(config.OUT_DIR_PROCESSED, ".gpkg")}
    return {nom: c for nom, c in chemins.items() if echelleGpkg(c) == "polygone"}


def agregerZone(chemin):
    """
    Resume un gpkg de zone tracee : compte, somme, mediane et quantiles P10/P90.
    --------
    @param[in] chemin : chemin du .gpkg (1 ligne par batiment)

    @return dict {"n", "somme", "med", "p10", "p90"}
    """
    champs = set(pyogrio.read_info(chemin)["fields"])
    cols = [c for c in config.COLONNES_SORTIE if c in champs]
    return resume(gpd.read_file(chemin, columns=["cleabs", *cols], ignore_geometry=True), cols)


def majStats(on_log=print):
    """
    Met a jour le cache : agrege les zones nouvelles ou modifiees, retire les disparues.
    --------
    @param[in] on_log : callback (message)

    @return stats, change : contenu du cache et bool indiquant s'il a change
    """
    stats = {"version": 1, "zones": {}}
    if os.path.exists(FICHIER_STATS):
        try:
            with open(FICHIER_STATS, encoding="utf-8") as f:
                charge = json.load(f)
            if charge.get("version") == 1:
                stats = charge
        except (json.JSONDecodeError, OSError):
            pass

    presents = {nom: os.path.getmtime(chemin) for nom, chemin in tracesCalculees().items()}
    change = False
    for nom in list(stats["zones"]):
        if nom not in presents:
            del stats["zones"][nom]
            change = True

    for nom, mtime in presents.items():
        if stats["zones"].get(nom, {}).get("mtime") == mtime:
            continue
        on_log(f"agregation de {nom}")
        stats["zones"][nom] = {"mtime": mtime,
                               **agregerZone(os.path.join(config.OUT_DIR_PROCESSED, nom))}
        change = True

    if change:
        os.makedirs(os.path.dirname(FICHIER_STATS), exist_ok=True)
        with open(FICHIER_STATS, "w", encoding="utf-8") as f:
            json.dump(stats, f)
    return stats, change


def popupZone(nom, d):
    """
    Tableau HTML de synthese : total, mediane, moyenne et P10-P90 par colonne de sortie.
    --------
    @param[in] nom : nom du gpkg
    @param[in] d   : entree du cache pour cette zone

    @return chaine HTML
    """
    lignes = []
    for c, (libelle, unite) in config.COLONNES_SORTIE.items():
        if c not in d["somme"] or d["n"] == 0:
            continue
        total, med, moy, interv = cellules(d, c, unite)
        lignes.append(f"<tr><th>{libelle}</th><td>{total}</td><td>{med}</td>"
                      f"<td>{moy}</td><td class='interv'>{interv}</td></tr>")
    return (f"<b>{os.path.splitext(nom)[0]}</b>"
            f"<p class='encart-note'>{d['n']} bâtiments</p>"
            f"<table class='tbl-stats'>"
            f"<tr class='entete'><th></th><th>total</th><th>médiane</th><th>moyenne</th>"
            f"<th>P10–P90</th></tr>{''.join(lignes)}</table>")


def listeZones(stats):
    """
    Encart listant les zones tracees deja calculees.
    --------
    @param[in] stats : contenu du cache

    @return chaine HTML
    """
    lignes = ""
    noms = sorted(n for n, d in stats["zones"].items() if d["n"] > 0)
    for nom in noms:
        lignes += (f"<li>{os.path.splitext(nom)[0]}"
                   f"{mentionIncomplet(os.path.join(config.OUT_DIR_PROCESSED, nom))}</li>")
    return (f'<div id="secteurs" class="encart">'
            f'<div class="encart-titre">Zones tracées ({len(noms)})</div>'
            f'<ul>{lignes}</ul></div>')


def construireCarte(stats):
    """
    Ecrit le HTML : zones deja calculees, outil de dessin et panneau lateral.
    --------
    @param[in] stats : contenu du cache

    @return chemin du HTML ecrit
    """
    carte = folium.Map(location=(46.8, 2.3), zoom_start=6, tiles=None,
                       control_scale=True, prefer_canvas=True)
    fondsDeCarte(carte)

    fg = folium.FeatureGroup(name="Zones déjà calculées")
    for nom, d in stats["zones"].items():
        contour = zone("polygone", os.path.splitext(nom)[0])
        if contour is None or d["n"] == 0:
            continue
        folium.GeoJson(
            contour.__geo_interface__,
            style_function=lambda _: {"color": TRAIT, "weight": 2, "fillColor": REMPLI,
                                      "fillOpacity": OPACITE},
            highlight_function=lambda _: {"weight": 4, "fillOpacity": OPACITE_SURVOL},
            tooltip=os.path.splitext(nom)[0],
            popup=folium.Popup(popupZone(nom, d), max_width=620,
                               max_height=460)).add_to(fg)
    fg.add_to(carte)

    Draw(export=False, position="topleft", show_geometry_on_click=False,
         draw_options={"polyline": False, "circle": False, "circlemarker": False,
                       "marker": False, "polygon": {"showArea": True}, "rectangle": True},
         edit_options={"edit": False, "remove": False}).add_to(carte)
    folium.LayerControl(position="topleft", collapsed=True).add_to(carte)

    carte.get_root().html.add_child(folium.Element(CSS))
    carte.get_root().html.add_child(folium.Element(LOCALE))
    carte.get_root().html.add_child(folium.Element(PANNEAU))
    carte.get_root().html.add_child(folium.Element(listeZones(stats)))
    carte.get_root().script.add_child(folium.Element(SCRIPT.replace("CARTE", carte.get_name())))

    os.makedirs(os.path.dirname(FICHIER_CARTE), exist_ok=True)
    carte.save(FICHIER_CARTE)
    return FICHIER_CARTE


def genererCarteDessin(on_log=print):
    """
    Met a jour le cache puis regenere le HTML si necessaire.
    --------
    @param[in] on_log : callback (message)

    @return chemin du HTML
    """
    stats, change = majStats(on_log)
    if change or not os.path.exists(FICHIER_CARTE):
        on_log("construction de la carte de traçage")
        construireCarte(stats)
    return FICHIER_CARTE


def viderCacheDessin():
    """
    Supprime le cache de stats et le HTML.
    --------
    @return None
    """
    for chemin in (FICHIER_STATS, FICHIER_CARTE):
        if os.path.exists(chemin):
            os.remove(chemin)


def listeTraces():
    """
    Noms des zones tracees, filtres par l'existence de leur GeoJSON.
    --------
    @return liste de noms, triee
    """
    try:
        with open(FICHIER_LISTE, encoding="utf-8") as f:
            noms = json.load(f)
    except (json.JSONDecodeError, OSError):
        noms = []
    return sorted(n for n in noms
                  if os.path.exists(os.path.join(config.DIR_GEOJSON, f"{n}.geojson")))


def enregistrerTrace(nom):
    """
    Ajoute un nom au registre des zones tracees.
    --------
    @param[in] nom : nom de la zone

    @return None
    """
    noms = set(listeTraces()) | {nom}
    os.makedirs(os.path.dirname(FICHIER_LISTE), exist_ok=True)
    with open(FICHIER_LISTE, "w", encoding="utf-8") as f:
        json.dump(sorted(noms), f, ensure_ascii=False)


def polygoneValide(geojson):
    """
    Polygone shapely d'un trace Leaflet, contours croises repares.
    --------
    @param[in] geojson : Feature ou geometrie GeoJSON, WGS84

    @return polygone shapely WGS84 ; leve ValueError si le trace ne delimite aucune surface
    """
    geo = geojson.get("geometry", geojson)
    poly = make_valid(shape(geo))
    if poly.geom_type == "GeometryCollection":
        surfaces = [g for g in poly.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not surfaces:
            raise ValueError("le tracé ne délimite aucune surface")
        poly = max(surfaces, key=lambda g: g.area)
    if poly.geom_type not in ("Polygon", "MultiPolygon") or poly.is_empty:
        raise ValueError("le tracé ne délimite aucune surface")
    return poly


_FENETRE = None


class API:
    """Methodes appelees depuis la page par pywebview.api."""

    def estimer(self, geojson):
        """
        Surface et nombre de dalles du trace, avec l'avertissement associe.
        --------
        @param[in] geojson : Feature GeoJSON du trace, en WGS84

        @return dict {"surface", "niveau", "message"}
        """
        try:
            poly = polygoneValide(geojson)
        except ValueError as e:
            return {"surface": "-", "niveau": "grave", "message": str(e)}
        l93 = gpd.GeoSeries([poly], crs=4326).to_crs(2154).iloc[0]
        niveau, message = avertissement(*estimerDalles(l93))
        return {"surface": f"{l93.area / 1e6:.2f}", "niveau": niveau, "message": message}

    def valider(self, geojson, nom):
        """
        Ecrit le contour en Lambert 93 dans DIR_GEOJSON, puis ferme la fenetre ; refuse le nom
        d'une zone administrative deja calculee.
        --------
        @param[in] geojson : Feature GeoJSON du trace, en WGS84
        @param[in] nom     : nom de la zone (caracteres non alphanumeriques retires)

        @return dict {"ok", "message"}
        """
        nom = "".join(c for c in (nom or "").strip().replace(" ", "_")
                      if c.isalnum() or c in "_-").strip("_-")
        if not nom:
            return {"ok": False, "message": "Donnez un nom à la zone."}
        pris = (os.path.exists(os.path.join(config.DIR_GEOJSON, f"{nom}.geojson"))
                or os.path.exists(os.path.join(config.OUT_DIR_PROCESSED, f"{nom}.gpkg")))
        if pris and nom not in listeTraces():
            return {"ok": False, "message": "Nom déjà pris par une zone calculée."}
        try:
            poly = polygoneValide(geojson)
        except ValueError as e:
            return {"ok": False, "message": str(e)}

        os.makedirs(config.DIR_GEOJSON, exist_ok=True)
        l93 = gpd.GeoDataFrame(geometry=[poly], crs=4326).to_crs(2154)
        l93.to_file(os.path.join(config.DIR_GEOJSON, f"{nom}.geojson"), driver="GeoJSON")
        n, serre = estimerDalles(l93.geometry.iloc[0])
        enregistrerTrace(nom)
        with open(FICHIER_TRACE, "w", encoding="utf-8") as f:
            json.dump({"nom": nom, "surface_km2": l93.geometry.iloc[0].area / 1e6,
                       "n_dalles": n, "niveau": avertissement(n, serre)[0]}, f,
                      ensure_ascii=False)

        if _FENETRE is not None:
            threading.Timer(0.3, _FENETRE.destroy).start()
        return {"ok": True, "message": ""}


def ouvrirCarteDessin(chemin):
    """
    Ouvre la carte de tracage dans une fenetre pywebview, ou dans le navigateur (sans retour du
    trace).
    --------
    @param[in] chemin : chemin du HTML

    @return None
    """
    if os.path.exists(FICHIER_TRACE):
        os.remove(FICHIER_TRACE)
    try:
        import webview
    except ImportError:
        import webbrowser
        webbrowser.open(Path(chemin).resolve().as_uri())
        return
    global _FENETRE
    api = API()
    _FENETRE = webview.create_window("Carte de traçage", chemin,
                                     js_api=api, width=1200, height=800)
    webview.start()


def lireTrace():
    """
    Dernier trace valide.
    --------
    @return dict {"nom", "surface_km2", "n_dalles" (majorant), "niveau" (voir avertissement)} ;
            None si rien n'a ete valide
    """
    if not os.path.exists(FICHIER_TRACE):
        return None
    try:
        with open(FICHIER_TRACE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
