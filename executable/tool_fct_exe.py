import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import geopandas as gpd

from src import config
from src.pipeline import dallesManquantes, effacerReprise, lireMetadonnees


def ouvrirDossier(chemin):
    """
    Ouvre un dossier dans l'explorateur de fichiers du systeme ; sous Linux, l'executable
    lance xdg-open avec le LD_LIBRARY_PATH d'origine, pas celui des bibliotheques embarquees.
    --------
    @param[in] chemin : chemin du dossier

    @return None
    """
    if sys.platform == "win32":
        os.startfile(chemin)
        return
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        origine = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if origine is None:
            env.pop("LD_LIBRARY_PATH", None)
        else:
            env["LD_LIBRARY_PATH"] = origine
    subprocess.Popen(["xdg-open", chemin], env=env)


def formater(valeur, unite):
    """
    Formate une valeur avec un prefixe adapte (k, M, G, T, P pour Wh/Wc, km2 pour m2).
    --------
    @param[in] valeur : valeur numerique (NaN tolere), en kWh ou kWc pour "Wh" ou "Wc"
    @param[in] unite  : "Wh", "Wc", "m2", "m", "deg", "ratio" ou ""

    @return chaine affichable ("-" si NaN)
    """
    if valeur != valeur:
        return "-"
    if unite in ("Wh", "Wc"):
        for seuil, prefixe in ((1e12, "P"), (1e9, "T"), (1e6, "G"), (1e3, "M")):
            if abs(valeur) >= seuil:
                return f"{valeur / seuil:.2f} {prefixe}{unite}"
        return f"{valeur:.2f} k{unite}"
    if unite == "m2" and abs(valeur) >= 1e6:
        return f"{valeur / 1e6:.2f} km2"
    if unite == "ratio":
        return f"{valeur:.2f}"
    if unite == "":
        return f"{valeur:,.0f}".replace(",", " ")
    return f"{valeur:,.1f} {unite}".replace(",", " ")


def resume(df, colonnes):
    """
    Effectif, somme, mediane, P10 et P90 de colonnes d'un tableau de batiments.
    --------
    @param[in] df       : DataFrame, 1 ligne par batiment
    @param[in] colonnes : colonnes a resumer

    @return dict {"n", "somme", "med", "p10", "p90"}, chaque statistique en {colonne: valeur}
    """
    return {"n":     int(len(df)),
            "somme": {c: float(df[c].sum()) for c in colonnes},
            "med":   {c: float(df[c].median()) for c in colonnes},
            "p10":   {c: float(df[c].quantile(0.10)) for c in colonnes},
            "p90":   {c: float(df[c].quantile(0.90)) for c in colonnes}}


def cellules(r, colonne, unite):
    """
    Total, mediane, moyenne et intervalle P10-P90 d'une colonne resumee, formates.
    --------
    @param[in] r       : resume (voir resume) ; med, p10, p90 facultatifs
    @param[in] colonne : nom de la colonne
    @param[in] unite   : unite d'affichage (voir formater)

    @return liste de 4 chaines ; "-" pour un total sans objet ou une statistique absente
    """
    med, p10, p90 = (r.get(cle, {}).get(colonne, float("nan")) for cle in ("med", "p10", "p90"))
    moyenne = r["somme"][colonne] / r["n"] if r["n"] else float("nan")
    total = "-" if unite in config.SANS_TOTAL else formater(r["somme"][colonne], unite)
    intervalle = "-" if p10 != p10 else f"{formater(p10, unite)} à {formater(p90, unite)}"
    return [total, formater(med, unite), formater(moyenne, unite), intervalle]


def echelleGpkg(chemin):
    """
    Echelle lue dans les metadonnees d'un gpkg de resultats.
    --------
    @param[in] chemin : chemin du .gpkg

    @return str ; "" si absente ou illisible
    """
    try:
        return lireMetadonnees(chemin).get("zone", {}).get("echelle", "")
    except Exception:
        return ""


def mentionIncomplet(chemin):
    """
    Mention d'un gpkg incomplet, pour les listes de zones des cartes.
    --------
    @param[in] chemin : chemin du .gpkg

    @return " (incomplet : k dalle(s) manquante(s))" ; "" si complet
    """
    k = len(dallesManquantes(chemin))
    return f" (incomplet : {k} dalle(s) manquante(s))" if k else ""


def fichiers(dossier, extension):
    """
    Fichiers d'un dossier portant une extension, tries.
    --------
    @param[in] dossier   : chemin du dossier
    @param[in] extension : extension, point compris (ex: ".gpkg")

    @return liste de noms ; [] si le dossier n'existe pas
    """
    if not os.path.isdir(dossier):
        return []
    return sorted(n for n in os.listdir(dossier) if n.endswith(extension))


