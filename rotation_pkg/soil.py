"""
soil.py — Volet sol de Field Shift Sénégal (données ISRIC SoilGrids v2.0)

  - lit data/soilgrids.csv (médiane de 4 points agricoles autour de chaque ville, 4 profondeurs) ;
  - calcule la réserve utile en eau (Saxton & Rawls 2006) et la convertit en JOURS de croissance
    possibles après la fin des pluies -> utilisé par le moteur à la place des 15 jours uniformes ;
  - produit une lecture simple des propriétés de surface (0-30 cm).

ATTENTION : SoilGrids = prédiction statistique à 250 m, pas une analyse de laboratoire.
Les seuils de lecture sont des repères généraux, à confirmer par un agronome et par des analyses de terrain.
"""
from pathlib import Path
import numpy as np
import pandas as pd

THICK_MM = {"0-5cm": 50, "5-15cm": 100, "15-30cm": 150, "30-60cm": 300}
TOP = {"0-5cm": 5, "5-15cm": 10, "15-30cm": 15}        # poids pour la moyenne 0-30 cm
RACINES_MM = 1000        # profondeur racinaire supposée (mil, sorgho, arachide) : 1 m
FRACTION_FACILE = 0.5    # part de la réserve facilement utilisable (FAO-56, p = 0,5)


def saxton_rawls_awc(sand, clay, soc_gkg):
    """Eau utile volumique (θ33 - θ1500) d'après Saxton & Rawls (2006). Sable et argile en %, SOC en g/kg."""
    S, C = sand / 100, clay / 100
    OM = soc_gkg / 10 * 1.724
    t15 = -0.024 * S + 0.487 * C + 0.006 * OM + 0.005 * S * OM - 0.013 * C * OM + 0.068 * S * C + 0.031
    th15 = t15 + (0.14 * t15 - 0.02)
    t33 = -0.251 * S + 0.195 * C + 0.011 * OM + 0.006 * S * OM - 0.027 * C * OM + 0.452 * S * C + 0.299
    th33 = t33 + (1.283 * t33 ** 2 - 0.374 * t33 - 0.015)
    return th33 - th15


def texture_usda(sand, clay, silt):
    if clay >= 40:
        return "argileuse"
    if clay >= 27 and sand <= 45:
        return "limono-argileuse"
    if clay >= 20 and sand > 45:
        return "limono-argilo-sableuse"
    if sand >= 85:
        return "sableuse"
    if sand >= 70:
        return "sablo-limoneuse (loamy sand)"
    if sand >= 52 or (clay < 7 and silt < 50):
        return "limono-sableuse"
    return "limoneuse"


def load(data_dir, et0_oct):
    """et0_oct : dict site -> ET0 moyenne d'octobre (mm/j). Renvoie (tableau sol par site, dict réserve en jours)."""
    path = Path(data_dir) / "soilgrids.csv"
    if not path.exists():
        return None, {}
    w = pd.read_csv(path)
    w["awc"] = saxton_rawls_awc(w.sand, w.clay, w.soc) * (1 - w.cfvo / 100)
    w["eau_mm"] = w.awc * w.profondeur.map(THICK_MM)
    ru = w.groupby("site").eau_mm.sum() / 600 * RACINES_MM            # extrapolé de 0-60 cm à 1 m
    t = w[w.profondeur.isin(TOP)].copy()
    t["p"] = t.profondeur.map(TOP)
    cols = ["clay", "sand", "silt", "soc", "phh2o", "nitrogen", "cec", "bdod"]
    top = t.groupby("site").apply(lambda g: pd.Series({c: np.average(g[c], weights=g.p) for c in cols}),
                                  include_groups=False)
    top["texture"] = [texture_usda(r.sand, r.clay, r.silt) for r in top.itertuples()]
    top["reserve_utile_mm"] = ru
    top["et0_oct"] = pd.Series(et0_oct)
    top["reserve_jours"] = (FRACTION_FACILE * top.reserve_utile_mm / top.et0_oct).round().astype("Int64")
    return top, {s: int(v) for s, v in top.reserve_jours.dropna().items()}


def lecture(r):
    """Repères généraux (à valider) pour une lecture rapide des propriétés 0-30 cm."""
    out = []
    out.append(("Carbone organique", f"{r.soc:.1f} g/kg",
                "faible" if r.soc < 10 else ("moyen" if r.soc < 20 else "élevé"),
                "Peu de matière organique : sol fragile, rétention d'eau et fertilité limitées." if r.soc < 10 else
                "Niveau correct à préserver (restitution des résidus)."))
    out.append(("Azote total", f"{r.nitrogen:.2f} g/kg", "faible" if r.nitrogen < 1 else "moyen",
                "Une légumineuse (arachide, niébé) dans la rotation apporte de l'azote à la céréale suivante."
                if r.nitrogen < 1 else "Niveau correct."))
    out.append(("pH (eau)", f"{r.phh2o:.1f}", "acide" if r.phh2o < 5.5 else ("neutre" if r.phh2o <= 7.3 else "basique"),
                "Sol acide : surveiller l'arachide et le niébé ; le chaulage ou l'apport organique aide." if r.phh2o < 5.5
                else "Compatible avec les cultures proposées."))
    out.append(("Texture", r.texture, f"{r.sand:.0f} % sable / {r.clay:.0f} % argile", "Détermine la réserve en eau ci-dessous."))
    out.append(("Réserve en eau (1 m)", f"{r.reserve_utile_mm:.0f} mm", f"≈ {r.reserve_jours} jours",
                "Nombre de jours pendant lesquels la culture peut finir son cycle après la dernière pluie."))
    return pd.DataFrame(out, columns=["Indicateur", "Valeur", "Niveau", "Ce que ça implique"])
