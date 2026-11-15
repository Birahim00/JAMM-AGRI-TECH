"""
rotation.py — Moteur de rotation sur 3 ans (JAMM AGRI-TECH, Field Shift Sénégal)

Lit la base agronomique de l'équipe (data/cultures_sahel_parametres_verifie.xlsx) et applique ses règles :
  R03  pluie annuelle de l'année sèche (quantile 20 %) < pluie minimale viable -> culture exclue du site
  R04  pluie annuelle moyenne > pluie maximale tolérée                       -> alerte
  R09  pH du sol hors de la plage tolérée                                    -> culture exclue du site
  R10  pH hors de la plage optimale                                          -> information (amendement)
  R07  matrice de rotation = 0 entre deux cultures successives               -> rotation exclue
  R08  retour de la même culture plus tôt que le délai minimal               -> rotation exclue
  R12  séquence sèche à la floraison                                         -> échec de l'année
  R13  >= 3 jours au-dessus de la T° critique à la floraison                 -> échec de l'année
  R06  date de semis hors de la période recommandée (calendrier)             -> information

Déroulé :
  1. chaque culture annuelle pluviale donne deux « variétés » : hâtive (cycle min) et tardive (cycle max) ;
  2. pour chaque site et chaque année 2005-2024, on évalue chaque variété semée au début réel des pluies ;
  3. chaque année, la variété est choisie de façon adaptative (la plus longue qui boucle son cycle dans >= 80 % des
     AUTRES saisons, compte tenu du début observé et de la réserve en eau du sol) ;
  4. toutes les rotations de 3 cultures compatibles sont rejouées sur les fenêtres de 3 années consécutives
     de l'historique, puis notées.

Hypothèses propres au moteur (à calibrer, affichées dans l'application) : HYPOTHESES ci-dessous.
"""
from pathlib import Path
import itertools, re
import numpy as np
import pandas as pd
import openpyxl
import core

HYPOTHESES = {
    # cultures non concernées par une rotation pluviale annuelle (irrigation ou cycle pluriannuel)
    "cultures_exclues": {"C13": "manioc : cycle de 8 à 18 mois", "C14": "patate douce : irrigation d'appoint",
                         "C16": "oignon : contre-saison irriguée"},
    # tolérance à une séquence sèche pendant la floraison (jours), déduite du niveau qualitatif de la base
    "tolerance_secheresse_j": {"très élevée": 14, "élevée": 12, "moyenne": 10, "faible à moyenne": 9, "faible": 8},
    "r12_cultures_sensibles_j": 10,     # R12 : séquence >= 10 j à la phase critique pour les cultures listées
    "jours_chauds_max": 3,              # R13
    "part_besoin_eau": 0.8,             # pluie de la période + réserve du sol >= 80 % du besoin en eau du cycle
    "confiance": 0.80,                  # choix adaptatif de la variété
    "quantile_annee_seche": 0.20,       # R03
    "poids": {"reussite": 0.30, "pire_cas": 0.20, "zone": 0.15, "azote": 0.15, "potentiel": 0.10, "compatibilite": 0.05,
              "documentation": 0.05},   # documentation : part des cultures avec variétés réelles sourcées (v3)
    # zone agroclimatique de la base (onglet Zones_Agroclimatiques) retenue pour chaque site, en agriculture pluviale
    "zone_site": {"Thies": "Sahélo-soudanienne", "Kaolack": "Sahélo-soudanienne",
                  "Ziguinchor": "Sub-guinéenne", "Richard-Toll": "Sahélienne"},
}
BILAN_N = [("fixatrice", 1.0), ("fort exportateur", -1.0), ("exportateur modéré", -0.5), ("faible exportateur", -0.25)]
MOIS = ["Jan", "Fév", "Mar", "Avr", "Mai", "Juin", "Juil", "Août", "Sep", "Oct", "Nov", "Déc"]


