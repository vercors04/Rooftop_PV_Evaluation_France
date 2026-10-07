import os
import queue
import threading
import multiprocessing
from tkinter import ttk, messagebox

from executable.tool_item_exe import (boiteDefilante, champ, case, champ2, fenetre, boite,
                                      menuCoches, onglets, radioBoutons, onglet, listeDeroulante,
                                      barreProgression, zoneLogs, bouton, bulleAide,
                                      comboSuggestions, POLICE_FIXE)
from executable.tool_fct_exe import afficherBilan, listesFichiers, statsRapide
from executable.carte_interactive import genererCarte, ouvrirCarte, viderCache
from executable.carte_dessin import (genererCarteDessin, ouvrirCarteDessin, lireTrace,
                                     listeTraces, viderCacheDessin)
from src.pipeline import runPipeline, runPipelineDecoupe
from src import config


class Reglages:
    """Widgets de reglage de la fenetre, ranges par mode de lecture."""

    def __init__(self):
        """
        Registres vides, remplis par les onglets a leur construction.
        --------
        @return None
        """
        self.entiers = {}
        self.flottants = {}
        self.listes = {}
        self.textes = {}
        self.cases = {}
        self.menus = {}

    def lire(self):
        """
        Valeurs saisies, pretes pour config.save ; virgule ou point decimal.
        --------
        @return dict {NOM: valeur} ; leve ValueError sur une saisie non numerique
        """
        valeurs = {nom: int(w.get()) for nom, w in {**self.entiers, **self.listes}.items()}
        valeurs.update({nom: w.get() for nom, w in self.textes.items()})
        valeurs.update({nom: float(w.get().replace(",", "."))
                        for nom, w in self.flottants.items()})
        valeurs.update({nom: var.get() for nom, var in self.cases.items()})
        valeurs.update({nom: [o for o, v in d.items() if v.get()]
                        for nom, d in self.menus.items()})
        return valeurs

    def defauts(self):
        """
        Remet tous les widgets aux valeurs de config.DEFAULTS.
        --------
        @return None
        """
        for nom, w in {**self.entiers, **self.flottants}.items():
            w.delete(0, "end")
            w.insert(0, str(config.DEFAULTS[nom]))
        for nom, w in {**self.listes, **self.textes}.items():
            w.set(config.DEFAULTS[nom])
        for nom, var in self.cases.items():
            var.set(config.DEFAULTS[nom])
        for nom, d in self.menus.items():
            for opt, var in d.items():
                var.set(opt in config.DEFAULTS[nom])


class Appli:
    """Etat partage entre les onglets."""

    def __init__(self, fen):
        """
        Fenetre, file des messages du calcul, calcul en cours et points d'accroche entre onglets.
        --------
        @param[in] fen : fenetre principale

        @return None
        """
        self.fen = fen
        self.file = queue.Queue()
        self.en_cours = False
        self.reglages = Reglages()
        self.rafraichir = []
        self.rappels_trace = []

    def rafraichirFichiers(self):
        """
        Rejoue les rafraichissements de listes de fichiers annonces par les onglets.
        --------
        @return None
        """
        for f in self.rafraichir:
            f()

    def signalerZoneTracee(self):
        """
        Previent les onglets qu'une zone tracee vient d'etre enregistree.
        --------
        @return None
        """
        for f in self.rappels_trace:
            f()


def journal(parent, hauteur):
    """
    Zone de logs en lecture seule et ses commandes d'ecriture.
    --------
    @param[in] parent  : cadre ou ranger la zone
    @param[in] hauteur : nombre de lignes visibles

    @return zone, ecrire, vider
    """
    zone = zoneLogs(parent, hauteur=hauteur)
    zone.pack(fill="both", expand=True, pady=5)
    zone.configure(state="disabled")

    def ecrire(texte):
        zone.configure(state="normal")
        zone.insert("end", texte)
        zone.see("end")
        zone.configure(state="disabled")

    def vider():
        zone.configure(state="normal")
        zone.delete("1.0", "end")
        zone.configure(state="disabled")

    return zone, ecrire, vider


def boiteEmpilee(parent, titre):
    """
    Boite de reglages empilee dans une colonne defilante.
    --------
    @param[in] parent : cadre defilant
    @param[in] titre  : titre de la boite

    @return LabelFrame
    """
    b = boite(parent, titre)
    b.pack(fill="x", padx=8, pady=(4, 6))
    return b


def placements(mere):
    """
    Ordre et placement des enfants d'une boite, pour les cacher puis les remontrer a leur
    place.
    --------
    @param[in] mere : boite dont tous les enfants sont crees

    @return liste de (widget, options de pack)
    """
    liste = []
    for w in mere.winfo_children():
        if w.winfo_manager() == "pack":
            info = w.pack_info()
            info.pop("in", None)
        else:
            info = {"fill": "x", "padx": 8, "pady": (2, 6)}
        liste.append((w, info))
    return liste


