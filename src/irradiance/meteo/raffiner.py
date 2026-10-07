import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.irradiance.meteo.main_meteo import choisirZone
from src.irradiance.meteo.grille_calculs import grilleCellules, construireTables, ecartsCellule
from src.irradiance.meteo.grille_fct import cheminTable
from src.tuile.donnees_dalle import enMetropole
from src import config

S_PAR_SOUS_CELLULE = 35


def lireEcarts():
    """
    Ecarts deja mesures, par cellule (config.ECARTS_FIN).
    --------
    @return dict {(lat, lon): [(lat_fin, lon_fin, ecart), ...]}
    """
    ecarts = {}
    if os.path.exists(config.ECARTS_FIN):
        with open(config.ECARTS_FIN, newline="") as f:
            for l in csv.DictReader(f):
                ecarts.setdefault((float(l["lat"]), float(l["lon"])), []).append(
                    (float(l["lat_fin"]), float(l["lon_fin"]), float(l["ecart"])))
    return ecarts


def mesurer(cellules, ecarts):
    """
    Mesure en parallele les cellules absentes de ecarts ; chaque mesure est ajoutee a ecarts
    et a config.ECARTS_FIN.
    --------
    @param[in] cellules : (lat, lon) des centres
    @param[in] ecarts   : dict rendu par lireEcarts, complete en place

    @return nombre de cellules en echec
    """
    a_faire = [c for c in cellules if c not in ecarts]
    if not a_faire:
        return 0
    os.makedirs(config.DOSSIER_FIN, exist_ok=True)
    nouveau = not os.path.exists(config.ECARTS_FIN)
    echecs, t0 = 0, time.time()
    with open(config.ECARTS_FIN, "a", newline="") as f, ThreadPoolExecutor(config.N_THREADS) as ex:
        ecrire = csv.writer(f)
        if nouveau:
            ecrire.writerow(["lat", "lon", "lat_fin", "lon_fin", "ecart"])
        futurs = {ex.submit(ecartsCellule, *c): c for c in a_faire}
        for k, fu in enumerate(as_completed(futurs), 1):
            c = futurs[fu]
            try:
                ecarts[c] = fu.result()
                ecrire.writerows([(*c, *e) for e in ecarts[c]])
                f.flush()
            except Exception as e:
                echecs += 1
                print(f"  {c[0]:.2f}, {c[1]:.2f}  ECHEC : {e}")
            if k % 100 == 0 or k == len(a_faire):
                print(f"  [{k}/{len(a_faire)}] cellules mesurees en {time.time() - t0:.0f} s")
    return echecs


def main():
    """
    Mesure les ecarts des cellules de la zone choisie, puis construit les sous-cellules au-dela
    de config.ECART_FIN.
    --------
    @return None
    """
    polygone = choisirZone()
    if polygone is None:
        return
    cellules = [c for c in grilleCellules(polygone) if enMetropole(*c)]
    ecarts = lireEcarts()
    n = sum(c not in ecarts for c in cellules)
    print(f"{len(cellules)} cellules, {n} a mesurer ({5 * n} appels PVGIS)")
    if mesurer(cellules, ecarts):
        print("relancer pour mesurer les cellules en echec")

    mesurees = [c for c in cellules if c in ecarts]
    sous = [(la, lo) for c in mesurees for la, lo, e in ecarts[c] if e > config.ECART_FIN]
    reste = [s for s in sous if not os.path.exists(cheminTable(*s, fine=True))]
    pire = max((e for c in mesurees for _, _, e in ecarts[c] if e == e), default=0.0)
    en_mer = sum(e != e for c in mesurees for _, _, e in ecarts[c])
    print(f"{len(sous)} sous-cellules sur {4 * len(mesurees)} a plus de {100 * config.ECART_FIN:g} % "
          f"de leur cellule (ecart max {100 * pire:.1f} %, {en_mer} sans donnee PVGIS), "
          f"{len(sous) - len(reste)} deja construites")
    if not reste:
        return
    duree = len(reste) * S_PAR_SOUS_CELLULE / config.N_COEURS / 3600
    if input(f"Construire les {len(reste)} restantes, environ {duree:.1f} h sur {config.N_COEURS} "
             f"coeurs (reprise possible) ? (o/n) : ").strip().lower() != "o":
        return
    construireTables(reste, fine=True)


if __name__ == "__main__":
    main()