# ------------------------------------------------------------------ LECTURE DE LA BASE
def _rows(ws):
    rows = [r for r in ws.iter_rows(values_only=True)]
    head = [str(h).strip() if h else "" for h in rows[0]]
    out = []
    for r in rows[1:]:
        if r and r[0] and re.fullmatch(r"C\d{2}", str(r[0]).strip()):
            out.append(dict(zip(head, r)))
    return out


def _num(v):
    if v is None or (isinstance(v, str) and v.strip() in ("", "—", "-")):
        return np.nan
    if isinstance(v, (int, float)):
        return float(v)
    nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", str(v).replace(" ", ""))]
    return float(np.mean(nums)) if nums else np.nan


def load_base(xlsx):
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    seuils = {r["ID"]: r for r in _rows(wb["Seuils_Numeriques"])}
    gen = {r["ID"]: r for r in _rows(wb["Cultures_Generalites"])}
    rot = {r["ID"]: r for r in _rows(wb["Rotation_Regles"])}
    cal = {r["ID"]: r for r in _rows(wb["Calendrier_Cultural"])}
    # matrice précédent -> suivant
    ws = wb["Matrice_Rotation"]
    rows = list(ws.iter_rows(values_only=True))
    cols = [re.match(r"(C\d{2})", str(c)).group(1) if c and re.match(r"C\d{2}", str(c)) else None for c in rows[0]]
    mat = {}
    for r in rows[1:]:
        m = re.match(r"(C\d{2})", str(r[0] or ""))
        if not m:
            continue
        for c, v in zip(cols[1:], r[1:]):
            if c and v is not None:
                mat[(m.group(1), c)] = int(v)

    cultures = []
    for cid, s in seuils.items():
        if cid in HYPOTHESES["cultures_exclues"]:
            continue
        g, ro, ca = gen.get(cid, {}), rot.get(cid, {}), cal.get(cid, {})
        tol_txt = str(g.get("Tolérance à la sécheresse", "")).strip().lower()
        tol = next((v for k, v in sorted(HYPOTHESES["tolerance_secheresse_j"].items(), key=lambda kv: -len(kv[0]))
                    if tol_txt.startswith(k)), 10)
        bil_txt = str(ro.get("Bilan azote du sol", "")).lower()
        bilan = next((v for k, v in BILAN_N if k in bil_txt), 0.0)
        semis = [i + 1 for i, m in enumerate(MOIS) if str(ca.get(m, "") or "").strip().upper() == "S"]
        cultures.append({
            "id": cid, "culture": str(s["Culture"]).strip(),
            "famille": str(g.get("Famille botanique", "")).strip(), "type": str(g.get("Type", "")).strip(),
            "cycle_min": _num(s["Cycle min (j)"]), "cycle_max": _num(s["Cycle max (j)"]),
            "besoin_min": _num(s["Besoin en eau du cycle min (mm)"]), "besoin_max": _num(s["Besoin en eau du cycle max (mm)"]),
            "pluie_viable": _num(s["Pluie annuelle min viable (mm)"]), "pluie_max": _num(s["Pluie max tolérée (mm)"]),
            "t_crit": _num(s["T° air critique max (°C)"]),
            "ph_min": _num(s["pH min toléré"]), "ph_opt_min": _num(s["pH optimal min"]),
            "ph_opt_max": _num(s["pH optimal max"]), "ph_max": _num(s["pH max toléré"]),
            "retour_min": _num(s["Retour min sur même parcelle (ans)"]),
            "fixation_n": _num(s["Fixation N (kg N/ha)"]), "bilan_n": bilan, "tol_sec": tol, "tol_txt": tol_txt,
            "phase_critique": str(g.get("Phase critique (eau)", "")).strip(), "mois_semis": semis,
            "rendement_min": _num(s["Rendement paysan min (kg/ha)"]), "rendement_max": _num(s["Rendement paysan max (kg/ha)"]),
        })
    C = pd.DataFrame(cultures).set_index("id")
    # R12 : cultures sensibles listées dans la règle -> tolérance plafonnée
    r12 = [r for r in _rows_regles(wb) if r.get("ID règle") == "R12"]
    if r12:
        noms = str(r12[0].get("Culture(s)", "")).lower()
        for cid, r in C.iterrows():
            if r.culture.split(" (")[0].split()[0].lower() in noms:
                C.loc[cid, "tol_sec"] = min(C.loc[cid, "tol_sec"], HYPOTHESES["r12_cultures_sensibles_j"])
    return C, mat