def montrer(liste, caches):
    """
    Replace les enfants d'une boite dans leur ordre, sauf ceux a cacher.
    --------
    @param[in] liste  : sortie de placements
    @param[in] caches : widgets a cacher

    @return None
    """
    for w, _ in liste:
        w.pack_forget()
    for w, info in liste:
        if w not in caches:
            w.pack(**info)


def saisieZone(parent, echelle):
    """
    Widget de saisie de la zone, adapte a l'echelle choisie.
    --------
    @param[in] parent  : cadre a remplir
    @param[in] echelle : echelle choisie (voir config.ECHELLES)

    @return widget de saisie ; None si l'echelle n'en demande pas
    """
    if echelle == "Adresse":
        return comboSuggestions(
            parent, echelle, config.GEOCODAGE, lambda t: {"q": t, "limit": 10},
            lambda r: [f["properties"]["label"] for f in r.get("features", [])], 3, largeur=50)

    if echelle == "Commune ou ville":
        return comboSuggestions(
            parent, echelle, config.GEO_API + "/communes",
            lambda t: {"nom": t, "limit": 10, "fields": "nom,codeDepartement"},
            lambda r: [f'{c["nom"]} ({c["codeDepartement"]})' for c in r
                       if c["codeDepartement"] < "97"], 3)

    if echelle == "Département":
        return comboSuggestions(
            parent, echelle, config.GEO_API + "/departements", lambda t: {"nom": t, "limit": 10},
            lambda r: [f'{c["nom"]} ({c["code"]})' for c in r if c["code"] < "97"], 2)

    if echelle == "Région":
        return comboSuggestions(
            parent, echelle, config.GEO_API + "/regions", lambda t: {"nom": t, "limit": 10},
            lambda r: [c["nom"] for c in r if int(c["code"]) > 10], 2)

    if echelle == "Zone tracée":
        ttk.Label(parent, text="Zone tracée").pack(anchor="w", pady=5)
        liste = ttk.Combobox(parent, width=30, state="readonly", values=listeTraces())
        liste.pack(anchor="w", pady=5)
        if liste["values"]:
            liste.current(len(liste["values"]) - 1)
        else:
            ttk.Label(parent, text="Aucune zone tracée : voir l'onglet « Carte de traçage ».",
                      foreground="#8A4B08").pack(anchor="w")
        return liste

    return None


def zoneDemandee(echelle, saisie):
    """
    Traduit le choix de l'interface en arguments de runPipeline, ou de runPipelineDecoupe pour
    une region ou la France.
    --------
    @param[in] echelle : echelle choisie (voir config.ECHELLES)
    @param[in] saisie  : widget rendu par saisieZone

    @return echelle, nom_zone, code_dep ; leve ValueError si la saisie ne convient pas
    """
    if echelle == "France":
        return "nationale", "France", None

    texte = saisie.get().strip()
    if not texte:
        raise ValueError("Choisissez une zone.")

    if echelle == "Adresse":
        return "adresse", texte, None
    if echelle == "Région":
        return "region", texte, None
    if echelle == "Zone tracée":
        return "polygone", texte, None

    if echelle in ("Commune ou ville", "Département"):
        if "(" not in texte:
            raise ValueError("Sélectionnez une suggestion dans la liste (nom + code).")
        nom, code = texte.rsplit("(", 1)
        if echelle == "Département":
            return "departement", nom.strip(), None
        return "commune", nom.strip(), code.rstrip(")").strip()

    raise ValueError(f"Échelle inconnue : {echelle}")


