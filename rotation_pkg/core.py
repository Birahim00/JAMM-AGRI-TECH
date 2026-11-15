"""
core.py — Moteur Field Shift Sénégal (source unique de vérité pour l'application ET le backtest)

Contenu :
  - paramètres des cultures (HYPOTHÈSES DE TRAVAIL à valider par un agronome) ;
  - détection du début / de la fin de saison (règles validées : 100 % de concordance avec climat_annuel.csv) ;
  - évaluation climatique d'une culture pour une année donnée ;
  - recommandation adaptative au début des pluies ;
  - backtest 2005-2024 des stratégies A (fixe), B (adaptative), C (toujours cycle court).
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

SITES = ["Thies", "Kaolack", "Ziguinchor", "Richard-Toll"]
LABEL = {"Thies": "Thiès", "Kaolack": "Kaolack", "Ziguinchor": "Ziguinchor", "Richard-Toll": "Richard-Toll"}
YEARS = range(2005, 2025)

# ------------------------------------------------------------------ CULTURES (à valider)
CROPS = pd.DataFrame([
    # culture, famille, cycle (j), pluie min (mm), tolérance séquence sèche floraison (j), seuil chaleur floraison (°C)
    ("Mil tardif (sanio)",  "cereale",     120, 350, 12, 40),
    ("Sorgho",              "cereale",     105, 350, 12, 38),
    ("Mil hâtif (souna)",   "cereale",      85, 250, 12, 40),
    ("Arachide tardive",    "legumineuse", 115, 400, 10, 36),
    ("Arachide hâtive",     "legumineuse",  90, 300, 10, 36),
    ("Niébé",               "legumineuse",  65, 200, 12, 36),
], columns=["culture", "famille", "cycle", "pluie_min", "tol_sec", "t_crit"]).set_index("culture")

RESERVE = 15          # valeur par défaut (jours de croissance sur la réserve du sol après la fin des pluies)
# Réserve par site estimée à partir du SOL (SoilGrids, médiane de 4 points agricoles autour de chaque ville) :
# réserve utile sur 1 m (Saxton & Rawls 2006, corrigée des éléments grossiers) x 50 % facilement utilisable
# / ET0 moyenne d'octobre (Hargreaves, NASA POWER). Recalculée par soil.py si data/soilgrids.csv est présent.
RESERVE_SITE = {}
DRY = 1.0             # mm : jour sec si pluie < 1 mm
HOT_DAYS_MAX = 3      # nb de jours > seuil tolérés pendant la floraison
CONFIANCE = 0.80      # B choisit la variété la plus longue qui boucle son cycle dans >= 80 % des saisons passées


# ------------------------------------------------------------------ DONNÉES
def load_daily(data_dir):
    frames = []
    for s in SITES:
        d = json.load(open(Path(data_dir) / f"{s}.json"))
        df = pd.DataFrame(d["properties"]["parameter"])
        df.index = pd.to_datetime(df.index, format="%Y%m%d")
        df = df.replace(d["header"]["fill_value"], np.nan)
        df["site"] = s
        frames.append(df)
    D = pd.concat(frames)
    D["annee"], D["doy"] = D.index.year, D.index.dayofyear
    return D


def longest_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def onset(p, doy):
    """1er jour >= 1er mai, pluvieux, ouvrant 3 j cumulant >= 20 mm, sans séquence sèche >= 7 j dans les 30 j suivants."""
    for i in range(len(p)):
        if doy[i] >= 121 and p[i] >= DRY and p[i:i + 3].sum() >= 20 and longest_run(p[i + 3:i + 33] < DRY) < 7:
            return int(doy[i])
    return None


def end(p, doy, on):
    """1er jour pluvieux >= 1er sept. (et après le début) suivi d'au moins 20 jours secs."""
    for i in range(len(p)):
        if doy[i] >= max(244, on) and p[i] >= DRY and (p[i + 1:i + 21] < DRY).all():
            return int(doy[i])
    return None


def detect_seasons(D):
    rows = []
    for (s, y), g in D.groupby(["site", "annee"]):
        p, doy = g.PRECTOTCORR.values, g.doy.values
        on = onset(p, doy)
        en = end(p, doy, on) if on else None
        rows.append({"site": s, "annee": y, "debut": on, "fin": en,
                     "duree": (en - on + 1) if on and en else None,
                     "pluie_saison": g[(g.doy >= on) & (g.doy <= en)].PRECTOTCORR.sum() if on and en else None})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ ÉVALUATION
def reserve(site):
    return RESERVE_SITE.get(site, RESERVE)


