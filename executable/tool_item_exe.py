import math
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

import requests

DELAI_SUGGESTION_MS = 300
POLICE_FIXE = "Consolas" if sys.platform == "win32" else "monospace"
TAILLE_ICONE = 128
MOLETTE = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def onglets(parent):
    """
    Conteneur d'onglets.
    --------
    @param[in] parent : fenetre

    @return ttk.Notebook
    """
    return ttk.Notebook(parent)


def onglet(notebook, titre):
    """
    Ajoute un onglet au conteneur.
    --------
    @param[in] notebook : conteneur d'onglets
    @param[in] titre    : titre de l'onglet

    @return Frame de l'onglet
    """
    f = ttk.Frame(notebook)
    notebook.add(f, text=titre)
    return f


def bulleAide(parent, message):
    """
    '?' cliquable qui affiche un message d'aide.
    --------
    @param[in] parent  : cadre ou ranger le '?'
    @param[in] message : texte de l'aide

    @return None
    """
    q = ttk.Label(parent, text="?", foreground="blue", cursor="hand2")
    q.pack(side="left", padx=(4, 0))
    q.bind("<Button-1>", lambda e: messagebox.showinfo("Aide", message))


def bouton(parent, libelle, commande, aide=None):
    """
    Bouton avec bulle d'aide optionnelle.
    --------
    @param[in] parent   : cadre ou ranger le bouton
    @param[in] libelle  : texte du bouton
    @param[in] commande : fonction appelee au clic
    @param[in] aide     : texte de la bulle d'aide (optionnel)

    @return Button
    """
    ligne = ttk.Frame(parent); ligne.pack(pady=5)
    b = ttk.Button(ligne, text=libelle, command=commande)
    b.pack(side="left")
    if aide:
        bulleAide(ligne, aide)
    return b