def load_zones(xlsx):
    """Cultures bien adaptées / à risque par zone (onglet Zones_Agroclimatiques)."""
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    rows = list(wb["Zones_Agroclimatiques"].iter_rows(values_only=True))
    head = [str(h).strip() if h else "" for h in rows[0]]
    out = {}
    for r in rows[1:]:
        if r and r[0]:
            d = dict(zip(head, r))
            out[str(r[0]).strip()] = {"adaptees": str(d.get("Cultures bien adaptées", "")).lower(),
                                      "risque": str(d.get("Cultures à risque", "")).lower()}
    return out


def _mot_cle(culture):
    return culture.split(" (")[0].split()[0].lower()      # « Mil à chandelle » -> « mil », « Riz (pluvial…) » -> « riz »


def adaptation_zone(C, zones, site):
    """+1 si la culture est citée comme bien adaptée à la zone du site, -1 si à risque, 0 sinon."""
    z = zones.get(HYPOTHESES["zone_site"].get(site, ""), {"adaptees": "", "risque": ""})
    out = {}
    for cid, c in C.iterrows():
        k = _mot_cle(c.culture)
        out[cid] = -1 if k in z["risque"] else (1 if k in z["adaptees"] else 0)
    return out


def _rows_regles(wb):
    rows = list(wb["Regles_Exemples"].iter_rows(values_only=True))
    head = [str(h).strip() if h else "" for h in rows[0]]
    return [dict(zip(head, r)) for r in rows[1:] if r and r[0] and str(r[0]).startswith("R")]


NOMS_CSV = {"arachide": "arachide", "niebe": "niébé", "niébé": "niébé", "mil": "mil", "sorgho": "sorgho",
            "mais": "maïs", "maïs": "maïs", "riz": "riz", "fonio": "fonio", "sesame": "sésame", "sésame": "sésame"}
TOLERANCE_ISOHYETE = 0.10      # tolérance de 10 % sur les bornes d'isohyète (même convention que l'analyse des variétés)


def load_varietes_nommees(csv_path):
    """Variétés réelles (besoins_cultures_varietes.csv) : culture, variété, cycle, isohyètes, source."""
    if csv_path is None or not Path(csv_path).exists():
        return None
    v = pd.read_csv(csv_path)
    v["cle"] = v.culture.str.strip().str.lower().map(lambda x: NOMS_CSV.get(x, x))
    return v


def varietes(C, nommees=None):
    """Variétés utilisées par le moteur.
    - Cultures présentes dans le tableau des variétés réelles : une ligne par variété nommée (cycle = cycle maximal,
      par prudence ; besoin en eau interpolé entre les besoins min et max de la culture dans la base de Cathy).
    - Autres cultures : deux variétés génériques, hâtive (cycle min) et tardive (cycle max) de la base."""
    out = []
    for cid, c in C.iterrows():
        cle = _mot_cle(c.culture)
        nv = nommees[nommees.cle == cle] if nommees is not None else pd.DataFrame()
        if len(nv):
            for k, r in nv.reset_index(drop=True).iterrows():
                cyc = int(r.cycle_max_j)
                if not np.isnan(c.cycle_min) and c.cycle_max > c.cycle_min:
                    f = min(1, max(0, (cyc - c.cycle_min) / (c.cycle_max - c.cycle_min)))
                    bes = c.besoin_min + f * (c.besoin_max - c.besoin_min)
                else:
                    bes = c.besoin_min
                out.append({"vid": f"{cid}-v{k:02d}", "id": cid, "culture": c.culture, "variete": str(r.variete),
                            "label": f"{c.culture.split(' (')[0]} {r.variete} ({cyc} j)", "cycle": cyc, "besoin": bes,
                            "tol_sec": c.tol_sec, "t_crit": c.t_crit, "iso_min": r.isohyete_min_mm, "iso_max": r.isohyete_max_mm,
                            "nommee": True, "portee": r.get("portee", ""), "source": r.get("source", "")})
            continue
        for nom, cyc, bes in [("hâtive", c.cycle_min, c.besoin_min), ("tardive", c.cycle_max, c.besoin_max)]:
            if np.isnan(cyc):
                continue
            out.append({"vid": f"{cid}-{nom[0]}", "id": cid, "culture": c.culture, "variete": f"générique {nom}",
                        "label": f"{c.culture.split(' (')[0]} ({int(cyc)} j)", "cycle": int(cyc), "besoin": bes,
                        "tol_sec": c.tol_sec, "t_crit": c.t_crit, "iso_min": np.nan, "iso_max": np.nan,
                        "nommee": False, "portee": "", "source": "base des cultures (Cathy)"})
            if c.cycle_min == c.cycle_max:
                break
    return pd.DataFrame(out).set_index("vid")