def boiteParametresGlobaux(parent, reglages):
    """
    Reglages de tri des batiments et de sortie, dans une boite defilante.
    --------
    @param[in] parent   : cadre de l'onglet
    @param[in] reglages : registre a completer

    @return LabelFrame a placer
    """
    exterieur, b = boiteDefilante(parent, "paramètres globaux")

    reglages.entiers.update(
        SURF_MIN=champ(b, "Surface min (m2)", config.SURF_MIN),
        HAUT_MIN=champ(b, "Hauteur min (m)", config.HAUT_MIN, aide="p95 du toit au-dessus du sol"),
        HAUT_MAX=champ(b, "Hauteur max (m)", config.HAUT_MAX, aide="p95 du toit au-dessus du sol"),
        AZ_MIN=champ(b, "Azimut min", config.AZ_MIN,
                     aide="degrés, 0 = Nord, 90 = Est. Arc parcouru en sens horaire jusqu'au max."),
        AZ_MAX=champ(b, "Azimut max", config.AZ_MAX, aide="degrés, 0 = Nord, 90 = Est."),
        PENTE_PLAT=champ(b, "Pente plat (deg)", config.PENTE_PLAT,
                         aide="en dessous, le toit est plat"),
        PENTE_MAX=champ(b, "Pente max (deg)", config.PENTE_MAX,
                        aide="au-delà, le pixel est écarté. 70 au plus, ramené sinon."))
    reglages.flottants.update(
        SEUIL_IRRADIANCE=champ(b, "Seuil irradiance", config.SEUIL_IRRADIANCE,
                               aide="kWh/m²/an reçus, ombrage compris, pour les sorties « seuil »"))
    reglages.cases.update(
        CONSTRUCTION_LEGERE=case(b, "Inclure les constructions légères",
                                 config.CONSTRUCTION_LEGERE))
    reglages.menus.update(
        ATTRS_BATI=menuCoches(b, "Attributs BD TOPO", config.ATTRS_BDTOPO, config.ATTRS_BATI,
                              aide="attributs copiés dans le gpkg, souvent incomplets"),
        ETAT=menuCoches(b, "État", config.ETATS, config.ETAT),
        NATURE_OK=menuCoches(b, "Natures gardées", config.NATURES, config.NATURE_OK),
        USAGE_OK=menuCoches(b, "Usages gardés", config.USAGE_1, config.USAGE_OK,
                            aide="beaucoup de bâtiments sont notés « Indifférencié »"),
        PROTECTIONS_OK=menuCoches(b, "Protections", list(config.PROTECTIONS),
                                  config.PROTECTIONS_OK,
                                  aide="zones où un refus reste possible (L111-17). Une colonne "
                                       "par couche cochée ; marqué ne veut pas dire interdit."))
    reglages.cases.update(
        PROTECTIONS_EXCLURE=case(b, "Supprimer les bâtiments protégés", config.PROTECTIONS_EXCLURE,
                                 aide="retire du gpkg les bâtiments marqués au lieu de les "
                                      "signaler"))
    reglages.menus.update(
        SORTIE_GARDEES=menuCoches(b, "Colonnes de sortie", list(config.GROUPES_SORTIE),
                                  config.SORTIE_GARDEES,
                                  aide="colonnes écrites dans le gpkg ; toutes sont calculées"))
    return exterieur


def ongletCalcul(nb, app):
    """
    Onglet de lancement : choix de la zone, parametres globaux, progression et journal.
    --------
    @param[in] nb  : conteneur d'onglets
    @param[in] app : etat partage

    @return None
    """
    o = onglet(nb, "Calcul")
    o.columnconfigure(0, weight=1)
    o.columnconfigure(1, weight=1)
    o.rowconfigure(0, weight=1)
    boiteParametresGlobaux(o, app.reglages).grid(row=0, column=1, sticky="nsew", padx=10, pady=10)

    gauche = ttk.Frame(o)
    gauche.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    bcz = boite(gauche, "choix de la zone")
    bcz.pack(fill="x")

    champs = {}

    def rebatir():
        for w in sous.winfo_children():
            w.destroy()
        champs["zone"] = saisieZone(sous, echelle.get())

    echelle = radioBoutons(bcz, "Échelle", config.ECHELLES, "Commune ou ville", on_change=rebatir,
                           aide="Région et France : un fichier par département ; ceux déjà "
                                "complets sont sautés (supprimer le fichier pour refaire).")
    sous = ttk.Frame(bcz)
    sous.pack(fill="x")
    rebatir()
    app.rappels_trace.append(rebatir)

    bl = boite(gauche, "lancement")
    bl.pack(fill="both", expand=True, pady=(10, 0))
    btn = ttk.Button(bl, text="Lancer", command=lambda: lancer())
    btn.pack(anchor="w", pady=5)
    barre = barreProgression(bl)
    barre.pack(fill="x", pady=5)
    _, ecrire, vider = journal(bl, 8)

    def lancer():
        try:
            valeurs = app.reglages.lire()
            demande = zoneDemandee(echelle.get(), champs["zone"])
        except ValueError as e:
            ecrire(f"[ERREUR] {e}\n")
            return
        config.save(valeurs)
        app.en_cours = True
        btn.configure(state="disabled")
        barre["value"] = 0
        vider()
        threading.Thread(target=calculer, args=demande, daemon=True).start()

    def calculer(ech, nom_zone, code_dep):
        def onLog(msg):
            app.file.put(("log", msg))

        def onProgress(i, total):
            app.file.put(("progress", i, total))

        try:
            if ech in ("nationale", "region"):
                bilan = runPipelineDecoupe(ech, nom_zone, on_progress=onProgress, on_log=onLog)
            else:
                bilan = runPipeline(ech, nom_zone, code_dep, on_progress=onProgress, on_log=onLog)
            app.file.put(("done", bilan))
        except Exception as e:
            app.file.put(("error", str(e)))

    def depiler():
        try:
            while True:
                item = app.file.get_nowait()
                if item[0] == "log":
                    ecrire(item[1] + "\n")
                elif item[0] == "progress":
                    barre["value"] = item[1] * 100 // item[2]
                elif item[0] == "done":
                    app.en_cours = False
                    btn.configure(state="normal")
                    barre["value"] = 0
                    for ligne in afficherBilan(item[1]):
                        ecrire(ligne + "\n")
                    app.rafraichirFichiers()
                elif item[0] == "error":
                    app.en_cours = False
                    btn.configure(state="normal")
                    barre["value"] = 0
                    ecrire(f"[ERREUR] {item[1]}\n")
        except queue.Empty:
            pass
        app.fen.after(100, depiler)

    depiler()


