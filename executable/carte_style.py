import folium
from folium.plugins import Geocoder

from src import config

TRAIT   = "#1A5276"
REMPLI  = "#1A5276"
OPACITE = 0.18
OPACITE_SURVOL = 0.35

CSS = """
<style>
.leaflet-popup-content-wrapper { border-radius: 6px; }
.leaflet-popup-content { margin: 8px 12px; font-family: sans-serif; font-size: 13px;
                         color: #1A252C; }
.encart { background: #fff; border: 1px solid #999; border-radius: 6px; padding: 12px;
          font-family: sans-serif; font-size: 13px; color: #1A252C;
          box-shadow: 0 2px 8px rgba(0,0,0,.3); }
.encart-titre { font-weight: bold; border-bottom: 1px solid #ddd;
                padding-bottom: 5px; margin-bottom: 6px; }
.encart-note { color: #7F8C8D; font-size: 12px; margin: 2px 0 0 0; }
.btn-sobre { cursor: pointer; padding: 4px 10px; border: 1px solid #999; border-radius: 3px;
             background: #f2f2f2; color: #1A252C; font-family: sans-serif; font-size: 12.5px; }
.btn-sobre:hover { background: #e6e6e6; }
.tbl-stats, .leaflet-popup-content table { width: 100%; border-collapse: collapse;
    margin-top: 6px; font-family: sans-serif; font-size: 12.5px; }
.tbl-stats th, .tbl-stats td,
.leaflet-popup-content th, .leaflet-popup-content td { padding: 3px 7px; text-align: right;
    border-bottom: 1px solid #e8e8e8; color: #1A252C; font-weight: 400; }
.tbl-stats td, .leaflet-popup-content td { white-space: nowrap; }
.tbl-stats th:first-child, .tbl-stats td:first-child,
.leaflet-popup-content th:first-child,
.leaflet-popup-content td:first-child { text-align: left; }
.tbl-stats th, .leaflet-popup-content th { color: #555; font-weight: 600; }
.tbl-stats .entete th, .leaflet-popup-content .entete th { border-bottom: 1px solid #999; }
.tbl-stats .interv { color: #666; }
#secteurs { position: fixed; bottom: 25px; left: 25px; z-index: 9999;
            max-height: 260px; overflow-y: auto; }
#secteurs ul { list-style: none; padding: 0; margin: 0;
               font-size: 12.5px; line-height: 1.7; }
</style>"""


def fondsDeCarte(carte):
    """
    Ajoute les fonds Plan IGN, vue aerienne IGN, satellite Esri et la recherche d'adresse.
    --------
    @param[in] carte : folium.Map

    @return None
    """
    folium.TileLayer(tiles=config.TUILES_PLAN, attr=config.ATTRIB_IGN, name="Plan IGN",
                     overlay=False, control=True, max_zoom=19).add_to(carte)
    folium.TileLayer(tiles=config.TUILES_ORTHO, attr=config.ATTRIB_IGN, name="Vue aérienne",
                     overlay=False, control=True, show=False, max_zoom=19).add_to(carte)
    folium.TileLayer(tiles=config.TUILES_SATELLITE, attr=config.ATTRIB_ESRI,
                     name="Vue satellite (Esri)", overlay=False, control=True,
                     show=False).add_to(carte)
    Geocoder(position="topright", zoom=13, add_marker=False).add_to(carte)