def varietes_site(V, D, site):
    """Filtre isohyète : pluie annuelle médiane du site dans la plage de la variété (tolérance 10 %)."""
    pluie_med = D[D.site == site].groupby("annee").PRECTOTCORR.sum().median()
    garder, rows = [], []
    for vid, v in V.iterrows():
        ok, motif = True, ""
        if not np.isnan(v.iso_min) and pluie_med < v.iso_min * (1 - TOLERANCE_ISOHYETE):
            ok, motif = False, f"pluie médiane {pluie_med:.0f} mm < isohyète min {v.iso_min:.0f} mm"
        if not np.isnan(v.iso_max) and pluie_med > v.iso_max * (1 + TOLERANCE_ISOHYETE):
            ok, motif = False, f"pluie médiane {pluie_med:.0f} mm > isohyète max {v.iso_max:.0f} mm"
        rows.append({"vid": vid, "label": v.label, "compatible_zone": ok, "motif": motif or "-"})
        if ok:
            garder.append(vid)
    return V.loc[garder], pd.DataFrame(rows).set_index("vid")


# ------------------------------------------------------------------ FILTRES PAR SITE
def filtres_site(C, D, soil_top, site, zones=None):
    """Renvoie (cultures autorisées, tableau des décisions avec la règle appliquée)."""
    pluie = D[D.site == site].groupby("annee").PRECTOTCORR.sum()
    q = pluie.quantile(HYPOTHESES["quantile_annee_seche"])
    ph = soil_top.loc[site, "phh2o"] if soil_top is not None and site in soil_top.index else np.nan
    rows = []
    for cid, c in C.iterrows():
        statut, regles = "autorisée", []
        if not np.isnan(c.pluie_viable) and q < c.pluie_viable:
            statut = "exclue"; regles.append(f"R03 : année sèche {q:.0f} mm < {c.pluie_viable:.0f} mm viables")
        if not np.isnan(c.pluie_max) and pluie.mean() > c.pluie_max:
            regles.append(f"R04 (alerte) : pluie moyenne {pluie.mean():.0f} mm > {c.pluie_max:.0f} mm tolérés")
        if not np.isnan(ph) and not np.isnan(c.ph_min) and (ph < c.ph_min or ph > c.ph_max):
            statut = "exclue"; regles.append(f"R09 : pH {ph:.1f} hors de [{c.ph_min}, {c.ph_max}]")
        elif not np.isnan(ph) and not np.isnan(c.ph_opt_min) and (ph < c.ph_opt_min or ph > c.ph_opt_max):
            regles.append(f"R10 (info) : pH {ph:.1f} hors optimum [{c.ph_opt_min}, {c.ph_opt_max}], amendement conseillé")
        if zones is not None:
            a = adaptation_zone(C, zones, site)[cid]
            if a < 0:
                regles.append(f"Zone {HYPOTHESES['zone_site'][site]} : culture à risque (pénalisée)")
        rows.append({"id": cid, "culture": c.culture, "statut": statut, "regles": " ; ".join(regles) or "aucune"})
    T = pd.DataFrame(rows).set_index("id")
    return list(T[T.statut == "autorisée"].index), T