def groupePv(parent, reglages):
    """
    Boite du modele photovoltaique et de ses coefficients thermiques.
    --------
    @param[in] parent   : cadre defilant
    @param[in] reglages : registre a completer

    @return dict : boite, sous-boite de Faiman, liste du type de pose
    """
    g = boiteEmpilee(parent, "Modèle photovoltaïque")
    reglages.flottants.update(
        RENDEMENT_MODULE=champ2(g, "Rendement du module PV", config.RENDEMENT_MODULE,
                                aide="aux conditions standard. 0,22 = 22 %."),
        PR_HORS_TEMP=champ2(g, "Performance ratio (hors température)", config.PR_HORS_TEMP,
                            aide="câblage, onduleur, salissures, désadaptation, "
                                 "indisponibilités."),
        GAMMA_MODULE=champ2(g, "Coefficient de température (/°C)", config.GAMMA_MODULE,
                            aide="perte par degré au-dessus de 25 °C. -0,0035 = -0,35 %/°C."),
        ALBEDO=champ2(g, "Albédo (réflectivité du sol)", config.ALBEDO,
                      aide="part du rayonnement réfléchie par le sol vers les plans inclinés."))
    pose = listeDeroulante(g, "Type de pose (pans inclinés)", list(config.POSES), config.POSE,
                           aide="fixe U0 et U1, sauf personnalisé. Surimposé : rails sur la "
                                "couverture ; intégré : remplace la couverture ; libre : châssis "
                                "ventilé.")
    reglages.textes.update(POSE=pose)

    faiman = boite(g, "Coefficients thermiques de Faiman")
    reglages.flottants.update(
        U0_FAIMAN=champ2(faiman, "U0 (W/m²/K)", config.U0_FAIMAN,
                         aide="échange module/air à vent nul. Plus bas = plus chaud."),
        U1_FAIMAN=champ2(faiman, "U1 (W·s/m³/K)", config.U1_FAIMAN,
                         aide="part de l'échange due au vent."))
    return {"boite": g, "faiman": faiman, "pose": pose}