def formaterDuree(secondes):
    """
    Duree lisible ('1h 12min 05s', '3min 42s', '8s').
    --------
    @param[in] secondes : duree (s)

    @return str
    """
    h, reste = divmod(int(secondes), 3600)
    m, s = divmod(reste, 60)
    if h:
        return f"{h}h {m:02d}min {s:02d}s"
    if m:
        return f"{m}min {s:02d}s"
    return f"{s}s"


def afficherBilan(bilan):
    """
    Formate le bilan retourne par runPipeline ou runPipelineDecoupe en lignes de texte, pour
    affichage GUI.
    --------
    @param[in] bilan : dict retourne par runPipeline ou runPipelineDecoupe, ou None

    @return lignes : liste de chaines, une par ligne a afficher
    """
    if not bilan:
        return ["Aucun bilan : zone introuvable, hors metropole, sans batiment ou sans dalle "
                "LiDAR HD."]

    lignes = []
    lignes.append(f"Fichier      : {bilan.get('fichier')}")
    lignes.append(f"Total dalles : {bilan.get('total')}")

    moy = bilan.get("moyennes_dalle", {})
    if moy:
        lignes.append("Temps moyens par dalle (s) :")
        for k, v in moy.items():
            lignes.append(f"   {k:<15}: {v:.3f}")

    glob = bilan.get("temps_globaux", {})
    if glob:
        lignes.append("Temps globaux :")
        for k, v in glob.items():
            lignes.append(f"   {k:<12}: {formaterDuree(v)}")

    bat = bilan.get("batiments", {})
    if bat:
        lignes.append("Batiments :")
        for k, v in bat.items():
            lignes.append(f"   {k:<20}: {v}")

    prot = bilan.get("protections", {})
    if prot:
        lignes.append("Protections :")
        for k, v in prot.items():
            lignes.append(f"   {k:<20}: {v}")

    erreur_relief = bilan.get("relief", {}).get("erreur")
    if erreur_relief:
        lignes.append(f"Relief indisponible, ombrage lointain absent : {erreur_relief}")

    def lieu(e):
        return f"{e['departement']}, {e['nom']}" if "departement" in e else e["nom"]

    echecs = bilan.get("echecs", [])
    if echecs:
        lignes.append(f"{len(echecs)} dalle(s) manquante(s) apres deux essais, resultat "
                      f"incomplet ; relancer la zone ne calculera qu'elles :")
        lignes += [f"   - {lieu(e)} : {e['erreur']}" for e in echecs]

    departements = bilan.get("departements_echec", [])
    if departements:
        lignes.append(f"{len(departements)} departement(s) en echec, refaits au prochain "
                      f"lancement :")
        lignes += [f"   - {d['nom']} : {d['erreur']}" for d in departements]

    return lignes


def listesFichiers(parent, geojson_dir, gpkg_dir, occupe):
    """
    Listes des geojson et des gpkg, avec suppression de la selection (dalles gardees et MNT de
    relief d'un gpkg compris), refusee pendant un calcul, et ouverture du dossier.
    --------
    @param[in] parent      : cadre ou ranger les listes
    @param[in] geojson_dir : dossier des .geojson
    @param[in] gpkg_dir    : dossier des .gpkg
    @param[in] occupe      : fonction () -> True si un calcul tourne

    @return fonction rafraichir
    """
    colonnes = ttk.Frame(parent); colonnes.pack(fill="both", expand=True)
    colonnes.columnconfigure(0, weight=1)
    colonnes.columnconfigure(1, weight=1)
    colonnes.rowconfigure(1, weight=1)

    ttk.Label(colonnes, text="geojson").grid(row=0, column=0)
    liste_geojson = tk.Listbox(colonnes, selectmode="extended")
    liste_geojson.grid(row=1, column=0, sticky="nsew", padx=2)

    ttk.Label(colonnes, text="gpkg").grid(row=0, column=1)
    liste_gpkg = tk.Listbox(colonnes, selectmode="extended")
    liste_gpkg.grid(row=1, column=1, sticky="nsew", padx=2)

    def rafraichir():
        for liste, dossier, extension in ((liste_geojson, geojson_dir, ".geojson"),
                                          (liste_gpkg, gpkg_dir, ".gpkg")):
            liste.delete(0, "end")
            for nom in fichiers(dossier, extension):
                liste.insert("end", nom)

    def supprimer(listbox, dossier):
        selection = listbox.curselection()
        if not selection:
            return
        if occupe():
            messagebox.showerror("Suppression", "Calcul en cours : suppression possible à la fin.")
            return
        noms = [listbox.get(i) for i in selection]
        if not messagebox.askyesno("Confirmer", f"Supprimer {len(noms)} fichier(s) ?\n" + "\n".join(noms)):
            return
        for nom in noms:
            try:
                os.remove(os.path.join(dossier, nom))
            except OSError as e:
                messagebox.showerror("Suppression", f"{nom} : {e}")
                continue
            if nom.endswith(".gpkg"):
                effacerReprise(os.path.splitext(nom)[0])
        rafraichir()

    ttk.Button(colonnes, text="Supprimer",
               command=lambda: supprimer(liste_geojson, geojson_dir)).grid(row=2, column=0, pady=2)
    ttk.Button(colonnes, text="Supprimer",
               command=lambda: supprimer(liste_gpkg, gpkg_dir)).grid(row=2, column=1, pady=2)

    ttk.Button(parent, text="Ouvrir dans l'explorateur",
               command=lambda: ouvrirDossier(os.path.dirname(geojson_dir))).pack(pady=4)

    ttk.Button(parent, text="Rafraîchir", command=rafraichir).pack(pady=5)

    rafraichir()
    return rafraichir


