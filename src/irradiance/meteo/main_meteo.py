import os

from src.acquisition.zone import zone
from src.irradiance.meteo.grille_calculs import grilleCellules, construireTables
from src.tuile.donnees_dalle import enMetropole
from src import config


def contours():
    """
    Noms des contours presents dans DIR_GEOJSON (zones tracees et zones deja calculees),
    utilisables comme echelle "polygone".
    --------
    @return liste de noms, triee
    """
    if not os.path.isdir(config.DIR_GEOJSON):
        return []
    return sorted(os.path.splitext(n)[0] for n in os.listdir(config.DIR_GEOJSON)
                  if n.endswith(".geojson"))


def choisirZone():
    """
    Demande au terminal l'echelle et le nom de la zone.
    --------
    @return polygone shapely en WGS84 ; None si le choix est invalide ou la zone introuvable
    """
    print("Choix de l'echelle territoriale:")
    print("0 : Adresse\n1 : Commune\n2 : Departement\n3 : Region\n4 : France"
          "\n5 : Contour enregistre (zone tracee ou deja calculee)")
    choix = input("Choisissez l'echelle (0-5) : ").strip()

    code_dep = None
    if choix == "0":
        echelle, nom_zone = "adresse", input("Entrez une adresse : ").strip()
    elif choix == "1":
        echelle, nom_zone = "commune", input("Entrez une commune : ").strip()
        code_dep = input("Entrez le numero de departement : ").strip()
    elif choix == "2":
        echelle, nom_zone = "departement", input("Entrez un departement (nom ou numero) : ").strip()
    elif choix == "3":
        echelle, nom_zone = "region", input("Entrez le nom d'une region : ").strip()
    elif choix == "4":
        echelle, nom_zone = "nationale", "France"
    elif choix == "5":
        echelle = "polygone"
        print("contours disponibles :", ", ".join(contours()) or "aucun")
        nom_zone = input("Entrez le nom du contour : ").strip()
    else:
        print("Choisissez entre 0 et 5."); return None

    polygone = zone(echelle, nom_zone, code_dep)
    if polygone is None:
        print("zone introuvable")
    return polygone


def main():
    """
    Construit les tables meteo absentes de la zone choisie au terminal.
    --------
    @return None
    """
    os.makedirs(config.DOSSIER, exist_ok=True)
    polygone = choisirZone()
    if polygone is None:
        return

    pts = [c for c in grilleCellules(polygone) if enMetropole(*c)]
    print(f"{len(pts)} cellules a construire dans {config.DOSSIER}/ sur {config.N_COEURS} "
          f"coeurs (reprise possible)")
    ratees = construireTables(pts)
    if ratees:
        print(f"{len(ratees)} echec(s) : {ratees}")


if __name__ == "__main__":
    main()