def groupeToitsPlats(parent, reglages):
    """
    Boite des poses de toit plat et de leurs sous-boites (repartition, rangees sud, est-ouest).
    --------
    @param[in] parent   : cadre defilant
    @param[in] reglages : registre a completer

    @return dict : boite, sous-boites et listes deroulantes qui commandent l'affichage
    """
    g = boiteEmpilee(parent, "Toits plats")
    plat_pose = listeDeroulante(g, "Pose des modules", config.POSES_PLAT + ["mixte"],
                                config.PLAT_POSE,
                                aide="à plat : sur la membrane ; sud : rangées espacées ; "
                                     "est-ouest : paires dos à dos ; mixte : pose choisie par "
                                     "bâtiment.")
    reglages.textes.update(PLAT_POSE=plat_pose)

    mixte = boite(g, "Répartition")
    critere = listeDeroulante(mixte, "Critère", config.CRITERES_MIXTE, config.MIXTE_CRITERE,
                              aide="surface : surface plate du bâtiment. usage, nature : "
                                   "attributs BD TOPO.")
    seuil = champ2(mixte, "Seuil de surface plate (m²)", config.MIXTE_SEUIL_M2)
    reglages.menus.update(
        MIXTE_USAGES=menuCoches(mixte, "Usages retenus", config.USAGE_1, config.MIXTE_USAGES))
    ligne_usages = mixte.winfo_children()[-1]
    reglages.menus.update(
        MIXTE_NATURES=menuCoches(mixte, "Natures retenues", config.NATURES, config.MIXTE_NATURES))
    ligne_natures = mixte.winfo_children()[-1]
    si = listeDeroulante(mixte, "Pose si le critère est rempli", config.POSES_PLAT,
                         config.MIXTE_SI,
                         aide="surface : au-dessus du seuil. usage, nature : valeurs retenues.")
    sinon = listeDeroulante(mixte, "Pose sinon", config.POSES_PLAT, config.MIXTE_SINON)
    reglages.textes.update(MIXTE_CRITERE=critere, MIXTE_SI=si, MIXTE_SINON=sinon)
    reglages.flottants.update(MIXTE_SEUIL_M2=seuil)

    sud = boite(g, "Rangées sud")
    reglages.flottants.update(
        SUD_PENTE=champ2(sud, "Pente (deg)", config.SUD_PENTE,
                         aide="10 à 15 sur lestage, 20 à 35 sur structure."),
        SUD_AZIMUT=champ2(sud, "Azimut (deg)", config.SUD_AZIMUT, aide="0 = Nord, 180 = Sud."))
    espacement = listeDeroulante(sud, "Espacement", config.ESPACEMENTS_SUD, config.SUD_ESPACEMENT,
                                 aide="aucune ombre à midi au solstice d'hiver, selon la "
                                      "latitude.")
    gcr = champ2(sud, "Taux d'occupation au sol", config.SUD_GCR,
                 aide="surface de modules / surface du champ. 0,5 à 0,7.")
    reglages.textes.update(SUD_ESPACEMENT=espacement)
    reglages.flottants.update(SUD_GCR=gcr)

    eo = boite(g, "Est-ouest")
    reglages.flottants.update(
        EO_PENTE=champ2(eo, "Pente (deg)", config.EO_PENTE, aide="5 à 15."),
        EO_GCR=champ2(eo, "Taux d'occupation au sol", config.EO_GCR,
                      aide="surface de modules / surface du champ, deux faces. 0,8 à 0,95."))
    return {"boite": g, "mixte": mixte, "sud": sud, "eo": eo, "pose": plat_pose,
            "critere": critere, "si": si, "sinon": sinon, "espacement": espacement,
            "seuil": seuil, "gcr": gcr, "usages": ligne_usages, "natures": ligne_natures}


def groupeSurface(parent, reglages):
    """
    Boite de la surface equipable.
    --------
    @param[in] parent   : cadre defilant
    @param[in] reglages : registre a completer

    @return None
    """
    g = boiteEmpilee(parent, "Surface équipable")
    reglages.flottants.update(
        COUVERTURE_INCL=champ2(g, "Couverture des pans inclinés", config.COUVERTURE_INCL,
                               aide="part équipée : reculs, cheminées, calepinage."),
        EMPRISE_PLAT=champ2(g, "Emprise du champ sur les toits plats", config.EMPRISE_PLAT,
                            aide="part du toit plat sous le champ : reculs, accès, édicules."),
        RECUL_M=champ2(g, "Recul géométrique (m)", config.RECUL_M,
                       aide="écarte les pixels proches d'un bord ou d'un obstacle. "
                            "0 = désactivé ; sinon, baisser les taux ci-dessus."))


def groupeGeometrie(parent, reglages):
    """
    Boite de la detection de la geometrie et de l'ajustement de plan.
    --------
    @param[in] parent   : cadre defilant
    @param[in] reglages : registre a completer

    @return dict : boite, sous-boite d'ajustement, liste de la methode
    """
    g = boiteEmpilee(parent, "Détection de la géométrie")
    reglages.flottants.update(
        BUFFER=champ2(g, "Tampon autour des bâtiments (m)", config.BUFFER,
                      aide="marge autour des emprises BD TOPO."),
        MNH_MIN=champ2(g, "Hauteur min au-dessus du sol (m)", config.MNH_MIN,
                       aide="en dessous, le pixel n'est pas du toit."),
        RES_MNT_M=champ2(g, "Pas du MNT téléchargé (m)", config.RES_MNT_M,
                         aide="sert à la hauteur au-dessus du sol."))
    methode = listeDeroulante(g, "Méthode pente/orientation", ["plan", "differences"],
                              config.METHODE_PENTE,
                              aide="« plan » : moindres carrés, moins bruité. « differences » : "
                                   "méthode du rapport.")
    reglages.textes.update(METHODE_PENTE=methode)

    plan = boite(g, "Ajustement de plan")
    reglages.entiers.update(
        RAYON_PLAN=champ2(plan, "Demi-fenêtre d'ajustement (px)", config.RAYON_PLAN,
                          aide="1 = 3x3 (minimum), 2 = 5x5. Au-delà, les arêtes sont lissées."))
    reglages.flottants.update(
        RESIDU_MAX_M=champ2(plan, "Écart max au plan ajusté (m)", config.RESIDU_MAX_M,
                            aide="au-delà, le pixel est écarté (mur, rive). 0 = désactivé."),
        RESIDU_PAN_M=champ2(plan, "Seuil de réajustement sur demi-fenêtre (m)",
                            config.RESIDU_PAN_M,
                            aide="au-delà, pente réestimée sur la demi-fenêtre la plus plane. "
                                 "0 = désactivé."))
    return {"boite": g, "plan": plan, "methode": methode}