def evaluate(g, on, en, crop, res=None):
    """g : données quotidiennes d'un site-année indexées par jour de l'année. Renvoie (réussite, cause)."""
    res = RESERVE if res is None else res
    if on is None or pd.isna(on):
        return False, "saison non installée"
    c = CROPS.loc[crop]
    on, en = int(on), int(en)
    mat = on + c.cycle - 1
    if mat > en + res:
        return False, "saison trop courte"
    if g.loc[on:min(mat, en), "PRECTOTCORR"].sum() < c.pluie_min:
        return False, "pluie insuffisante"
    flo = g.loc[on + int(0.50 * c.cycle): on + int(0.75 * c.cycle)]
    if longest_run(flo.PRECTOTCORR.values < DRY) >= c.tol_sec:
        return False, "sécheresse à la floraison"
    if (flo.T2M_MAX > c.t_crit).sum() >= HOT_DAYS_MAX:
        return False, "chaleur à la floraison"
    return True, ""


def options(fam):
    return CROPS[CROPS.famille == fam].sort_values("cycle", ascending=False)


def family_of_year(year):
    return "cereale" if year % 2 == 0 else "legumineuse"


def prob_fit(S, site, on, crop, exclude_year=None):
    """Part des saisons passées (hors exclude_year) dont la fin + réserve laisse le temps de boucler le cycle."""
    ends = S[(S.site == site) & S.fin.notna() & (S.annee != exclude_year)].fin.values
    if len(ends) == 0:
        return np.nan
    mat = on + CROPS.loc[crop, "cycle"] - 1
    return float(np.mean(ends + reserve(site) >= mat))


def other_risks(D, S, site, crop, exclude_year=None):
    """Fréquence historique des échecs NON liés à la durée (pluie, sécheresse ou chaleur à la floraison),
    en semant chaque année à son début de saison réel."""
    fails, n = {}, 0
    for _, r in S[(S.site == site) & S.debut.notna() & (S.annee != exclude_year)].iterrows():
        g = D[(D.site == site) & (D.annee == r.annee)].set_index("doy")
        ok, why = evaluate(g, r.debut, r.fin, crop, reserve(site))
        n += 1
        if not ok and why != "saison trop courte":
            fails[why] = fails.get(why, 0) + 1
    return {k: v / n for k, v in fails.items()}, n


def recommend(D, S, site, on, fam, exclude_year=None):
    """Tableau des variétés de la famille avec probabilité de boucler le cycle ; recommandée = la plus longue >= CONFIANCE."""
    rows, chosen = [], None
    for crop, c in options(fam).iterrows():
        p = prob_fit(S, site, on, crop, exclude_year)
        risks, _ = other_risks(D, S, site, crop, exclude_year)
        rows.append({"culture": crop, "cycle_j": int(c.cycle), "maturite_doy": on + int(c.cycle) - 1,
                     "p_duree": p, "risque_autre": sum(risks.values()),
                     "detail_risque": ", ".join(f"{k} {v:.0%}" for k, v in risks.items()) or "—"})
        if chosen is None and p >= CONFIANCE:
            chosen = crop
    if chosen is None:
        chosen = options(fam).index[-1]
    T = pd.DataFrame(rows)
    T["recommandee"] = T.culture == chosen
    return T, chosen


# ------------------------------------------------------------------ BACKTEST
def choose_A(S, site, year, fam):
    """Plan classique : variété la plus longue tenant dans la saison MÉDIANE des autres années."""
    o = S[(S.site == site) & S.duree.notna() & (S.annee != year)]
    med = o.duree.median()
    for crop, c in options(fam).iterrows():
        if c.cycle <= med + reserve(site):
            return crop
    return options(fam).index[-1]


def choose_B(S, site, year, fam):
    on = S[(S.site == site) & (S.annee == year)].debut.iloc[0]
    if on is None or pd.isna(on):
        return None
    for crop, _ in options(fam).iterrows():
        if prob_fit(S, site, int(on), crop, exclude_year=year) >= CONFIANCE:
            return crop
    return options(fam).index[-1]


def choose_C(S, site, year, fam):
    return options(fam).index[-1]


def run_backtest(D, S):
    rows = []
    for s in SITES:
        for y in YEARS:
            fam = family_of_year(y)
            r = S[(S.site == s) & (S.annee == y)].iloc[0]
            g = D[(D.site == s) & (D.annee == y)].set_index("doy")
            for strat, fn in [("A_fixe", choose_A), ("B_adaptatif", choose_B), ("C_court", choose_C)]:
                crop = fn(S, s, y, fam)
                if crop is None:
                    ok, why, cyc = False, "saison non installée", np.nan
                else:
                    ok, why = evaluate(g, r.debut, r.fin, crop, reserve(s))
                    cyc = CROPS.loc[crop, "cycle"]
                rows.append({"site": s, "annee": y, "famille": fam, "debut": r.debut, "fin": r.fin,
                             "duree_saison": r.duree, "strategie": strat, "culture": crop,
                             "cycle": cyc, "reussite": ok, "cause": why})
    return pd.DataFrame(rows)


def doy_to_str(d, year=2021):
    if d is None or pd.isna(d):
        return "—"
    mois = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    t = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=int(d) - 1)
    return f"{t.day} {mois[t.month - 1]}"
