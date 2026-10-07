import numpy as np
import pandas as pd
from numba import njit, prange

from src.geometrie.horizon import facteursCiel
from src.irradiance import pose_plat as PP
from src import config


@njit(cache=True, inline="always")
def _poids(angle, pente, nalpha, nbeta, pas_a, pas_b):
    """
    Indices et poids de l'interpolation bilineaire (orientation, pente) dans la table.
    --------
    @param[in] angle, pente : orientation et pente du plan (deg)
    @param[in] nalpha, nbeta, pas_a, pas_b : dimensions et pas de la grille d'angles

    @return i0, i1, j0, j1, w00, w10, w01, w11 : indices bas/haut et poids des 4 coins
    """
    fa = angle / pas_a
    i0 = int(np.floor(fa)) % nalpha
    i1 = (i0 + 1) % nalpha
    wa = fa - np.floor(fa)
    fb = pente / pas_b
    fb = 0.0 if fb < 0 else (nbeta - 1.0 if fb > nbeta - 1 else fb)
    j0 = int(np.floor(fb))
    j1 = j0 + 1 if j0 + 1 < nbeta else nbeta - 1
    wb = fb - j0
    return (i0, i1, j0, j1,
            (1-wa)*(1-wb), wa*(1-wb), (1-wa)*wb, wa*wb)


def partsPerez(f1, f2, SAZ, SEL):
    """
    Parts circumsolaire et de bande d'horizon du diffus du ciel (le reste est isotrope), par
    plan de la grille et par creneau.
    --------
    @param[in] f1, f2   : coefficients de Perez par (mois, heure), voir coefsPerez
    @param[in] SAZ, SEL : azimut et elevation du soleil par (mois, heure), deg

    @return PC, PH : (n_alphas, n_betas, 12, 24) float32 ; PH peut etre negatif
    """
    al  = np.radians(config.ALPHAS)[:, None, None, None]
    be  = np.radians(config.BETAS)[None, :, None, None]
    zen = np.radians(90.0 - SEL)[None, None, :, :]
    az  = np.radians(SAZ)[None, None, :, :]
    cosz = np.cos(zen)

    ci = cosz * np.cos(be) + np.sin(zen) * np.sin(be) * np.cos(az - al)
    circ = np.where(SEL[None, None, :, :] > 0.0,
                    f1[None, None, :, :] * np.clip(ci, 0.0, None)
                    / np.maximum(cosz, 0.087), 0.0)
    iso = (1.0 - f1[None, None, :, :]) * (1.0 + np.cos(be)) / 2.0
    hb  = f2[None, None, :, :] * np.sin(be)
    som = iso + circ + hb
    ok = som > 1e-9
    return (np.where(ok, circ / som, 0.0).astype(np.float32),
            np.where(ok, hb / som, 0.0).astype(np.float32))


def partSol(albedo):
    """
    Part du global horizontal reflechie par le sol sur chaque pente de la grille.
    --------
    @param[in] albedo : albedo du sol

    @return (n_betas,) float32 : albedo (1 - cos b) / 2
    """
    return (albedo * (1.0 - np.cos(np.radians(config.BETAS))) / 2.0).astype(np.float32)


def invV(u0, u1, profils):
    """
    Esperance de 1/(U0 + U1 V) par creneau, developpee a l'ordre 2 en V.
    --------
    @param[in] u0, u1  : coefficients de Faiman
    @param[in] profils : profils de la cellule (v_pond, v_var)

    @return (12, 24) float32
    """
    u0, u1 = np.float32(u0), np.float32(u1)
    d0 = u0 + u1 * profils["v_pond"]
    return (1.0 / d0 + u1 * u1 * profils["v_var"] / d0**3).astype(np.float32)