def groupeOmbrage(parent, reglages):
    """
    Boites de l'ombrage proche et de l'ombrage lointain.
    --------
    @param[in] parent   : cadre defilant
    @param[in] reglages : registre a completer

    @return None
    """
    g = boiteEmpilee(parent, "Ombrage proche")
    reglages.listes.update(
        N_DIRECTIONS=listeDeroulante(g, "Nombre de directions azimutales", config.DIVISEURS_360,
                                     config.N_DIRECTIONS,
                                     aide="36 = une direction tous les 10 degrés."))
    reglages.entiers.update(
        DIST_MAX_M=champ2(g, "Rayon de recherche (m)", config.DIST_MAX_M,
                          aide="portée sur le MNS fin ; la dalle est téléchargée élargie "
                               "d'autant."),
        PAS_RAYON_DIV=champ2(g, "Croissance du pas du rayon", config.PAS_RAYON_DIV,
                             aide="0 = exact. n : pas de 1 + d/n pixels à la distance d ; plus "
                                  "rapide, moins exact."))
    reglages.flottants.update(
        CAP=champ2(g, "Plafond solaire (deg)", config.CAP,
                   aide="au-delà, la direction est masquée et la recherche s'arrête."))

    loin = boiteEmpilee(parent, "Ombrage lointain (relief)")
    reglages.entiers.update(
        DIST_LOIN_M=champ2(loin, "Portée (m)", config.DIST_LOIN_M,
                           aide="portée sur le MNT de relief. 0 = désactivé."),
        RES_LOIN_M=champ2(loin, "Pas du MNT de relief (m)", config.RES_LOIN_M,
                          aide="plus fin = plus lourd, mais crédible plus près."),
        DIST_MIN_LOIN_M=champ2(loin, "Distance de confiance (m)", config.DIST_MIN_LOIN_M,
                               aide="en deçà, le relief n'ombre pas. Environ 20 fois le pas du "
                                    "MNT de relief."))


def groupeReseau(parent, reglages):
    """
    Boite du reseau, du telechargement et du parallelisme.
    --------
    @param[in] parent   : cadre defilant
    @param[in] reglages : registre a completer

    @return None
    """
    g = boiteEmpilee(parent, "Réseau, téléchargement et parallélisme")
    reglages.entiers.update(
        N_COEURS=champ2(g, "Nombre de cœurs (parallélisme)", config.N_COEURS,
                        aide="dalles traitées en parallèle."),
        N_THREADS=champ2(g, "Nombre de threads (requêtes WFS)", config.N_THREADS),
        COUNT=champ2(g, "Taille des paquets WFS", config.COUNT, aide="entités par requête WFS."),
        N_ESSAIS_WFS=champ2(g, "Essais WFS", config.N_ESSAIS_WFS,
                            aide="essais si la requête échoue."))
    reglages.flottants.update(PAUSE_WFS=champ2(g, "Pause entre essais WFS (s)", config.PAUSE_WFS))
    reglages.entiers.update(
        N_ESSAIS=champ2(g, "Essais téléchargement de dalle", config.N_ESSAIS))
    reglages.flottants.update(
        PAUSE_DL=champ2(g, "Pause entre essais de dalle (s)", config.PAUSE_DL))
    reglages.entiers.update(
        N_ESSAIS_DEPARTEMENT=champ2(g, "Essais par département", config.N_ESSAIS_DEPARTEMENT))
    reglages.flottants.update(
        PAUSE_DEPARTEMENT=champ2(g, "Pause entre essais de département (s)",
                                 config.PAUSE_DEPARTEMENT))


