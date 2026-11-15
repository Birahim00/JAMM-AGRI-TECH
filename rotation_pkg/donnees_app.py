"""
Préparation des données pour l'application Field Shift (JAMM AGRI-TECH).
Tout le calcul lourd est fait une seule fois ici ; l'application ne fait ensuite que filtrer et reclasser.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
import core, soil, rotation as rt

HERE = Path(__file__).parent
DATA = HERE / "data"

# emplacement illustratif des parcelles simulées (zone agricole à quelques km du centre-ville)
FERME = {"Thies": (14.735, -16.875), "Kaolack": (14.195, -15.995),
         "Ziguinchor": (12.525, -16.215), "Richard-Toll": (16.430, -15.655)}

# couleurs des cultures : légumineuses (fixent l'azote) en verts, céréales en ocres et bruns
COULEURS = {
    "Mil à chandelle": "#C8892B", "Sorgho": "#8C3B2E", "Maïs": "#E0B93A", "Riz": "#6FA8C7", "Fonio": "#D9A57B",
    "Arachide": "#2F7D32", "Niébé": "#66A84F", "Soja": "#9CC77E", "Voandzou": "#1F5E4E",
    "Sésame": "#9C7FC4", "Coton": "#8E9AA8", "Bissap": "#B0305A", "Pastèque": "#4F8FC0",
}


def nom_court(culture):
    return culture.split(" (")[0]


def charger():
    """Charge toutes les données et calcule les rotations, variétés et évaluations des 4 sites."""
    et0 = {s: pd.read_csv(DATA / "power_extra" / f"{s}_2005_2024.csv", parse_dates=["date"])
              .query("date.dt.month == 10").ET0_HARGREAVES_mm.mean() for s in core.SITES}
    SOIL, RES = soil.load(DATA, et0)
    core.RESERVE_SITE.update(RES)
    D = core.load_daily(DATA)
    S = core.detect_seasons(D)
    xlsx = DATA / "cultures_sahel_parametres_verifie.xlsx"
    C, mat = rt.load_base(xlsx)
    V = rt.varietes(C, rt.load_varietes_nommees(DATA / "besoins_cultures_varietes.csv"))
    Z = rt.load_zones(xlsx)
    f_cl = DATA / "issa" / "dataset_site_annee.csv"
    CL = pd.read_csv(f_cl)[["site", "annee", "classe_annee"]] if f_cl.exists() else None

    sites = {}
    for site in core.SITES:
        rfu = 0.5 * SOIL.loc[site, "reserve_utile_mm"]
        R, dec, succ, Vs, iso = rt.rotations_site(D, S, C, V, mat, SOIL, site, core.reserve(site), rfu, Z, top=None)
        autorisees = list(dec[dec.statut == "autorisée"].index)
        coords = json.load(open(DATA / f"{site}.json"))["geometry"]["coordinates"]
        pluie_an = D[D.site == site].groupby("annee").PRECTOTCORR.sum()
        Ss = S[S.site == site]
        mens = D[D.site == site].copy()
        mens["mois"] = mens.index.month
        pluie_mois = mens.groupby(["annee", "mois"]).PRECTOTCORR.sum().groupby("mois").mean()
        E = rt.evaluation_classes(S, Vs, C, succ, site, core.reserve(site), CL) if CL is not None else pd.DataFrame()
        sites[site] = {
            "R": R, "dec": dec, "succ": succ, "V": Vs, "iso": iso, "autorisees": autorisees, "E": E,
            "lat": coords[1], "lon": coords[0], "reserve_j": core.reserve(site),
            "pluie_med": float(pluie_an.median()), "debut_med": float(Ss.debut.median()),
            "duree_med": float(Ss.duree.median()), "ph": float(SOIL.loc[site, "phh2o"]),
            "texture": str(SOIL.loc[site, "texture"]), "sable": float(SOIL.loc[site, "sand"]),
            "argile": float(SOIL.loc[site, "clay"]), "pluie_mois": pluie_mois,
        }
    return {"D": D, "S": S, "C": C, "mat": mat, "V": V, "CL": CL, "sites": sites}


def proba_varietes(S, Vs, site, cid, onset, res_j):
    """Chance de boucler le cycle (calculée sur 2005-2024) pour chaque variété d'une culture, semée à la date onset."""
    ends = S[(S.site == site) & S.fin.notna()].fin.values
    rows = []
    for vid, v in Vs[Vs.id == cid].sort_values("cycle").iterrows():
        rows.append({"vid": vid, "variete": v.label, "cycle": int(v.cycle), "nommee": bool(v.nommee),
                     "p": float(np.mean(ends + res_j >= onset + v.cycle - 1))})
    return pd.DataFrame(rows)