@njit(cache=True, inline="always")
def _plan(B, D, PC, PH, i0, i1, j0, j1, w00, w10, w01, w11, m, h, clair, ombre, st, fc, fh):
    """
    Direct et diffus d'un plan interpole dans les tables, masques par l'horizon, la
    rangee de devant et les facteurs de ciel.
    --------
    @param[in] B, D, PC, PH : tables (n_alphas, n_betas, 12, 24)
    @param[in] i0, i1, j0, j1 : indices du plan, voir _poids
    @param[in] w00, w10, w01, w11 : poids du plan
    @param[in] m, h         : creneau
    @param[in] clair        : soleil au-dessus de l'horizon
    @param[in] ombre        : fraction du module ombree par la rangee de devant
    @param[in] st           : reflechi par le sol sur le plan (W/m2)
    @param[in] fc, fh       : facteurs de ciel et de bande d'horizon du plan

    @return b, d : direct et diffus (W/m2)
    """
    b = 0.0
    if clair:
        b = (w00*B[i0,j0,m,h] + w10*B[i1,j0,m,h]
             + w01*B[i0,j1,m,h] + w11*B[i1,j1,m,h]) * (1.0 - ombre)
    d = (w00*D[i0,j0,m,h] + w10*D[i1,j0,m,h]
         + w01*D[i0,j1,m,h] + w11*D[i1,j1,m,h])
    pc = (w00*PC[i0,j0,m,h] + w10*PC[i1,j0,m,h]
          + w01*PC[i0,j1,m,h] + w11*PC[i1,j1,m,h])
    ph = (w00*PH[i0,j0,m,h] + w10*PH[i1,j0,m,h]
          + w01*PH[i0,j1,m,h] + w11*PH[i1,j1,m,h])
    c = d - st
    if c < 0.0:
        c = 0.0
    d = c * ((pc * (1.0 - ombre) if clair else 0.0) + (1.0 - pc - ph) * fc + ph * fh) + st * fc
    return b, d


@njit(cache=True, inline="always")
def _corrige(b, d, m, h, c, m_b, m_d, m_bb, m_bd, m_dd, f_lin, inv_v, gamma):
    """
    Irradiance d'un plan corrigee de la temperature de cellule.
    --------
    @param[in] b, d  : direct et diffus du plan (W/m2)
    @param[in] m, h  : creneau
    @param[in] c     : classe thermique
    @param[in] m_b, m_d, m_bb, m_bd, m_dd : moments horizontaux, voir energiePix
    @param[in] f_lin, inv_v, gamma : termes de temperature, voir energiePix

    @return irradiance effective (W/m2)
    """
    g = b + d
    if g <= 0.0:
        return 0.0
    rb = b / m_b[m, h] if m_b[m, h] > 0.0 else 0.0
    rd = d / m_d[m, h] if m_d[m, h] > 0.0 else 0.0
    g2 = (rb*rb*m_bb[m, h] + 2.0*rb*rd*m_bd[m, h] + rd*rd*m_dd[m, h])
    return g * (f_lin[m, h] + gamma * (g2 / g) * inv_v[c, m, h])