def statsRapide(parent_selec, gpkg_dir, parent_stats):
    """
    Liste des gpkg et statistiques du fichier choisi (total, mediane, moyenne, P10-P90).
    --------
    @param[in] parent_selec : cadre de la liste des fichiers
    @param[in] gpkg_dir     : dossier des .gpkg
    @param[in] parent_stats : cadre des statistiques

    @return fonction rafraichir
    """
    parent_selec.columnconfigure(1, weight=1)
    parent_selec.rowconfigure(1, weight=1)

    liste_gpkg = tk.Listbox(parent_selec, selectmode="browse")
    liste_gpkg.grid(row=1, column=1, sticky="nsew", padx=2)

    scrollbar_gpkg = ttk.Scrollbar(parent_selec, orient="vertical", command=liste_gpkg.yview)
    scrollbar_gpkg.grid(row=1, column=2, sticky="ns")
    liste_gpkg.configure(yscrollcommand=scrollbar_gpkg.set)

    scrollbar_x = ttk.Scrollbar(parent_stats, orient="horizontal", command=lambda *a: zone_stats.xview(*a))
    scrollbar_x.pack(side="bottom", fill="x")

    zone_stats = tk.Text(parent_stats, wrap="none", xscrollcommand=scrollbar_x.set)
    zone_stats.pack(fill="both", expand=True)
    zone_stats.configure(state="disabled")

    def rafraichir():
        liste_gpkg.delete(0, "end")
        for nom in fichiers(gpkg_dir, ".gpkg"):
            liste_gpkg.insert("end", nom)

    def afficher(texte):
        zone_stats.configure(state="normal")
        zone_stats.delete("1.0", "end")
        zone_stats.insert("1.0", texte)
        zone_stats.configure(state="disabled")

    def selection():
        choix = liste_gpkg.curselection()
        return liste_gpkg.get(choix[0]) if choix else None

    def stats():
        nom = selection()
        if nom is None:
            return
        btn_stats.configure(state="disabled")
        afficher("Calcul en cours...")
        threading.Thread(target=calcul, args=(nom,), daemon=True).start()

    def calcul(nom):
        try:
            chemin = os.path.join(gpkg_dir, nom)
            gdf = gpd.read_file(chemin, ignore_geometry=True)
            lignes = [f"Fichier : {nom}", f"Nombre de toitures : {len(gdf)}"]
            manquantes = dallesManquantes(chemin)
            if manquantes:
                lignes.append(f"Incomplet : {len(manquantes)} dalle(s) manquante(s), "
                              f"voir les métadonnées")
            lignes.append("")
            colonnes = [c for c in config.COLONNES_SORTIE if c in gdf.columns]
            r = resume(gdf, colonnes)
            for c in colonnes:
                libelle, unite = config.COLONNES_SORTIE[c]
                total, med, moy, intervalle = cellules(r, c, unite)
                texte = f"médiane={med}  moyenne={moy}  P10–P90={intervalle}"
                if unite not in config.SANS_TOTAL:
                    texte = f"total={total}  " + texte
                lignes.append(f"{libelle:<30}: {texte}")
            resultat = "\n\n".join(lignes)
        except Exception as e:
            resultat = f"[ERREUR] {nom} : {e}"

        def montrer():
            afficher(resultat)
            btn_stats.configure(state="normal")
        zone_stats.after(0, montrer)

    def metadonnees():
        nom = selection()
        if nom is None:
            return
        try:
            meta = lireMetadonnees(os.path.join(gpkg_dir, nom))
            afficher(json.dumps(meta, indent=2, ensure_ascii=False))
        except Exception as e:
            afficher(f"[ERREUR] {nom} : {e}")

    ttk.Button(parent_selec, text="Rafraîchir", command=rafraichir).grid(row=2, column=1, pady=2)
    btn_stats = ttk.Button(parent_selec, text="Statistiques", command=stats)
    btn_stats.grid(row=3, column=1, pady=2)
    ttk.Button(parent_selec, text="Métadonnées", command=metadonnees).grid(row=4, column=1, pady=2)

    rafraichir()
    return rafraichir