def ongletAvance(nb, app):
    """
    Onglet des reglages fins et de la liste des fichiers produits.
    --------
    @param[in] nb  : conteneur d'onglets
    @param[in] app : etat partage

    @return None
    """
    o = onglet(nb, "Paramètres avancés")
    o.columnconfigure(0, weight=1)
    o.columnconfigure(1, weight=1)
    o.rowconfigure(0, weight=1)
    exterieur, colonne = boiteDefilante(o, "paramètres avancés")
    exterieur.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    r = app.reglages
    pv = groupePv(colonne, r)
    plat = groupeToitsPlats(colonne, r)
    groupeSurface(colonne, r)
    geom = groupeGeometrie(colonne, r)
    groupeOmbrage(colonne, r)
    groupeReseau(colonne, r)

    places = {cle: placements(b) for cle, b in (("pv", pv["boite"]), ("geom", geom["boite"]),
                                                ("plat", plat["boite"]), ("mixte", plat["mixte"]),
                                                ("sud", plat["sud"]))}

    def majVisibilite(*_):
        choix = plat["pose"].get()
        poses = {plat["si"].get(), plat["sinon"].get()} if choix == "mixte" else {choix}
        montrer(places["pv"], set() if pv["pose"].get() == "personnalise" else {pv["faiman"]})
        montrer(places["geom"], set() if geom["methode"].get() == "plan" else {geom["plan"]})
        montrer(places["plat"], {b for b, vu in ((plat["mixte"], choix == "mixte"),
                                                 (plat["sud"], "sud" in poses),
                                                 (plat["eo"], "est-ouest" in poses)) if not vu})
        critere = plat["critere"].get()
        montrer(places["mixte"], {w for w, vu in ((plat["seuil"].master, critere == "surface"),
                                                  (plat["usages"], critere == "usage"),
                                                  (plat["natures"], critere == "nature"))
                                  if not vu})
        montrer(places["sud"], set() if plat["espacement"].get() == config.ESPACEMENTS_SUD[1]
                else {plat["gcr"].master})

    for liste in (pv["pose"], geom["methode"], plat["pose"], plat["critere"], plat["si"],
                  plat["sinon"], plat["espacement"]):
        liste.bind("<<ComboboxSelected>>", majVisibilite)
    majVisibilite()

    def enregistrer():
        if app.en_cours:
            messagebox.showerror("Paramètres", "Calcul en cours : enregistrement possible à la fin.")
            return
        try:
            valeurs = r.lire()
        except ValueError as e:
            messagebox.showerror("Paramètres", f"Valeur invalide dans un champ : {e}")
            return
        config.save(valeurs)
        messagebox.showinfo("Paramètres", "Paramètres enregistrés")

    ligne = ttk.Frame(colonne)
    ligne.pack(pady=8)
    ttk.Button(ligne, text="Réinitialiser les paramètres par défaut",
               command=lambda: (r.defauts(), majVisibilite())).pack(side="left", padx=3)
    ttk.Button(ligne, text="Enregistrer les paramètres",
               command=enregistrer).pack(side="left", padx=3)
    bulleAide(ligne, "enregistre les réglages sans lancer de calcul.")

    bfg = boite(o, "fichiers générés")
    bfg.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
    app.rafraichir.append(listesFichiers(bfg, config.DIR_GEOJSON, config.OUT_DIR_PROCESSED,
                                         lambda: app.en_cours))


def ongletCarte(nb):
    """
    Onglet de la carte des resultats.
    --------
    @param[in] nb : conteneur d'onglets

    @return None
    """
    o = onglet(nb, "Carte des résultats")
    o.columnconfigure(0, weight=1)
    o.rowconfigure(0, weight=1)
    b = boite(o, "carte interactive")
    b.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    ttk.Label(b, text="Carte des résultats calculés, mise à jour à chaque affichage."
              ).pack(pady=(30, 5))
    btn = bouton(b, "Afficher la carte", lambda: afficher(),
                 aide="les gpkg affichés doivent partager les mêmes paramètres.")
    bouton(b, "Vider le cache", lambda: vider(),
           aide="statistiques mises en cache ; à vider après une mise à jour de data/contours.")
    etat = ttk.Label(b, text="")
    etat.pack(pady=5)
    zone, ecrire, effacer = journal(b, 6)

    def vider():
        viderCache()
        etat.configure(text="Cache vidé : tout sera recalculé au prochain affichage.")

    def afficher():
        btn.configure(state="disabled")
        etat.configure(text="Préparation de la carte (jusqu'à 30 min pour toute la France).")
        effacer()
        threading.Thread(target=travail, daemon=True).start()

    def travail():
        def onLog(msg):
            zone.after(0, ecrire, msg + "\n")

        try:
            chemin = genererCarte(on_log=onLog)
            multiprocessing.Process(target=ouvrirCarte, args=(chemin,), daemon=True).start()
            msg = "Carte ouverte."
        except Exception as e:
            msg = f"[ERREUR] {e}"
        etat.after(0, lambda: (etat.configure(text=msg), btn.configure(state="normal")))