# ------------------------------------------------------------------ ÉVALUATION ANNUELLE
def eval_variete(g, on, en, v, res_j, rfu_mm):
    """Réussite climatique d'une variété semée au début des pluies (on) d'une année (g indexé par jour de l'année)."""
    if on is None or pd.isna(on):
        return False, "saison non installée"
    on, en = int(on), int(en)
    mat = on + v.cycle - 1
    if mat > en + res_j:
        return False, "saison trop courte"
    pluie = g.loc[on:min(mat, en), "PRECTOTCORR"].sum()
    if not np.isnan(v.besoin) and pluie + rfu_mm < HYPOTHESES["part_besoin_eau"] * v.besoin:
        return False, "eau insuffisante"
    flo = g.loc[on + int(0.50 * v.cycle): on + int(0.75 * v.cycle)]
    if core.longest_run(flo.PRECTOTCORR.values < core.DRY) >= v.tol_sec:
        return False, "sécheresse à la floraison (R12)"
    if not np.isnan(v.t_crit) and (flo.T2M_MAX > v.t_crit).sum() >= HYPOTHESES["jours_chauds_max"]:
        return False, "chaleur à la floraison (R13)"
    return True, ""


def table_succes(D, S, V, site, res_j, rfu_mm):
    """Réussite (True/False) et cause pour chaque variété x année du site."""
    rows = []
    Ss = S[S.site == site].set_index("annee")
    for y in Ss.index:
        g = D[(D.site == site) & (D.annee == y)].set_index("doy")
        on, en = Ss.loc[y, "debut"], Ss.loc[y, "fin"]
        for vid, v in V.iterrows():
            ok, why = eval_variete(g, on, en, v, res_j, rfu_mm)
            rows.append({"annee": y, "vid": vid, "ok": ok, "cause": why})
    return pd.DataFrame(rows)


def choix_adaptatif(S, V, site, cid, annee, res_j, onset=None):
    """Variété de la culture cid choisie au début des pluies : la plus longue avec P(boucler) >= confiance."""
    Ss = S[S.site == site]
    on = Ss[Ss.annee == annee].debut.iloc[0] if onset is None else onset
    cands = V[V.id == cid].sort_values("cycle", ascending=False)
    if on is None or pd.isna(on):
        return cands.index[-1], np.nan
    ends = Ss[(Ss.annee != annee) & Ss.fin.notna()].fin.values
    for vid, v in cands.iterrows():
        p = float(np.mean(ends + res_j >= on + v.cycle - 1))
        if p >= HYPOTHESES["confiance"]:
            return vid, p
    vid = cands.index[-1]
    return vid, float(np.mean(ends + res_j >= on + cands.loc[vid, "cycle"] - 1))


# ------------------------------------------------------------------ ROTATIONS
def _r08_ok(seq, C):
    """R08 : dans une rotation cyclique de 3 ans, l'écart entre deux retours d'une même culture >= délai minimal."""
    for c in set(seq):
        pos = [i for i, x in enumerate(seq) if x == c]
        if len(pos) == 1:
            ecart = 3
        else:
            ecarts = [(pos[(k + 1) % len(pos)] - pos[k]) % 3 or 3 for k in range(len(pos))]
            ecart = min(ecarts)
        rmin = C.loc[c, "retour_min"]
        if not np.isnan(rmin) and ecart < rmin:
            return False
    return True