def fenetre(titre="", largeur=600, hauteur=400, icone=None):
    """
    Fenetre principale.
    --------
    @param[in] titre   : titre de la fenetre
    @param[in] largeur : largeur (px)
    @param[in] hauteur : hauteur (px)
    @param[in] icone   : chemin de l'icone sans extension, .ico sous Windows, .png ailleurs ;
                         ignoree si le fichier manque (optionnel)

    @return Tk
    """
    fen = tk.Tk()
    fen.title(titre)
    fen.geometry(f"{largeur}x{hauteur}")
    chemin = None if icone is None else icone + (".ico" if sys.platform == "win32" else ".png")
    if chemin is not None and os.path.exists(chemin):
        if sys.platform == "win32":
            fen.iconbitmap(chemin)
        else:
            image = tk.PhotoImage(master=fen, file=chemin)
            fen.iconphoto(True, image.subsample(max(1, image.width() // TAILLE_ICONE)))
    fen.columnconfigure(0, weight=1)
    fen.rowconfigure(0, weight=1)
    return fen


def boite(parent, titre):
    """
    Cadre avec titre.
    --------
    @param[in] parent : fenetre ou cadre parent
    @param[in] titre  : titre du cadre

    @return LabelFrame
    """
    return ttk.LabelFrame(parent, text=titre)


def radioBoutons(parent, libelle, options, defaut, on_change=None, aide=None):
    """
    Groupe de boutons radio.
    --------
    @param[in] parent    : cadre ou ranger le groupe
    @param[in] libelle   : titre affiche au-dessus
    @param[in] options   : liste des choix
    @param[in] defaut    : choix initial
    @param[in] on_change : fonction appelee a chaque changement (optionnel)
    @param[in] aide      : texte de la bulle d'aide (optionnel)

    @return StringVar du choix courant
    """
    ligne_titre = ttk.Frame(parent); ligne_titre.pack(anchor="w", fill="x", pady=(4, 0))
    ttk.Label(ligne_titre, text=libelle).pack(side="left")
    if aide:
        bulleAide(ligne_titre, aide)

    var = tk.StringVar(value=defaut)
    cb = ttk.Frame(parent)
    cb.pack(anchor="w", fill="x")

    for opt in options:
        ttk.Radiobutton(cb, text=opt, value=opt, variable=var,
                        command=on_change).pack(side="left", padx=5)
    return var


def barreProgression(parent):
    """
    Barre de progression de 0 a 100.
    --------
    @param[in] parent : cadre

    @return Progressbar
    """
    return ttk.Progressbar(parent, maximum=100)


def zoneLogs(parent, hauteur=10):
    """
    Zone de texte deroulante.
    --------
    @param[in] parent  : cadre
    @param[in] hauteur : nombre de lignes visibles

    @return ScrolledText
    """
    return scrolledtext.ScrolledText(parent, height=hauteur)


def champ(parent, libelle, defaut, aide=None, largeur=18):
    """
    Ligne 'libelle : [saisie]'.
    --------
    @param[in] parent  : cadre ou ranger le champ
    @param[in] libelle : texte a gauche
    @param[in] defaut  : valeur initiale
    @param[in] aide    : texte de la bulle d'aide (optionnel)
    @param[in] largeur : largeur du libelle (caracteres)

    @return Entry (texte a convertir)
    """
    ligne = ttk.Frame(parent); ligne.pack(fill="x", pady=2)
    ttk.Label(ligne, text=libelle, width=largeur).pack(side="left")
    e = ttk.Entry(ligne); e.insert(0, str(defaut)); e.pack(side="left", fill="x", expand=True)
    if aide:
        bulleAide(ligne, aide)
    return e


def champ2(parent, libelle, defaut, aide=None):
    """
    Comme champ, avec un libelle large (45 caracteres).
    --------
    @param[in] parent, libelle, defaut, aide : voir champ

    @return Entry (texte a convertir)
    """
    return champ(parent, libelle, defaut, aide, largeur=45)


def listeDeroulante(parent, libelle, options, defaut, aide=None):
    """
    Ligne 'libelle : [liste deroulante]', choix unique en lecture seule.
    --------
    @param[in] parent  : cadre ou ranger la liste
    @param[in] libelle : texte a gauche
    @param[in] options : liste des choix
    @param[in] defaut  : choix initial
    @param[in] aide    : texte de la bulle d'aide (optionnel)

    @return Combobox
    """
    ligne = ttk.Frame(parent); ligne.pack(fill="x", pady=2)
    ttk.Label(ligne, text=libelle, width=45).pack(side="left")
    cb = ttk.Combobox(ligne, values=options, state="readonly")
    cb.set(defaut)
    cb.pack(side="left", fill="x", expand=True)
    if aide:
        bulleAide(ligne, aide)
    return cb


def case(parent, libelle, defaut, aide=None):
    """
    Case a cocher.
    --------
    @param[in] parent  : cadre ou ranger la case
    @param[in] libelle : texte de la case
    @param[in] defaut  : etat initial (bool)
    @param[in] aide    : texte de la bulle d'aide (optionnel)

    @return BooleanVar
    """
    ligne = ttk.Frame(parent); ligne.pack(fill="x", pady=2)
    var = tk.BooleanVar(value=defaut)
    ttk.Checkbutton(ligne, text=libelle, variable=var).pack(side="left", pady=2)
    if aide:
        bulleAide(ligne, aide)
    return var


def menuCoches(parent, libelle, options, defaut, aide=None):
    """
    Bouton ouvrant un panneau de cases a cocher, par colonnes de 5.
    --------
    @param[in] parent  : cadre ou ranger le bouton
    @param[in] libelle : texte a gauche
    @param[in] options : liste des choix
    @param[in] defaut  : choix coches au depart
    @param[in] aide    : texte de la bulle d'aide (optionnel)

    @return dict {option: BooleanVar}
    """
    variables = {opt: tk.BooleanVar(value=(opt in defaut)) for opt in options}

    ligne = ttk.Frame(parent); ligne.pack(fill="x", pady=2)
    ttk.Label(ligne, text=libelle, width=18).pack(side="left")
    btn = ttk.Button(ligne); btn.pack(side="left")
    if aide:
        bulleAide(ligne, aide)
    etat = {"pop": None}

    def majTexte():
        n = sum(v.get() for v in variables.values())
        btn.configure(text=f"{n} sélectionné(s)  ▾")

    for v in variables.values():
        v.trace_add("write", lambda *_: majTexte())

    def ouvrir():
        if etat["pop"] is not None and etat["pop"].winfo_exists():
            etat["pop"].lift()
            return

        pop = tk.Toplevel(btn); etat["pop"] = pop
        pop.title(libelle)
        pop.transient(btn.winfo_toplevel())
        pop.geometry(f"+{btn.winfo_rootx()}+{btn.winfo_rooty() + btn.winfo_height()}")

        opts    = list(variables.items())
        ncols   = math.ceil(len(opts) / 5)
        par_col = math.ceil(len(opts) / ncols)
        for idx, (opt, v) in enumerate(opts):
            ttk.Checkbutton(pop, text=opt, variable=v).grid(
                row=idx % par_col, column=idx // par_col, sticky="w", padx=10, pady=2)

        ttk.Button(pop, text="OK", command=pop.destroy).grid(
            row=par_col, column=0, columnspan=ncols, pady=6)

    btn.configure(command=ouvrir)
    majTexte()
    return variables


def boiteDefilante(parent, titre):
    """
    Cadre avec titre dont le contenu defile verticalement.
    --------
    @param[in] parent : fenetre ou cadre parent
    @param[in] titre  : titre du cadre

    @return exterieur, interieur : cadre a placer, cadre a remplir
    """
    exterieur = ttk.LabelFrame(parent, text=titre)
    canvas = tk.Canvas(exterieur, highlightthickness=0)
    scrollbar = ttk.Scrollbar(exterieur, orient="vertical", command=canvas.yview)
    interieur = ttk.Frame(canvas)
    fenetre_id = canvas.create_window((0, 0), window=interieur, anchor="nw")

    interieur.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(fenetre_id, width=e.width))
    canvas.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    def molette(event):
        canvas.yview_scroll({4: -1, 5: 1}.get(event.num, int(-1 * (event.delta / 120))), "units")

    def lier(event):
        for sequence in MOLETTE:
            canvas.bind_all(sequence, molette)

    def delier(event):
        for sequence in MOLETTE:
            canvas.unbind_all(sequence)

    canvas.bind("<Enter>", lier)
    canvas.bind("<Leave>", delier)

    return exterieur, interieur


def comboSuggestions(parent, libelle, url, parametres, suggestions, n_min, largeur=30):
    """
    Liste deroulante completee au fil de la saisie par une API de suggestion, interrogee dans
    un fil a part apres DELAI_SUGGESTION_MS sans frappe.
    --------
    @param[in] parent      : cadre ou ranger la liste
    @param[in] libelle     : titre affiche au-dessus
    @param[in] url         : adresse de l'API
    @param[in] parametres  : fonction (texte saisi) -> parametres de la requete
    @param[in] suggestions : fonction (reponse JSON) -> liste de libelles
    @param[in] n_min       : nombre de caracteres avant la premiere requete
    @param[in] largeur     : largeur du champ (caracteres)

    @return Combobox
    """
    ttk.Label(parent, text=libelle).pack(anchor="w", pady=5)
    cb = ttk.Combobox(parent, width=largeur)
    cb.pack(anchor="w", pady=5)
    attente = {"id": None}

    def chercher(texte):
        try:
            valeurs = suggestions(requests.get(url, params=parametres(texte), timeout=2).json())
        except (requests.RequestException, ValueError, KeyError):
            return

        def appliquer():
            if cb.winfo_exists() and cb.get() == texte:
                cb["values"] = valeurs
        cb.after(0, appliquer)

    def lancer():
        attente["id"] = None
        texte = cb.get()
        if len(texte) < n_min:
            cb["values"] = []
            return
        threading.Thread(target=chercher, args=(texte,), daemon=True).start()

    def suggerer(event=None):
        if attente["id"] is not None:
            cb.after_cancel(attente["id"])
        attente["id"] = cb.after(DELAI_SUGGESTION_MS, lancer)

    def premier(event=None):
        if cb["values"]:
            cb.set(cb["values"][0])

    cb.bind("<KeyRelease>", suggerer)
    cb.bind("<Return>", premier)
    return cb