def ongletTracage(nb, app):
    """
    Onglet de la carte de tracage d'une emprise a la main.
    --------
    @param[in] nb  : conteneur d'onglets
    @param[in] app : etat partage

    @return None
    """
    o = onglet(nb, "Carte de traçage")
    o.columnconfigure(0, weight=1)
    o.rowconfigure(0, weight=1)
    b = boite(o, "zone tracée à la main")
    b.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    ttk.Label(b, justify="left",
              text="Dessiner l'emprise plutôt que choisir un contour administratif.\n"
                   "Une zone validée se lance depuis l'onglet principal, échelle "
                   "« Zone tracée ».").pack(pady=(25, 5))
    btn = bouton(b, "Ouvrir la carte de traçage", lambda: afficher(),
                 aide="taille annoncée avant validation. Un calcul interrompu reprend aux "
                      "dalles manquantes.")
    bouton(b, "Vider le cache", lambda: vider(),
           aide="cache des résultats, pour ne pas relire les gpkg à chaque affichage.")
    etat = ttk.Label(b, text="", justify="left")
    etat.pack(pady=5)
    zone, ecrire, effacer = journal(b, 6)

    def vider():
        viderCacheDessin()
        etat.configure(text="Cache vidé : la carte sera reconstruite au prochain affichage.")

    def afficher():
        btn.configure(state="disabled")
        etat.configure(text="Préparation de la carte...")
        effacer()
        threading.Thread(target=travail, daemon=True).start()

    def travail():
        def onLog(msg):
            zone.after(0, ecrire, msg + "\n")

        try:
            chemin = genererCarteDessin(on_log=onLog)
            p = multiprocessing.Process(target=ouvrirCarteDessin, args=(chemin,), daemon=True)
            p.start()
            p.join()
            trace = lireTrace()
            if trace:
                gros = " — pensez à la découper" if trace["niveau"] == "grave" else ""
                msg = (f"Zone « {trace['nom']} » enregistrée : {trace['surface_km2']:.2f} km², "
                       f"{trace['n_dalles']} dalles au plus{gros}.\n"
                       f"Choisissez l'échelle « Zone tracée » dans l'onglet principal.")
                zone.after(0, app.signalerZoneTracee)
            else:
                msg = "Fenêtre fermée sans validation : aucune zone enregistrée."
        except Exception as e:
            msg = f"[ERREUR] {e}"
        etat.after(0, lambda: (etat.configure(text=msg), btn.configure(state="normal")))


def ongletFichiers(nb, app):
    """
    Onglet des statistiques rapides d'un gpkg.
    --------
    @param[in] nb  : conteneur d'onglets
    @param[in] app : etat partage

    @return None
    """
    o = onglet(nb, "Info fichiers")
    for c in range(3):
        o.columnconfigure(c, weight=1, uniform="col")
    for l in range(2):
        o.rowconfigure(l, weight=1, uniform="row")

    liste = boite(o, "gpkg calculés")
    liste.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=10, pady=10)
    stats = boite(o, "statistiques")
    stats.grid(row=0, column=1, rowspan=2, columnspan=2, sticky="nsew", padx=10, pady=10)
    app.rafraichir.append(statsRapide(liste, config.OUT_DIR_PROCESSED, stats))


def ongletApropos(nb):
    """
    Onglet affichant a_propos.md.
    --------
    @param[in] nb : conteneur d'onglets

    @return None
    """
    o = onglet(nb, "À propos")
    o.columnconfigure(0, weight=1)
    o.rowconfigure(0, weight=1)
    b = boite(o, "à propos")
    b.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    texte = zoneLogs(b, hauteur=25)
    texte.pack(fill="both", expand=True)
    texte.configure(font=(POLICE_FIXE, 10))
    with open(os.path.join(config.BASE_DATA, "a_propos.md"), encoding="utf-8") as f:
        texte.insert("1.0", f.read())
    texte.configure(state="disabled")


def construire(fen):
    """
    Monte les onglets dans la fenetre.
    --------
    @param[in] fen : fenetre principale

    @return Appli
    """
    app = Appli(fen)
    nb = onglets(fen)
    nb.grid(row=0, column=0, sticky="nsew")
    ongletCalcul(nb, app)
    ongletAvance(nb, app)
    ongletCarte(nb)
    ongletTracage(nb, app)
    ongletFichiers(nb, app)
    ongletApropos(nb)
    return app


def main():
    """
    Ouvre la fenetre principale.
    --------
    @return None
    """
    for dossier in config.DOSSIERS_SORTIE:
        os.makedirs(dossier, exist_ok=True)

    fen = fenetre(f"roofTool {config.VERSION}", 1000, 500,
                  icone=os.path.join(config.BASE_DATA, "data", "assets", "logo_soleil"))
    construire(fen)

    try:
        import pyi_splash
        pyi_splash.close()
    except ImportError:
        pass

    fen.mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    multiprocessing.set_start_method("spawn")
    main()