def rotations_site(D, S, C, V, mat, soil_top, site, res_j, rfu_mm, zones=None, top=5, avec_revision=True):
    """Classe les rotations de 3 ans du site. avec_revision=True : chaque année, si la culture prévue est trop risquée
    au vu du début des pluies, elle est remplacée par une culture de même famille (système complet, comme sur le terrain)."""
    autorisees, decisions = filtres_site(C, D, soil_top, site, zones)
    V, iso = varietes_site(V, D, site)
    sans_variete = [c for c in autorisees if c not in set(V.id)]
    for c in sans_variete:                                   # toutes ses variétés hors de la zone de pluie
        decisions.loc[c, "statut"] = "exclue"
        decisions.loc[c, "regles"] = (decisions.loc[c, "regles"].replace("aucune", "").strip(" ;")
                                      + " ; aucune variété compatible avec la pluie du site (isohyètes)").strip(" ;")
    autorisees = [c for c in autorisees if c not in sans_variete]
    cyc_max = V.groupby("id").cycle.max().to_dict()
    doc = V.groupby("id").nommee.max().astype(float).to_dict()   # 1 si la culture a des variétés réelles sourcées
    adapt = adaptation_zone(C, zones, site) if zones is not None else {c: 0 for c in C.index}
    succ = table_succes(D, S, V[V.id.isin(autorisees)], site, res_j, rfu_mm)
    ok = succ.set_index(["annee", "vid"]).ok
    annees = sorted(S[S.site == site].annee.unique())
    choix_p = {(cid, y): choix_adaptatif(S, V, site, cid, y, res_j) for cid in autorisees for y in annees}
    conf = HYPOTHESES["confiance"]
    final = {}                                                     # (culture prévue, précédent, année) -> variété semée

    def variete_semee(cid, prev, y):
        k = (cid, prev, y)
        if k not in final:
            vid, p = choix_p[(cid, y)]
            if avec_revision and not np.isnan(p) and p < conf:
                alts = [(choix_p[(c2, y)][1], choix_p[(c2, y)][0]) for c2 in autorisees
                        if c2 != cid and C.loc[c2, "famille"] == C.loc[cid, "famille"] and mat.get((prev, c2), 1) != 0]
                alts = [a for a in alts if not np.isnan(a[0])]
                if alts and max(alts)[0] > p:
                    vid = max(alts)[1]
            final[k] = vid
        return final[k]
    fenetres = [annees[i:i + 3] for i in range(len(annees) - 2)]
    rows = []
    for seq in itertools.product(autorisees, repeat=3):
        trans = [(seq[0], seq[1]), (seq[1], seq[2]), (seq[2], seq[0])]          # rotation cyclique
        compat = [mat.get(t, 1) for t in trans]
        if 0 in compat or not _r08_ok(seq, C):                                   # R07, R08
            continue
        scores, pot = [], []
        for w in fenetres:
            prevs = [seq[(i - 1) % 3] for i in range(3)]
            v_ = [variete_semee(c, pv, y) for c, pv, y in zip(seq, prevs, w)]
            scores.append(np.mean([ok.get((y, v), False) for v, y in zip(v_, w)]))
            pot.append(np.mean([V.loc[v, "cycle"] / cyc_max[V.loc[v, "id"]] for v in v_]))
        scores = np.array(scores)
        k = max(1, int(round(0.2 * len(scores))))
        rows.append({"rotation": seq, "reussite": scores.mean(), "pire_cas": np.sort(scores)[:k].mean(),
                     "potentiel": float(np.mean(pot)), "compatibilite": np.mean(compat) / 2,
                     "azote": np.mean([C.loc[c, "bilan_n"] for c in seq]),
                     "zone": np.mean([adapt[c] for c in seq]),
                     "documentation": np.mean([doc.get(c, 0.0) for c in seq])})
    R = pd.DataFrame(rows)
    if R.empty:
        return R, decisions, succ, V, iso
    R["rotation_txt"] = R.rotation.map(lambda s: " → ".join(C.loc[c, "culture"].split(" (")[0] for c in s))
    if top is None:                                          # toutes les rotations, critères bruts (pour l'application)
        return R, decisions, succ, V, iso
    return classer(R).head(top).reset_index(drop=True), decisions, succ, V, iso


