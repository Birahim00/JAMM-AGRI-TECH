"""
Lance le moteur de rotation JAMM AGRI-TECH et écrit les résultats dans un fichier Excel.

Usage :
    python lancer_rotation.py
    python lancer_rotation.py --excel data/ma_base.xlsx --sortie resultats_rotation.xlsx --top 5
"""
import argparse, sys
from pathlib import Path
import numpy as np
import pandas as pd
import core, soil, rotation as rt

HERE = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", default=str(HERE / "data" / "cultures_sahel_parametres_verifie.xlsx"))
    ap.add_argument("--sortie", default=str(HERE / "resultats_rotation.xlsx"))
    ap.add_argument("--varietes", default=str(HERE / "data" / "besoins_cultures_varietes.csv"),
                    help="tableau des variétés réelles (laisser un chemin inexistant pour n'utiliser que des variétés génériques)")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()

    # 1. Vérification de la base agronomique
    pb = rt.verifier_base(a.excel)
    if pb:
        print("La base agronomique n'a pas la structure attendue :")
        for p in pb:
            print("  -", p)
        sys.exit(1)
    print(f"Base agronomique OK : {a.excel}")

    # 2. Données climatiques et sols
    data = HERE / "data"
    et0 = {s: pd.read_csv(data / "power_extra" / f"{s}_2005_2024.csv", parse_dates=["date"])
              .query("date.dt.month == 10").ET0_HARGREAVES_mm.mean() for s in core.SITES}
    SOIL, RES = soil.load(data, et0)
    core.RESERVE_SITE.update(RES)
    D = core.load_daily(data)
    S = core.detect_seasons(D)
    C, mat = rt.load_base(a.excel)
    NV = rt.load_varietes_nommees(a.varietes)
    V = rt.varietes(C, NV)
    Z = rt.load_zones(a.excel)
    print(f"{len(C)} cultures retenues, {len(V)} variétés ({int(V.nommee.sum())} variétés réelles nommées, "
          f"{int((~V.nommee).sum())} génériques), {len(mat)} cases dans la matrice de rotation\n")

    synthese, decisions, varietes, revisions, isos, evals = [], [], [], [], [], []
    f_cl = data / "issa" / "dataset_site_annee.csv"
    CL = pd.read_csv(f_cl)[["site", "annee", "classe_annee"]] if f_cl.exists() else None
    for site in core.SITES:
        rfu = 0.5 * SOIL.loc[site, "reserve_utile_mm"]
        R, dec, succ, Vs, iso = rt.rotations_site(D, S, C, V, mat, SOIL, site, core.reserve(site), rfu, Z, top=a.top)
        for vid, r in iso.iterrows():
            isos.append({"Site": core.LABEL[site], "Variété": r.label, "Compatible avec la pluie du site": "oui" if r.compatible_zone else "non",
                         "Motif": r.motif, "Portée de la source": V.loc[vid, "portee"]})
        autorisees = list(dec[dec.statut == "autorisée"].index)

        print(f"=== {core.LABEL[site]} : zone {rt.HYPOTHESES['zone_site'][site]}, réserve en eau {core.reserve(site)} j, "
              f"{len(autorisees)} cultures autorisées sur {len(dec)}")
        for i, r in R.iterrows():
            print(f"  {i + 1}. {r.rotation_txt:45s} cycles réussis {r.reussite:4.0%} | pires années {r.pire_cas:4.0%} "
                  f"| score {r.score:.2f}")
        if not R.empty and R.iloc[0].reussite < 0.7:
            print("  ⚠ Agriculture pluviale très risquée sur ce site : envisager l'irrigation.")
        print()

        for i, r in R.iterrows():
            synthese.append({"Site": core.LABEL[site], "Rang": i + 1, "Rotation (3 ans)": r.rotation_txt,
                             "Cycles réussis": round(r.reussite, 3), "Pires années (20 %)": round(r.pire_cas, 3),
                             "Potentiel exploité": round(r.potentiel, 3), "Bilan azote (-1 à +1)": round(r.azote, 2),
                             "Adaptation zone (-1 à +1)": round(r.zone, 2), "Successions (0 à 1)": round(r.compatibilite, 2),
                             "Variétés documentées": round(r.documentation, 2),
                             "Cultures sans données variétales": ", ".join(sorted({C.loc[c, "culture"].split(" (")[0] for c in r.rotation
                                                                                  if not V[V.id == c].nommee.any()})) or "-",
                             "Score": round(r.score, 3)})
        for cid, d in dec.iterrows():
            decisions.append({"Site": core.LABEL[site], "ID": cid, "Culture": d.culture, "Statut": d.statut,
                              "Règles déclenchées": d.regles})
        taux = succ.groupby("vid").agg(reussite=("ok", "mean")).join(
            succ[~succ.ok].groupby("vid").cause.agg(lambda x: x.value_counts().idxmax()).rename("cause"))
        for vid, t in taux.iterrows():
            varietes.append({"Site": core.LABEL[site], "Variété": V.loc[vid, "label"], "Culture": V.loc[vid, "culture"],
                             "Cycle (j)": V.loc[vid, "cycle"], "Variété réelle": "oui" if V.loc[vid, "nommee"] else "générique",
                             "Réussite 2005-2024": round(t.reussite, 2),
                             "Cause d'échec la plus fréquente": t.cause if isinstance(t.cause, str) else "",
                             "Source": V.loc[vid, "source"]})
        if CL is not None and site != "Richard-Toll":         # Richard-Toll : pluvial non viable, exclu de l'évaluation
            evals.append(rt.evaluation_classes(S, Vs, C, succ, site, core.reserve(site), CL))
        # révision au début des pluies pour la meilleure rotation, rejouée année par année
        if not R.empty:
            seq = R.rotation.iloc[0]
            ok = succ.set_index(["annee", "vid"])
            for k, y in enumerate(sorted(S[S.site == site].annee.unique())):
                cid, prev = seq[k % 3], seq[(k - 1) % 3]
                on = S[(S.site == site) & (S.annee == y)].debut.iloc[0]
                if on is None or pd.isna(on):
                    revisions.append({"Site": core.LABEL[site], "Année": y, "Début des pluies": "aucune saison",
                                      "Culture prévue": C.loc[cid, "culture"], "Variété retenue": "", "Chance de boucler": "",
                                      "Remplacement conseillé": "pas de semis pluvial", "Résultat réel": "échec (pas de saison)"})
                    continue
                rv = rt.revision(S, Vs, C, mat, autorisees, site, cid, prev, y, core.reserve(site))
                res = ok.loc[(y, rv["vid_final"])] if (y, rv["vid_final"]) in ok.index else None
                revisions.append({"Site": core.LABEL[site], "Année": y, "Début des pluies": core.doy_to_str(on, y),
                                  "Culture prévue": rv["culture_prevue"], "Variété retenue": rv["variete_retenue"],
                                  "Chance de boucler": round(rv["p"], 2), "Remplacement conseillé": rv["remplacement"],
                                  "Résultat réel": ("cycle bouclé" if res.ok else f"échec ({res.cause})") if res is not None else ""})

    hyp = [{"Paramètre": k, "Valeur": str(v)} for k, v in rt.HYPOTHESES.items()]
    hyp += [{"Paramètre": f"réserve en eau du sol ({core.LABEL[s]})", "Valeur": f"{v} jours"} for s, v in RES.items()]
    with pd.ExcelWriter(a.sortie, engine="openpyxl") as xw:
        pd.DataFrame(synthese).to_excel(xw, sheet_name="Rotations", index=False)
        pd.DataFrame(revisions).to_excel(xw, sheet_name="Revision_debut_saison", index=False)
        pd.DataFrame(varietes).sort_values(["Site", "Réussite 2005-2024"], ascending=[True, False]) \
          .to_excel(xw, sheet_name="Reussite_varietes", index=False)
        pd.DataFrame(decisions).to_excel(xw, sheet_name="Regles_par_site", index=False)
        pd.DataFrame(isos).to_excel(xw, sheet_name="Varietes_zone_pluie", index=False)
        if evals:
            E = pd.concat(evals)
            E["site"] = E.site.map(core.LABEL)
            def bilan(g):
                return pd.Series({"Décisions": len(g), "Échecs agriculteur fixe": int((~g.ok_fixe).sum()),
                                  "Échecs agriculteur conseillé": int((~g.ok_conseil).sum()),
                                  "Échecs évités": int((~g.ok_fixe).sum() - (~g.ok_conseil).sum()),
                                  "Cycle moyen fixe (j)": round(g.cycle_fixe.mean(), 1),
                                  "Cycle moyen conseillé (j)": round(g.cycle_conseil.mean(), 1)})
            ordre = {"defavorable": 0, "moyenne": 1, "favorable": 2}
            T = E.groupby("classe").apply(bilan).reset_index()
            T = T.sort_values("classe", key=lambda x: x.map(ordre))
            T = pd.concat([T, bilan(E).to_frame().T.assign(classe="TOTAL")])
            T = T.rename(columns={"classe": "Type d'année (classes d'Issa)"})
            Ts = E.groupby(["site", "classe"]).apply(bilan).reset_index().rename(columns={"site": "Site", "classe": "Type d'année"})
            T.to_excel(xw, sheet_name="Evaluation", index=False)
            Ts.to_excel(xw, sheet_name="Evaluation", index=False, startrow=len(T) + 3)
            E.assign(ok_fixe=E.ok_fixe.map({True: "bouclé", False: "échec"}),
                     ok_conseil=E.ok_conseil.map({True: "bouclé", False: "échec"})).rename(columns={
                "site": "Site", "culture": "Culture", "annee": "Année", "classe": "Type d'année",
                "var_fixe": "Variété agriculteur fixe", "cycle_fixe": "Cycle fixe (j)", "ok_fixe": "Résultat fixe",
                "var_conseil": "Variété conseillée", "cycle_conseil": "Cycle conseillé (j)", "ok_conseil": "Résultat conseillé"}) \
             .to_excel(xw, sheet_name="Evaluation_detail", index=False)
            print(f"Évaluation (classes d'Issa) : échecs agriculteur fixe {int((~E.ok_fixe).sum())}, "
                  f"agriculteur conseillé {int((~E.ok_conseil).sum())} sur {len(E)} décisions")
        pd.DataFrame(hyp).to_excel(xw, sheet_name="Hypotheses", index=False)
        for ws in xw.book.worksheets:                       # largeur des colonnes
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col) + 2))
            ws.freeze_panes = "A2"
    print(f"Résultats écrits dans : {a.sortie}")


if __name__ == "__main__":
    main()