@njit(parallel=True, cache=True)
def energiePix(a, p, a_pose, p_pose, w2, typ, cls, B, D, PC, PH, fc_toit, fh_toit,
               fc_pose, fh_pose, f_sh, g_sol, ghi, horizon, dmh, SEL, actif,
               m_b, m_d, m_bb, m_bd, m_dd, f_lin, inv_v, NJ, pas_a, pas_b, gamma):
    """
    Energie mensuelle par pixel (kWh/m2) : recue par le toit, et productive vue par
    les modules, temperature de cellule comprise. Deux plans de pose au plus.
    --------
    @param[in] a, p           : orientation et pente du toit (deg), shape (N,)
    @param[in] a_pose, p_pose : orientation et pente des deux plans de pose (N, 2)
    @param[in] w2             : part des modules sur le second plan (N,)
    @param[in] typ            : type de rangee par plan (N, 2), index de f_sh
    @param[in] cls            : classe thermique du pixel (N,), index de inv_v
    @param[in] B, D           : tables directe et diffuse (n_alphas, n_betas, 12, 24), W/m2
    @param[in] PC, PH         : parts circumsolaire et de brillance d'horizon, forme de D
    @param[in] fc_toit, fh_toit : facteurs de ciel et de bande du toit (N,)
    @param[in] fc_pose, fh_pose : de meme pour les plans de pose (N, 2)
    @param[in] f_sh           : fraction ombree par type de rangee (4, 12, 24)
    @param[in] g_sol          : part reflechie par le sol, (n_betas,) : albedo (1-cos b)/2
    @param[in] ghi            : global horizontal moyen (12, 24), W/m2
    @param[in] horizon        : angle d'horizon par pixel et direction (N, n_dir), deg
    @param[in] dmh            : indice de direction d'horizon du soleil par (mois, heure)
    @param[in] SEL            : elevation du soleil par (mois, heure), deg
    @param[in] actif          : 2D bool (12, 24), creneaux pouvant contribuer
    @param[in] m_b, m_d       : direct et diffus horizontaux moyens (12, 24), W/m2
    @param[in] m_bb, m_bd, m_dd : moments horizontaux d'ordre 2 (12, 24), W2/m4
    @param[in] f_lin          : 1 + gamma (T_ponderee - 25), part de f_T sans irradiance
    @param[in] inv_v          : esperance de 1/(U0 + U1 V) par classe (n_cls, 12, 24)
    @param[in] NJ             : nombre de jours par mois, shape (12,)
    @param[in] pas_a, pas_b   : pas de la grille en orientation et pente (deg)
    @param[in] gamma          : coefficient de temperature du module (/degC)

    @return e_mois   : energie recue par le toit, shape (N, 12), kWh/m2
    @return eff_mois : energie vue par les modules, corrigee de la temperature, kWh/m2
    """
    N = a.shape[0]
    nalpha, nbeta = B.shape[0], B.shape[1]
    e_mois   = np.zeros((N, 12), np.float32)
    eff_mois = np.zeros((N, 12), np.float32)

    for n in prange(N):
        i0, i1, j0, j1, w00, w10, w01, w11 = _poids(a[n], p[n], nalpha, nbeta, pas_a, pas_b)
        gs_t = g_sol[j0] * (w00 + w10) + g_sol[j1] * (w01 + w11)
        meme = typ[n, 0] == 0 and a_pose[n, 0] == a[n] and p_pose[n, 0] == p[n]
        if meme:
            k0, k1, l0, l1, v00, v10, v01, v11 = i0, i1, j0, j1, w00, w10, w01, w11
            gs_0 = gs_t
        else:
            k0, k1, l0, l1, v00, v10, v01, v11 = _poids(a_pose[n, 0], p_pose[n, 0],
                                                        nalpha, nbeta, pas_a, pas_b)
            gs_0 = g_sol[l0] * (v00 + v10) + g_sol[l1] * (v01 + v11)
        deux = w2[n] > 0.0
        q0, q1, r0, r1, u00, u10, u01, u11 = k0, k1, l0, l1, v00, v10, v01, v11
        gs_1 = gs_0
        if deux:
            q0, q1, r0, r1, u00, u10, u01, u11 = _poids(a_pose[n, 1], p_pose[n, 1],
                                                        nalpha, nbeta, pas_a, pas_b)
            gs_1 = g_sol[r0] * (u00 + u10) + g_sol[r1] * (u01 + u11)
        c = cls[n]

        for m in range(12):
            recue = 0.0
            corrigee = 0.0
            for h in range(24):
                if not actif[m, h]:
                    continue
                clair = SEL[m, h] > 0.0 and SEL[m, h] > horizon[n, dmh[m, h]]

                bt, dt = _plan(B, D, PC, PH, i0, i1, j0, j1, w00, w10, w01, w11, m, h,
                               clair, 0.0, gs_t * ghi[m, h], fc_toit[n], fh_toit[n])
                recue += bt + dt

                if meme:
                    bp, dp = bt, dt
                else:
                    bp, dp = _plan(B, D, PC, PH, k0, k1, l0, l1, v00, v10, v01, v11, m, h,
                                   clair, f_sh[typ[n, 0], m, h], gs_0 * ghi[m, h],
                                   fc_pose[n, 0], fh_pose[n, 0])
                e0 = _corrige(bp, dp, m, h, c, m_b, m_d, m_bb, m_bd, m_dd, f_lin, inv_v, gamma)
                if deux:
                    bq, dq = _plan(B, D, PC, PH, q0, q1, r0, r1, u00, u10, u01, u11, m, h,
                                   clair, f_sh[typ[n, 1], m, h], gs_1 * ghi[m, h],
                                   fc_pose[n, 1], fh_pose[n, 1])
                    e1 = _corrige(bq, dq, m, h, c, m_b, m_d, m_bb, m_bd, m_dd, f_lin,
                                  inv_v, gamma)
                    corrigee += (1.0 - w2[n]) * e0 + w2[n] * e1
                else:
                    corrigee += e0

            e_mois[n, m]   = NJ[m] / 1000.0 * recue
            eff_mois[n, m] = NJ[m] / 1000.0 * corrigee
    return e_mois, eff_mois