# profils de priorité de l'agriculteur (poids du score)
PROFILS = {
    "Équilibré": None,                                       # poids par défaut (HYPOTHESES["poids"])
    "Sécurité": {"reussite": .40, "pire_cas": .35, "zone": .10, "azote": .05, "potentiel": .05, "compatibilite": .05,
                 "documentation": 0},
    "Fertilité du sol": {"reussite": .20, "pire_cas": .10, "zone": .10, "azote": .45, "potentiel": .05,
                         "compatibilite": .05, "documentation": .05},
    "Production": {"reussite": .20, "pire_cas": .15, "zone": .10, "azote": .05, "potentiel": .40, "compatibilite": .05,
                   "documentation": .05},
}


def classer(R, poids=None, voulues=(), refusees=(), distinctes=False):
    """Note et classe les rotations selon les priorités de l'agriculteur.
    poids : dictionnaire de poids (None = poids par défaut) ; voulues : la rotation doit contenir au moins une
    de ces cultures ; refusees : la rotation ne doit contenir aucune de ces cultures."""
    w = dict(poids or HYPOTHESES["poids"])
    tot = sum(w.values())
    w = {k: v / tot for k, v in w.items()}
    R = R.copy()
    if voulues:
        R = R[R.rotation.map(lambda s: any(c in s for c in voulues))]
    if refusees:
        R = R[R.rotation.map(lambda s: not any(c in s for c in refusees))]
    if R.empty:
        return R
    R["score"] = (w.get("reussite", 0) * R.reussite + w.get("pire_cas", 0) * R.pire_cas
                  + w.get("potentiel", 0) * R.potentiel + w.get("compatibilite", 0) * R.compatibilite
                  + w.get("azote", 0) * (R.azote + 1) / 2 + w.get("zone", 0) * (R.zone + 1) / 2
                  + w.get("documentation", 0) * R.documentation)
    R["cle"] = R.rotation.map(lambda s: min([s, s[1:] + s[:1], s[2:] + s[:2]]))
    R = R.sort_values("score", ascending=False).drop_duplicates("cle").drop(columns="cle")
    if distinctes:                                           # une seule ligne par combinaison de cultures (meilleur ordre)
        R = R[~R.rotation.map(lambda s: tuple(sorted(s))).duplicated()]
    return R.reset_index(drop=True)


# ------------------------------------------------------------------ VÉRIFICATION DE LA BASE
REQUIS = {
    "Seuils_Numeriques": ["ID", "Culture", "Cycle min (j)", "Cycle max (j)", "Pluie annuelle min viable (mm)",
                          "Pluie max tolérée (mm)", "Besoin en eau du cycle min (mm)", "Besoin en eau du cycle max (mm)",
                          "T° air critique max (°C)", "pH min toléré", "pH optimal min", "pH optimal max", "pH max toléré",
                          "Retour min sur même parcelle (ans)", "Fixation N (kg N/ha)",
                          "Rendement paysan min (kg/ha)", "Rendement paysan max (kg/ha)"],
    "Cultures_Generalites": ["ID", "Famille botanique", "Type", "Tolérance à la sécheresse", "Phase critique (eau)"],
    "Rotation_Regles": ["ID", "Bilan azote du sol"],
    "Calendrier_Cultural": ["ID"] + MOIS,
    "Matrice_Rotation": [],
    "Zones_Agroclimatiques": ["Zone", "Cultures bien adaptées", "Cultures à risque"],
    "Regles_Exemples": ["ID règle", "Culture(s)"],
}


def verifier_base(xlsx):
    """Vérifie que le fichier Excel a la structure attendue. Renvoie la liste des problèmes (vide si tout va bien)."""
    problemes = []
    if not Path(xlsx).exists():
        return [f"Fichier introuvable : {xlsx}"]
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    for onglet, colonnes in REQUIS.items():
        if onglet not in wb.sheetnames:
            problemes.append(f"Onglet manquant : « {onglet} »")
            continue
        entete = [str(h).strip() if h else "" for h in next(wb[onglet].iter_rows(values_only=True))]
        for c in colonnes:
            if c not in entete:
                problemes.append(f"Onglet « {onglet} » : colonne manquante « {c} »")
    if not problemes:
        zones = load_zones(xlsx)
        for site, z in HYPOTHESES["zone_site"].items():
            if z not in zones:
                problemes.append(f"Zone « {z} » (site {site}) absente de l'onglet Zones_Agroclimatiques")
    return problemes


