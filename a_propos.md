roofTool calcule le potentiel photovoltaïque des toitures de France
métropolitaine, bâtiment par bâtiment. Il produit un GeoPackage par zone, avec
une ligne par bâtiment. Les valeurs citées sont celles par défaut ; la plupart
se règlent dans l'interface.


Données
=======

- BD TOPO (IGN) : emprises et attributs des bâtiments ; contours des communes,
  départements et régions. WFS Géoplateforme (https://data.geopf.fr/wfs/ows),
  couches BDTOPO_V3:batiment, BDTOPO_V3:commune, BDTOPO_V3:departement,
  BDTOPO_V3:region.
- LiDAR HD (IGN) : MNS (surface, avec bâtiments et végétation) au pas de
  0,5 m et MNT (sol), en dalles de 1 km, Lambert 93. Dalles listées par la
  couche WFS IGNF_LIDAR-HD_METADONNEE:metadata, lues en WMS.
- PVGIS SARAH-3 (Commission européenne, JRC) : séries horaires 2005-2023 de
  direct, diffus, température de l'air et vent
  (https://re.jrc.ec.europa.eu/api/v5_3/).
- Protections : Géoportail de l'urbanisme et INPN, WFS Géoplateforme, couches
  wfs_sup:generateur_sup_s, wfs_sup:assiette_sup_s (types ac1, ac2, ac4) et
  patrinat_pn2:pn.
- Recherche de zone : API Géocodage IGN (https://data.geopf.fr/geocodage) pour
  les adresses, https://geo.api.gouv.fr pour les communes, départements et
  régions.


Méthode
=======

Le calcul se fait par dalle de 1 km, en parallèle (5 processus).

Bâtiments
---------

- Bâtiments BD TOPO de la zone : en service, hors constructions légères.
  Natures : indifférenciée ; industriel, agricole ou commercial. Usages :
  résidentiel, commercial et services, indifférencié, industriel, agricole.
- Un bâtiment appartient à la zone si son point intérieur y tombe.
- Emprise élargie de 0,8 m, puis rasterisée sur la dalle.
- Pixel de toit : dans l'emprise, à 1,5 m au moins au-dessus du sol (MNS − MNT).
- Hauteur du bâtiment : p95 de la hauteur au-dessus du sol sur ses pixels de
  toit, avant le tri par pente et planéité.

Géométrie
---------

- MNT lu à 1 m, ramené au pas du MNS (0,5 m).
- Pente et orientation : plan des moindres carrés sur une fenêtre de 3 × 3
  pixels, limitée au même bâtiment. Option : différences finies.
- Pixel écarté si l'écart quadratique moyen au plan dépasse 0,25 m. Cela retire
  surtout les murs, les rives et les obstacles.
- Écart au plan supérieur à 0,03 m : pente recalculée sur la plus plane des
  quatre demi-fenêtres. Cela corrige les faîtages.
- Plat : pente sous 10°. Incliné : de 10 à 45°. Au-delà : écarté.
- Incliné orienté : orientation entre 90 et 270° (est, sud, ouest).
- Surface d'un pixel : surface au sol / cos(pente).

Ombrage
-------

- Horizon proche : lancer de rayons sur le MNS, dans 36 directions, jusqu'à
  100 m. Le MNS est téléchargé avec 100 m de marge autour de la dalle. Une
  direction dont l'horizon dépasse 75° est masquée.
- Horizon lointain : MNT de relief à 50 m sur la zone et 20 km autour,
  téléchargé une fois par zone et supprimé quand elle est complète. Rayons de 1 à 20 km, depuis l'altitude médiane
  des toits de chaque cellule de 50 m.
- Horizon retenu : le plus haut des deux, par direction.
- Direct : compté si le soleil est au-dessus de l'horizon dans sa direction.
- Diffus, découpé selon Perez :
  - circumsolaire : masqué avec le direct ;
  - dôme isotrope : multiplié par le facteur de vue du ciel du plan ;
  - bande d'horizon (6,5°) : multipliée par sa part visible ;
  - réfléchi par le sol : multiplié par le facteur de vue du ciel.

Facteur de vue du ciel d'un plan de pente β et d'orientation α :

    f_ciel = 1 / (π (1 + cos β) / 2)
             × ∫∫ max(0, cos β sin e + sin β cos e cos(φ − α)) cos e de dφ

    φ de 0 à 2π ; e de e0(φ) à 90° ; e0 = le plus haut de l'horizon et de
    l'élévation où l'incidence s'annule.

Météo
-----

- Territoire découpé en cellules de 0,10°. Une table par cellule, construite
  une fois depuis la série PVGIS horaire 2005-2023 de son centre.
- Chaque heure est transposée sur 192 plans (Perez, albédo 0,20) : 24
  orientations (pas de 15°) × 8 pentes (0 à 70°, pas de 10°). Les heures sont
  ensuite moyennées par mois et par heure.
- La table garde aussi des profils des heures réelles : moments d'ordre 2 du
  direct et du diffus, température et vent pondérés par l'irradiance, variance
  du vent, coefficients de Perez. Ils servent à la température des modules et
  à l'ombrage du diffus.
- Sous-cellule de 0,05° (un pixel SARAH-3) : construite si son irradiation
  annuelle s'écarte de plus de 1 % de celle de sa cellule. Elle remplace la
  cellule pour ses dalles.
- Une dalle lit la table qui contient son centre. Chaque pixel est interpolé
  entre les quatre plans voisins de la table.
- L'albédo réglé (0,20) remplace celui des tables au calcul.

Production
----------

Température de cellule (Faiman) et perte de rendement, avec G l'irradiance du
module, V le vent et γ = −0,0035 /°C :

    T_cell = T_air + G / (U0 + U1 × V)
    f_T    = 1 + γ × (T_cell − 25)

- U0 et U1 dépendent de la pose des pans inclinés : surimposé (27,9 ; 1,56),
  intégré (23,5 ; 1,26), libre (25,0 ; 6,84) ou personnalisé.
- G × f_T dépend du carré de G. Il est calculé avec les profils des heures
  réelles, pas avec la moyenne.
- Production = irradiation des modules × f_T × surface de modules × rendement
  (0,22) × PR hors température (0,79).
- PR hors température : 0,76 / 0,962. 0,76 est le performance ratio mesuré par
  Leloux et al. (2012), température comprise. 0,962 est le f_T moyen d'un plan
  sud à 30° surimposé à Lille, Cloué et Montpellier. Il reste les pertes de
  câblage, d'onduleur, de salissure et de désadaptation.
- Puissance crête = surface de modules × rendement.

Surface de modules :

- Pans inclinés : surface × 0,60. Ce taux tient compte des reculs, des
  obstacles et du calepinage.
- Toits plats : surface × 0,75 (emprise du champ) × densité de la pose.
- Option recul (0 m) : pixels proches d'un bord ou d'un obstacle non équipés.

Toits plats
-----------

- À plat : modules posés sur le toit, densité 1, classe thermique intégrée.
- Sud : rangées à 15° face au sud, classe thermique libre. Espacement sans
  ombre à midi au solstice d'hiver (densité 0,60 environ à 46° N), ou taux
  fixé.
- Est-ouest : rangées dos à dos à 10°, densité 0,90, classe thermique
  surimposée.
- Mixte : est-ouest si la surface plate atteint 500 m², sud sinon. Le critère
  peut aussi être l'usage ou la nature du bâtiment.
- La rangée de devant ombre le direct et le diffus.
- L'irradiation reçue (colonnes irr) reste celle du toit. La production utilise
  le plan des modules.

Densité des rangées sud, avec β la pente des modules et φ la latitude :

    GCR = 1 / (cos β + sin β / tan h)      h = 90° − φ − 23,44°

Bâtiments retenus
-----------------

- Pixels sommés par bâtiment. Un bâtiment coupé par plusieurs dalles est
  recollé par son identifiant (cleabs).
- Gardés : surface posable de 5 m² au moins, hauteur de 2 à 300 m.

Protections
-----------

- Bâtiment marqué si son point intérieur tombe dans une zone : monument
  historique, abords de monument, site patrimonial remarquable, site classé ou
  inscrit, cœur de parc national (article L111-17 du code de l'urbanisme).
- Marqué ne veut pas dire interdit : l'autorité compétente peut imposer des
  conditions plutôt que refuser.
- Option « Supprimer les bâtiments protégés » : les bâtiments marqués sont
  retirés du fichier.
- Couche indisponible : colonne absente, signalée dans les métadonnées. En mode
  suppression, le calcul s'arrête.

Calcul et reprise
-----------------

- Zones : adresse (cercle de 40 m), commune, département, région, France, zone
  tracée. Région et France : un fichier par département ; un département déjà
  complet est sauté.
- Chaque dalle finie est écrite dans data/processed/en_cours/, un dossier par
  zone. Un calcul interrompu reprend aux dalles manquantes si la version, la
  zone, le MNT de relief et les réglages du calcul n'ont pas changé.
- Une dalle en échec est retentée une fois en fin de calcul. Si elle échoue
  encore, le fichier est écrit sans elle et le signale dans ses métadonnées.
  Relancer la zone ne calcule qu'elle.
- Le dossier de reprise et le MNT de relief sont supprimés quand la zone est
  complète, ou avec le fichier depuis l'interface.
- Un calcul utilise un seul jeu de réglages, enregistré dans les métadonnées.


Limites
=======

- France métropolitaine seule (domaine du Lambert 93).
- Zone sans dalle LiDAR HD publiée : pas de résultat.
- Le MNT de relief ne couvre pas l'étranger : horizon lointain sous-estimé près
  des frontières.
- Météo moyenne 2005-2023 : pas de variation d'une année à l'autre.
- Taux de couverture et PR : valeurs moyennes, pas de calepinage par toit.
- Surface posable : pans de plus de 45°, rives et pourtour des obstacles exclus.
  Elle est plus petite que la surface de toiture.
- Protections : indication, pas décision.


Colonnes de sortie
==================

Une ligne par bâtiment.

| Colonne                  | Contenu                                       |
|--------------------------|-----------------------------------------------|
| cleabs                   | identifiant BD TOPO                           |
| nature, usage_1          | attributs BD TOPO                             |
| hauteur, nombre_d_etages | attributs BD TOPO                             |
| pose_plat                | pose sur le toit plat (vide sans toit plat)   |
| hauteur_p95_m            | hauteur du bâtiment, p95 du MNH               |
| nb_pixels                | nombre de pixels de toit                      |
| surf_m2                  | surface posable (plat + incliné)              |
| surf_m2_plat             | surface plate                                 |
| surf_m2_incl             | surface inclinée, toutes orientations         |
| surf_m2_or               | surface inclinée orientée (90 à 270°)         |
| surf_m2_seuil            | surface au-dessus du seuil d'irradiance       |
| surf_m2_mod              | surface de modules installables               |
| pente_moy_deg_incl       | pente moyenne des pans inclinés               |
| surf_m2_incl_N à _NO     | surface inclinée par orientation (8 secteurs) |
| ciel_moy                 | part du ciel vue par le toit (0 à 1)          |
| irr_an_kwh               | irradiation reçue par an                      |
| puissance_kwc            | puissance crête installable                   |
| prod_an_kwh              | production par an                             |
| prod_T1_kwh_orp à T4     | production par trimestre, plat + orienté      |
| prot_monument, ...       | bâtiment dans une zone protégée (vrai / faux) |

irr, puissance et prod existent aussi en _orp (plat + orienté) et _seuil
(au-dessus du seuil d'irradiance, 1 000 kWh/m²/an).

- surf_m2 n'est pas la surface de toiture : les pans de plus de 45° et le
  pourtour des obstacles en sont exclus. Un inventaire de pans, comme ceux des
  cadastres solaires, mesure la toiture et donne davantage.
- surf_m2_mod porte la puissance et la production, pas surf_m2.
- Colonnes prot : une par protection cochée, aucune si aucune ne l'est. Les
  cinq colonnes sont prot_monument, prot_abords, prot_spr, prot_site et
  prot_coeur_parc.

Convention de nommage
---------------------

    <grandeur>[_<qualificateur>]_<unité>[_<périmètre>]

    grandeur       surf, irr, prod, puissance, pente, hauteur, ciel, nb_pixels
    qualificateur  temporel (an, T1 à T4) ou statistique (moy, p95)
    unité          m2, kwh, kwc, deg, m ; absente pour un comptage ou un rapport
    périmètre      toujours en dernier ; absent = toute la toiture

    (aucun)   toute la toiture          surf_m2, irr_an_kwh, prod_an_kwh
    _plat     partie plate              surf_m2_plat
    _incl     incliné                   surf_m2_incl, pente_moy_deg_incl
    _incl_X   incliné, secteur X        surf_m2_incl_N ... surf_m2_incl_NO
    _or       incliné orienté           surf_m2_or
    _orp      orienté + plat            irr_an_kwh_orp, prod_T1_kwh_orp
    _seuil    au-dessus du seuil        surf_m2_seuil, prod_an_kwh_seuil
    _mod      couvert de modules        surf_m2_mod

Métadonnées
-----------

Chaque GeoPackage porte : version, réglages, poses et coefficients thermiques,
nombre de dalles sur cellule et sur sous-cellule météo, zone, nombre de
bâtiments à chaque étape, dalles (total, calculées, manquantes et cause), MNT
de relief, protections (bâtiments marqués par couche, couches indisponibles) et
date de création.