def irrPixels(masque_bat, pente, aspect, incline, incline_or, plat, utile,
              res, B, D, SAZ, SEL, profils, horizon, lat, poses=None):
    """
    Energie par pixel de toit : recue par la toiture, et vue par les modules selon leur pose
    (temperature comprise) ; surface de modules.
    --------
    @param[in] masque_bat : 2D int, index gdf + 1 du batiment (0 hors toit)
    @param[in] pente, aspect : 2D float (deg)
    @param[in] incline, incline_or, plat : 2D bool, masques de selection
    @param[in] utile      : 2D bool, pixels equipables (voir eroderToit)
    @param[in] res        : taille du pixel (m)
    @param[in] B, D       : tables (n_alphas, n_betas, 12, 24) direct / diffus (W/m2)
    @param[in] SAZ, SEL   : position moyenne du soleil par (mois, heure) (deg)
    @param[in] profils    : dict des profils (12, 24) de la cellule (voir profilsCellule)
    @param[in] horizon    : horizon par pixel (N, n_dir), meme ordre que incline | plat
    @param[in] lat        : latitude du centre de la dalle (deg)
    @param[in] poses      : code de pose du toit plat par batiment (voir posesBatiments) ;
                            None = config.PLAT_POSE partout

    @return DataFrame, 1 ligne par pixel (id, energie, energie_eff, energie_eff_T1..T4, surf,
            surf_mod, pente, ciel, secteur, incline, incline_or, pose)
    """
    toit = incline | plat
    assert horizon.shape[0] == toit.sum(), "horizon et masque de toit desynchronises"

    a = aspect[toit].astype(np.float32)
    p = pente[toit].astype(np.float32)
    est_plat = plat[toit]
    N = a.shape[0]

    code = np.full(N, -1, np.int8)
    if poses is None:
        if config.PLAT_POSE not in PP.CODES:
            raise ValueError("pose mixte sans repartition par batiment (voir posesBatiments)")
        code[est_plat] = PP.CODES[config.PLAT_POSE]
    else:
        ids = masque_bat[toit][est_plat] - 1
        code[est_plat] = poses.reindex(ids, fill_value=PP.CODES[config.MIXTE_SINON]).to_numpy()

    geo = PP.geometrie(lat, SAZ, SEL)
    a_pose = np.stack([a, a], axis=1)
    p_pose = np.stack([p, p], axis=1)
    typ = np.full((N, 2), PP.R_AUCUNE, np.int8)
    w2 = np.zeros(N, np.float32)
    cls = np.zeros(N, np.int8)
    taux = np.full(N, float(np.clip(config.COUVERTURE_INCL, 0.0, 1.0)))
    emprise = float(np.clip(config.EMPRISE_PLAT, 0.0, 1.0))

    i_plat = np.flatnonzero(code == PP.A_PLAT)
    cls[i_plat] = 1 + PP.A_PLAT
    taux[i_plat] = emprise

    i_sud = np.flatnonzero(code == PP.SUD)
    a_pose[i_sud, 0] = config.SUD_AZIMUT
    p_pose[i_sud, 0] = config.SUD_PENTE
    typ[i_sud, 0] = PP.R_SUD
    cls[i_sud] = 1 + PP.SUD
    taux[i_sud] = emprise * geo["sud"]["densite"]

    i_eo = np.flatnonzero(code == PP.EST_OUEST)
    a_pose[i_eo, 0] = 90.0
    a_pose[i_eo, 1] = 270.0
    p_pose[i_eo] = config.EO_PENTE
    typ[i_eo, 0] = PP.R_EST
    typ[i_eo, 1] = PP.R_OUEST
    w2[i_eo] = 0.5
    cls[i_eo] = 1 + PP.EST_OUEST
    taux[i_eo] = emprise * geo["eo"]["densite"]

    pas_a = float(config.ALPHAS[1] - config.ALPHAS[0])
    pas_b = float(config.BETAS[1] - config.BETAS[0])
    ndir  = horizon.shape[1]
    dmh = (np.round(SAZ / (360 / ndir)).astype(np.int64) % ndir)

    g_sol = partSol(config.ALBEDO)
    ghi = (profils["m_b"] + profils["m_d"]).astype(np.float32)
    D32 = (D.astype(np.float32)
           + (g_sol - partSol(config.ALBEDO_TABLES))[None, :, None, None] * ghi)
    actif = (SEL > 0.0) | (D32.max(axis=(0, 1)) > 0.0)

    inv_v = np.stack([invV(config.U0_FAIMAN, config.U1_FAIMAN, profils)]
                     + [invV(*config.POSES[config.THERMIQUE_PLAT[nom]], profils)
                        for nom in config.POSES_PLAT])
    f_lin = (1.0 + config.GAMMA_MODULE * (profils["t_pond"] - 25.0)).astype(np.float32)

    hz32 = horizon.astype(np.float32)
    bande = np.float32(config.BANDE_HORIZON_DEG)
    fc_toit, fh_toit = facteursCiel(hz32, p, a, bande, np.zeros(1), np.ones(1))
    fc_pose = np.stack([fc_toit, fc_toit], axis=1)
    fh_pose = np.stack([fh_toit, fh_toit], axis=1)
    for i, s, g in ((i_sud, 0, geo["sud"]), (i_eo, 0, geo["eo"]), (i_eo, 1, geo["eo"])):
        if i.size:
            fc_pose[i, s], fh_pose[i, s] = facteursCiel(hz32[i], p_pose[i, s], a_pose[i, s],
                                                        bande, g["t"], g["w"])
    PC, PH = partsPerez(profils["f1_pond"], profils["f2_pond"], SAZ, SEL)

    e_mois, eff_mois = energiePix(
        a, p, a_pose, p_pose, w2, typ, cls, B.astype(np.float32), D32, PC, PH,
        fc_toit, fh_toit, fc_pose, fh_pose, geo["f_sh"], g_sol, ghi, hz32,
        dmh, SEL.astype(np.float32), actif,
        profils["m_b"].astype(np.float32),  profils["m_d"].astype(np.float32),
        profils["m_bb"].astype(np.float32), profils["m_bd"].astype(np.float32),
        profils["m_dd"].astype(np.float32), f_lin, inv_v,
        config.N_JOURS.astype(np.float32), pas_a, pas_b, np.float32(config.GAMMA_MODULE))

    surf = res**2 / np.cos(np.radians(p))
    surf_mod = np.where(utile[toit], surf * taux, 0.0)

    e_mois   = e_mois   * surf[:, None]
    eff_mois = eff_mois * surf_mod[:, None]

    df = pd.DataFrame({
        "id":          masque_bat[toit] - 1,
        "energie":     e_mois.sum(axis=1),
        "energie_eff": eff_mois.sum(axis=1),
        "surf":        surf,
        "surf_mod":    surf_mod,
        "pente":       p,
        "ciel":        fc_toit,
        "secteur":     np.round(a / 45).astype(int) % 8,
        "incline":     incline[toit],
        "incline_or":  incline_or[toit],
        "pose":        code,
    })
    for t, mois in enumerate(config.TRIM, start=1):
        df[f"energie_eff_T{t}"] = eff_mois[:, mois].sum(axis=1)
    return df