# ------------------------------------------------------------------ RÉVISION AU DÉBUT DES PLUIES
def revision(S, V, C, mat, autorisees, site, cid, precedent, annee, res_j, onset=None):
    """Au début réel des pluies : variété retenue pour la culture prévue et, si elle est trop risquée,
    remplacement par une culture de la même famille compatible avec le précédent (matrice de rotation)."""
    vid, p = choix_adaptatif(S, V, site, cid, annee, res_j, onset)
    out = {"culture_prevue": C.loc[cid, "culture"], "variete_retenue": V.loc[vid, "label"], "vid": vid, "p": p,
           "remplacement": "-", "vid_final": vid, "p_final": p}
    if not np.isnan(p) and p < HYPOTHESES["confiance"]:
        alts = []
        for c2 in autorisees:
            if c2 == cid or C.loc[c2, "famille"] != C.loc[cid, "famille"] or mat.get((precedent, c2), 1) == 0:
                continue
            v2, p2 = choix_adaptatif(S, V, site, c2, annee, res_j, onset)
            alts.append((p2, c2, v2))
        alts.sort(reverse=True)
        if alts and alts[0][0] > p:
            p2, c2, v2 = alts[0]
            out.update(remplacement=f"{V.loc[v2, 'label']} ({p2:.0%} de chances)", vid_final=v2, p_final=p2)
        else:
            out.update(remplacement="aucune culture de la même famille plus sûre : semis à risque")
    return out


# ------------------------------------------------------------------ ÉVALUATION PAR TYPE D'ANNÉE (classes d'Issa)
def evaluation_classes(S, Vs, C, succ, site, res_j, classes):
    """Compare, pour chaque culture à variétés réelles et chaque année, deux agriculteurs :
    - fixe : sème toujours la variété la plus longue qui a réussi >= 80 % des autres années ;
    - conseillé : suit le moteur (variété choisie au vu du début des pluies, sur les autres années).
    Chaque année est jugée sans que le moteur la connaisse. classes : DataFrame site, annee, classe_annee."""
    ok = succ.set_index(["annee", "vid"]).ok
    annees = sorted(S[S.site == site].annee.unique())
    cl = classes[classes.site == site].set_index("annee").classe_annee
    rows = []
    testees = set(succ.vid)                                 # variétés des cultures autorisées sur le site
    for cid in Vs[Vs.nommee & Vs.index.isin(testees)].id.unique():
        cands = Vs[(Vs.id == cid) & Vs.index.isin(testees)].sort_values("cycle", ascending=False)
        if len(cands) < 2:                                  # une seule variété : rien à adapter
            continue
        for y in annees:
            fix = next((vid for vid in cands.index
                        if np.mean([ok.get((a, vid), False) for a in annees if a != y]) >= HYPOTHESES["confiance"]),
                       cands.index[-1])
            ada, _ = choix_adaptatif(S, Vs, site, cid, y, res_j)
            c = str(cl.get(y, "")).replace("defavorable_aucune_saison", "defavorable")
            rows.append({"site": site, "culture": C.loc[cid, "culture"].split(" (")[0], "annee": y, "classe": c,
                         "var_fixe": Vs.loc[fix, "label"], "cycle_fixe": Vs.loc[fix, "cycle"], "ok_fixe": bool(ok.get((y, fix), False)),
                         "var_conseil": Vs.loc[ada, "label"], "cycle_conseil": Vs.loc[ada, "cycle"],
                         "ok_conseil": bool(ok.get((y, ada), False))})
    return pd.DataFrame(rows)
