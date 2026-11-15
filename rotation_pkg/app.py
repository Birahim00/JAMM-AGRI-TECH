"""
Field Shift | JAMM AGRI-TECH
Decision-support app: crop rotations and variety choice at the onset of the rains (Senegal).

Run:  streamlit run app.py
"""
import datetime as dt
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import rotation as rt
import donnees_app as da

st.set_page_config(page_title="Field Shift | JAMM AGRI-TECH", page_icon="🌾", layout="wide")

# ------------------------------------------------------------------ STYLE
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; padding-bottom: 2rem;}
h1, h2, h3, h4 {color: #1F3B24;}
.bandeau {background: linear-gradient(90deg, #1F3B24 0%, #2F6B3A 60%, #C8892B 100%); color: white;
          padding: 18px 26px; border-radius: 14px; margin-bottom: 14px;}
.bandeau h1 {color: white; margin: 0; font-size: 1.9rem;}
.bandeau p {margin: 4px 0 0 0; opacity: .92;}
.kpi {background: #FFFFFF; border: 1px solid #E6DFCF; border-radius: 12px; padding: 12px 14px; height: 100%;}
.kpi .v {font-size: 1.45rem; font-weight: 700; color: #1F3B24;}
.kpi .l {font-size: .82rem; color: #6B6455;}
.carte {background: #FFFFFF; border: 1px solid #E6DFCF; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px;}
.carte.choisie {border: 2px solid #2F6B3A; box-shadow: 0 2px 10px rgba(47,107,58,.15);}
.puce {display: inline-block; padding: 4px 11px; border-radius: 999px; color: white; font-weight: 600;
       font-size: .84rem; margin: 2px 3px 2px 0;}
.puce i {font-weight: 400; opacity: .9;}
.fleche {color: #8A8270; margin: 0 2px;}
.ligne {font-size: .9rem; color: #3B3A33; margin: 3px 0;}
.alerte {background: #FFF4E0; border: 1px solid #F0C987; border-radius: 10px; padding: 10px 14px; color: #6A4A10;}
.tel {width: 300px; margin: auto; background: #1E1E1E; border-radius: 34px; padding: 16px 12px 22px 12px;
      box-shadow: 0 8px 24px rgba(0,0,0,.25);}
.ecran {background: #ECE5DD; border-radius: 22px; padding: 14px 12px; min-height: 320px;}
.entete-sms {text-align: center; font-size: .78rem; color: #6B6455; margin-bottom: 8px;}
.bulle {background: white; border-radius: 4px 14px 14px 14px; padding: 10px 12px; font-size: .9rem; color: #1E1E1E;
        line-height: 1.38; box-shadow: 0 1px 1px rgba(0,0,0,.08);}
.heure {text-align: right; font-size: .7rem; color: #8A8270; margin-top: 4px;}
.trad {background: #FFFFFF; border: 1px dashed #CFC6B3; border-radius: 10px; padding: 10px 12px; font-size: .85rem;
       color: #4A473E; margin-top: 12px;}
.parcelle {background: #FFFFFF; border-radius: 12px; padding: 12px 14px; border-left: 6px solid #2F6B3A;
           border-top: 1px solid #E6DFCF; border-right: 1px solid #E6DFCF; border-bottom: 1px solid #E6DFCF;}
.petit {font-size: .8rem; color: #6B6455;}
table.sources {border-collapse: collapse; font-size: .86rem; width: 100%; background: white;}
table.sources th {background: #F1EBDD; text-align: left; padding: 8px 10px; color: #1F3B24;}
table.sources td {padding: 7px 10px; border-top: 1px solid #EEE7D8; vertical-align: top;}
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Computing rotations from 20 years of NASA data (first run only, about 15 s)...")
def donnees():
    return da.charger()


DON = donnees()


@st.cache_data
def pays():
    import json
    return json.load(open(da.DATA / "afrique_ouest.geojson", encoding="utf-8"))


PAYS = pays()
C, S, D = DON["C"], DON["S"], DON["D"]
PARCELS = ["A", "B", "C"]
YEAR0 = 2027
SITE_NAME = {"Thies": "Thiès", "Kaolack": "Kaolack", "Ziguinchor": "Ziguinchor", "Richard-Toll": "Richard-Toll"}

# local crop name (as used in Senegal) and English translation
CROP = {"Mil à chandelle": ("Mil", "pearl millet"), "Sorgho": ("Sorgho", "sorghum"), "Maïs": ("Maïs", "maize"),
        "Riz": ("Riz", "rice"), "Fonio": ("Fonio", ""), "Arachide": ("Arachide", "groundnut"),
        "Niébé": ("Niébé", "cowpea"), "Soja": ("Soja", "soybean"), "Voandzou": ("Voandzou", "Bambara groundnut"),
        "Sésame": ("Sésame", "sesame"), "Coton": ("Coton", "cotton"), "Bissap": ("Bissap", "roselle"),
        "Pastèque": ("Pastèque", "watermelon")}
PROFILE_EN = {"Équilibré": "Balanced", "Sécurité": "Safety", "Fertilité du sol": "Soil fertility", "Production": "Production"}
PROFILE_TXT = {"Équilibré": "a bit of everything: safety, soil, production",
               "Sécurité": "never lose the harvest, even in bad years",
               "Fertilité du sol": "enrich the soil with nitrogen-fixing legumes",
               "Production": "sow longer, more productive varieties"}
TEXTURE_EN = {"limono-sableuse": "sandy loam", "limono-argilo-sableuse": "sandy clay loam",
              "limono-argileuse": "clay loam", "sableuse": "sandy", "argileuse": "clay", "limoneuse": "loam"}
CAUSE_EN = {"saison trop courte": "season too short", "eau insuffisante": "not enough water",
            "sécheresse à la floraison (R12)": "dry spell at flowering (R12)",
            "chaleur à la floraison (R13)": "heat at flowering (R13)", "saison non installée": "no rainy season"}
CLASS_EN = {"defavorable": "Unfavourable years", "moyenne": "Average years", "favorable": "Favourable years"}


def court(cid):
    return da.nom_court(C.loc[cid, "culture"])


def nom(cid):
    """Local name with English translation, e.g. 'Arachide (groundnut)'."""
    loc, en = CROP.get(court(cid), (court(cid), ""))
    return f"{loc} ({en})" if en else loc


def nom_local(cid):
    return CROP.get(court(cid), (court(cid), ""))[0]


def couleur(cid):
    return da.COULEURS.get(court(cid), "#888888")


def puce(cid):
    loc, en = CROP.get(court(cid), (court(cid), ""))
    return f'<span class="puce" style="background:{couleur(cid)}">{loc}{f" <i>({en})</i>" if en else ""}</span>'


def var_txt(V, vid):
    """Variety label in English: 'Arachide 55-33 (80 days)' or 'Fonio, generic (75 days)'."""
    v = V.loc[vid]
    loc = CROP.get(da.nom_court(v.culture), (da.nom_court(v.culture), ""))[0]
    return f"{loc} {v.variete} ({int(v.cycle)} days)" if v.nommee else f"{loc}, generic ({int(v.cycle)} days)"


def date_en(doy, year=YEAR0):
    d = dt.date(year, 1, 1) + dt.timedelta(days=int(doy) - 1)
    return f"{d.day} {d.strftime('%B')}"


def rules_en(t):
    if t == "aucune":
        return "none"
    rep = [(r"\(alerte\) : pluie moyenne ([\d.]+) mm > ([\d.]+) mm tolérés", r"(alert): mean rainfall \1 mm > \2 mm tolerated"),
           (r"\(info\) : pH ([\d.]+) hors optimum", r"(info): pH \1 outside optimum"),
           (r"amendement conseillé", "soil amendment advised"),
           (r": année sèche ([\d.]+) mm < ([\d.]+) mm viables", r": dry-year rainfall \1 mm < \2 mm needed"),
           (r": pH ([\d.]+) hors de", r": pH \1 outside"),
           (r"Zone Sahélienne", "Sahelian zone"), (r"Zone Sahélo-soudanienne", "Sahelo-Sudanian zone"),
           (r"Zone Sub-guinéenne", "Sub-Guinean zone"), (r"culture à risque \(pénalisée\)", "crop at risk (penalised)"),
           (r"aucune variété compatible avec la pluie du site \(isohyètes\)", "no variety suited to the site's rainfall (isohyets)"),
           (r" ; ", "; ")]
    for a, b in rep:
        t = re.sub(a, b, t)
    return t


# ------------------------------------------------------------------ SIDEBAR
with st.sidebar:
    st.markdown("### 🌾 Field Shift")
    st.caption("JAMM AGRI-TECH · NASA Space Apps Challenge 2026")
    site = st.selectbox("📍 Location (Senegal)", core.SITES, index=1, format_func=lambda s: SITE_NAME[s])
    info = DON["sites"][site]
    autorisees = info["autorisees"]

    st.markdown("#### Farmer priorities")
    priorite = st.radio("What matters most to you?", list(rt.PROFILS), index=0,
                        format_func=lambda p: PROFILE_EN[p], captions=[PROFILE_TXT[p] for p in rt.PROFILS])
    voulues = st.multiselect("Crops you want to grow", autorisees, format_func=nom, placeholder="Choose...",
                             help="The rotation will include at least one of these crops (market, home consumption...).")
    refusees = st.multiselect("Crops you do not want", [c for c in autorisees if c not in voulues], format_func=nom,
                              placeholder="Choose...", help="No seeds, no market, not used to it...")
    st.divider()
    fond = st.radio("Farm map background", ["Satellite", "Plain"], horizontal=True)
    st.caption("Data: NASA POWER, GPM IMERG, SMAP, MODIS, SoilGrids. Preliminary results: agronomic parameters "
               "still to be validated by experts.")

# ------------------------------------------------------------------ HEADER
st.markdown(f"""
<div class="bandeau"><h1>Field Shift · {SITE_NAME[site]}, Senegal</h1>
<p>Which crop rotation for my farm, and which variety should I sow when the rains arrive?
Recommendations built on 20 years of NASA Earth observations (2005-2024).</p></div>
""", unsafe_allow_html=True)

k = st.columns(5)
kpis = [(f"{info['pluie_med']:.0f} mm", "median annual rainfall"),
        (date_en(info["debut_med"]), "median onset of the rains"),
        (f"{info['duree_med']:.0f} days", "median rainy-season length"),
        (f"{info['reserve_j']} days", "soil water reserve after the last rain"),
        (f"pH {info['ph']:.1f}", f"{TEXTURE_EN.get(info['texture'], info['texture'])} soil")]
for col, (v, l) in zip(k, kpis):
    col.markdown(f'<div class="kpi"><div class="v">{v}</div><div class="l">{l}</div></div>', unsafe_allow_html=True)
st.write("")

if site == "Richard-Toll":
    st.markdown('<div class="alerte">⚠️ <b>Rain-fed farming is very risky in Richard-Toll</b>: with about '
                f'{info["pluie_med"]:.0f} mm of rain, even the best rotation completes barely 1 crop cycle in 5. '
                'Farming here relies on irrigation (Senegal River valley).</div>', unsafe_allow_html=True)
    st.write("")

# ------------------------------------------------------------------ RANKING FROM FARMER PRIORITIES
R = rt.classer(info["R"], rt.PROFILS[priorite], voulues, refusees, distinctes=True)

onglets = st.tabs(["🗺️ My farm", "🌧️ Rain onset", "⏪ Replay a past year", "📊 20-year evidence", "🛰️ NASA data"])

# ================================================================== 1. MY FARM
with onglets[0]:
    if R.empty:
        st.warning("No rotation satisfies your wanted crops, your refused crops and the agronomic rules at the same "
                   "time. Remove a constraint in the left panel.")
        st.stop()

    top = R.head(3)
    m1, m2 = st.columns([0.9, 1.3])
    with m1:
        st.markdown("**The 4 study sites in Senegal**")
        fs = go.Figure()
        for feat in PAYS["features"]:                         # country borders, bundled with the app (works offline)
            geom = feat["geometry"]
            polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
            sen = feat["properties"]["iso"] == "SEN"
            for poly in polys:
                lon_, lat_ = zip(*poly[0])
                fs.add_trace(go.Scatter(x=lon_, y=lat_, fill="toself", mode="lines", hoverinfo="skip", showlegend=False,
                                        fillcolor="#F3EBD9" if sen else "#ECE8DF",
                                        line=dict(color="#A79D86" if sen else "#C9C1AE", width=1.6 if sen else 1)))
        for txt, la, lo in [("SENEGAL", 14.75, -14.4), ("MAURITANIA", 16.9, -13.4), ("MALI", 14.2, -11.6),
                            ("THE GAMBIA", 13.75, -15.9), ("GUINEA-BISSAU", 12.0, -15.2), ("GUINEA", 12.15, -12.4),
                            ("Atlantic<br>Ocean", 13.3, -17.3)]:
            fs.add_trace(go.Scatter(x=[lo], y=[la], mode="text", text=[txt], hoverinfo="skip", showlegend=False,
                                    textfont=dict(size=15 if txt == "SENEGAL" else 10,
                                                  color="#6B6455" if txt == "SENEGAL" else "#9A927F")))
        for s_, v in DON["sites"].items():
            best = rt.classer(v["R"])
            rr = best.reussite.iloc[0] if not best.empty else 0
            sel = s_ == site
            fs.add_trace(go.Scatter(
                x=[v["lon"]], y=[v["lat"]], mode="markers+text", text=[f"<b>{SITE_NAME[s_]}</b>" if sel else SITE_NAME[s_]],
                textposition="middle left" if s_ == "Thies" else "middle right",
                textfont=dict(size=14 if sel else 12, color="#1F3B24" if sel else "#5A5446"),
                marker=dict(size=10 + v["pluie_med"] / 70, color="#2F6B3A" if sel else "#C8892B",
                            line=dict(color="white", width=2), opacity=0.95),
                hovertemplate=f"<b>{SITE_NAME[s_]}</b><br>median rainfall {v['pluie_med']:.0f} mm<br>"
                              f"median rain onset {date_en(v['debut_med'])}<br>"
                              f"best rotation: {rr:.0%} of crop cycles completed<extra></extra>", showlegend=False))
        fs.update_xaxes(range=[-17.8, -11.2], visible=False)
        fs.update_yaxes(range=[11.9, 17.2], visible=False, scaleanchor="x", scaleratio=1.033)
        fs.update_layout(height=430, margin=dict(l=0, r=0, t=0, b=0), plot_bgcolor="#DCEBF2", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fs, width="stretch", config={"displayModeBar": False})
        st.caption("Dot size: annual rainfall, from the dry Sahelian north to the humid south. Hover a site for details.")

    with m2:
        a1, a2 = st.columns([1, 1.2])
        with a1:
            choix = st.radio("Rotation shown on the farm", list(range(len(top))), horizontal=True,
                             format_func=lambda i: f"No. {i + 1}")
        with a2:
            annee = st.slider("Season", YEAR0, YEAR0 + 5, YEAR0, help="Move through the years to see the rotation turn.")
        seq = R.rotation.iloc[choix]
        kk = annee - YEAR0
        cult_parc = [seq[(kk + p) % 3] for p in range(3)]
        lat0, lon0 = da.FERME[site]
        w, h, gap = 0.0030, 0.0042, 0.0007
        fig = go.Figure()
        for p, cid in enumerate(cult_parc):
            x0 = lon0 + (p - 1) * (w + gap) - w / 2
            xs = [x0, x0 + w, x0 + w, x0, x0]
            ys = [lat0 - h / 2, lat0 - h / 2, lat0 + h / 2, lat0 + h / 2, lat0 - h / 2]
            fig.add_trace(go.Scattermap(lon=xs, lat=ys, fill="toself", mode="lines", fillcolor=couleur(cid),
                                        line=dict(color="white", width=3), opacity=0.78, hoverinfo="text",
                                        text=f"Plot {PARCELS[p]} · {annee}: {nom(cid)}", showlegend=False))
            loc, en = CROP.get(court(cid), (court(cid), ""))
            fig.add_trace(go.Scattermap(lon=[x0 + w / 2], lat=[lat0], mode="text",
                                        text=[f"Plot {PARCELS[p]}<br>{loc}" + (f"<br>({en})" if en else "")],
                                        textfont=dict(size=14, color="white"), hoverinfo="skip", showlegend=False))
        layers, style = [], "carto-positron"
        if fond == "Satellite":
            style = "white-bg"
            layers = [{"sourcetype": "raster", "below": "traces", "sourceattribution": "Esri World Imagery",
                       "source": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"]}]
        fig.update_layout(map=dict(style=style, layers=layers, center=dict(lat=lat0, lon=lon0), zoom=14.6),
                          margin=dict(l=0, r=0, t=0, b=0), height=345)
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
        st.caption("Simulated plots, illustrative location. Each plot follows the same rotation shifted by one year, "
                   "so all three crops are on the farm every season.")

    st.write("")
    b1, b2 = st.columns([1, 1.15])
    with b1:
        st.markdown(f"#### Recommended rotations · priority: **{PROFILE_EN[priorite].lower()}**")
        for i, r in top.iterrows():
            chips = '<span class="fleche">→</span>'.join(puce(c) for c in r.rotation)
            legum = [nom(c) for c in dict.fromkeys(r.rotation) if C.loc[c, "bilan_n"] > 0]
            sans_var = [nom_local(c) for c in dict.fromkeys(r.rotation) if not info["V"][info["V"].id == c].nommee.any()]
            lignes = [f"✅ Crop cycle completed in <b>{r.reussite:.0%}</b> of cases over 2005-2024 "
                      f"(<b>{r.pire_cas:.0%}</b> in the worst years)"]
            lignes.append(f"🌱 {', '.join(legum)}: legume that adds nitrogen to the soil" if legum else
                          "🌱 No legume: the soil loses nitrogen, plan for manure or fertiliser")
            if sans_var:
                lignes.append(f"ℹ️ {', '.join(sans_var)}: no documented variety, generic values used")
            cls = "carte choisie" if i == choix else "carte"
            st.markdown(f'<div class="{cls}"><div style="display:flex;justify-content:space-between;align-items:center">'
                        f'<b>No. {i + 1}</b><span class="petit">score {r.score:.2f}</span></div>'
                        f'<div style="margin:6px 0 8px 0">{chips}</div>'
                        + "".join(f'<div class="ligne">{l}</div>' for l in lignes) + "</div>", unsafe_allow_html=True)
        if len(R) > 3 and abs(R.score.iloc[0] - R.score.iloc[min(4, len(R) - 1)]) < 0.03:
            st.caption("The top rotations have very close scores: they are almost equivalent, so the farmer chooses "
                       "based on experience. The tool supports the farmer's judgement, it does not replace it.")
    with b2:
        years = list(range(YEAR0, YEAR0 + 6))
        uniq = list(dict.fromkeys(seq))
        z, txt = [], []
        for p in range(3):
            z.append([uniq.index(seq[(j + p) % 3]) for j in range(len(years))])
            txt.append([nom_local(seq[(j + p) % 3]) for j in range(len(years))])
        n = len(uniq)
        scale = []
        for i, cid in enumerate(uniq):
            scale += [[i / n, couleur(cid)], [(i + 1) / n, couleur(cid)]]
        fr = go.Figure(go.Heatmap(z=z, x=[str(a) for a in years], y=[f"Plot {x}" for x in PARCELS], text=txt,
                                  texttemplate="%{text}", textfont=dict(color="white", size=13), colorscale=scale,
                                  zmin=0, zmax=n, showscale=False, xgap=4, ygap=4,
                                  hovertemplate="%{y}, %{x}: %{text}<extra></extra>"))
        fr.update_layout(height=230, margin=dict(l=0, r=0, t=34, b=0), plot_bgcolor="rgba(0,0,0,0)",
                         title=dict(text="Rotation plan over 6 seasons", font=dict(size=15)), yaxis=dict(autorange="reversed"))
        st.plotly_chart(fr, width="stretch", config={"displayModeBar": False})
        with st.expander("Why are some crops not proposed here?"):
            dec = info["dec"][info["dec"].statut == "exclue"].copy()
            dec = pd.DataFrame({"Crop": [nom(c) for c in dec.index], "Rules from the agronomic database": dec.regles.map(rules_en)})
            st.dataframe(dec, hide_index=True, width="stretch")

# ================================================================== 2. RAIN ONSET
with onglets[1]:
    st.markdown("#### The rains have just started: which variety should be sown on each plot?")
    st.caption("The onset of the rainy season is detected every year from NASA POWER daily rainfall: first rainy day after "
               "1 May with at least 20 mm over 3 days and no 7-day dry spell in the following month.")
    c1, c2 = st.columns([1.3, 1])
    debut_def = dt.date(annee, 1, 1) + dt.timedelta(days=int(info["debut_med"]) - 1)
    with c1:
        d_on = st.slider("Date the rains set in", min_value=dt.date(annee, 6, 1), max_value=dt.date(annee, 8, 31),
                         value=debut_def, format="DD/MM")
        onset = d_on.timetuple().tm_yday
        ecart = onset - info["debut_med"]
        etat = "early" if ecart < -7 else "late" if ecart > 7 else "normal"
        quand = ("on the usual date" if abs(ecart) < 1 else
                 f"{abs(ecart):.0f} days {'earlier' if ecart < 0 else 'later'} than usual")
        st.markdown(f"Season **{annee}** (set in the My farm tab). Rains set in on **{date_en(onset, annee)}**, "
                    f"**{quand}**: **{etat}** season.")
        cult_parc = [seq[(kk + p) % 3] for p in range(3)]
        prev_parc = [seq[(kk + p - 1) % 3] for p in range(3)]
        recs = []
        pc = st.columns(3)
        for p in range(3):
            rv = rt.revision(S, info["V"], C, DON["mat"], autorisees, site, cult_parc[p], prev_parc[p], 9999,
                             info["reserve_j"], onset=onset)
            recs.append(rv)
            vid_f, p_f = rv["vid_final"], rv["p_final"]
            bord = "#2F6B3A" if p_f >= 0.8 else "#C8892B" if p_f >= 0.6 else "#B0305A"
            extra = ""
            if vid_f != rv["vid"]:
                extra = (f'<div class="ligne">🔁 {nom_local(cult_parc[p])} too risky this year: switched to a crop of '
                         f'the same family</div>')
            elif p_f < 0.8:
                extra = '<div class="ligne">⚠️ No safer crop of the same family: risky sowing</div>'
            pc[p].markdown(f'<div class="parcelle" style="border-left-color:{bord}">'
                           f'<div class="petit">Plot {PARCELS[p]} · planned: {nom(cult_parc[p])}</div>'
                           f'<div style="font-size:1.05rem;font-weight:700;margin:4px 0">{var_txt(info["V"], vid_f)}</div>'
                           f'<div class="ligne">Chance to complete the cycle: <b>{p_f:.0%}</b></div>{extra}</div>',
                           unsafe_allow_html=True)
        st.write("")
        par = st.selectbox("Variety details for", range(3),
                           format_func=lambda p: f"Plot {PARCELS[p]} ({nom(info['V'].loc[recs[p]['vid_final'], 'id'])})")
        cid_par = info["V"].loc[recs[par]["vid_final"], "id"]
        P = da.proba_varietes(S, info["V"], site, cid_par, onset, info["reserve_j"])
        P["txt"] = [var_txt(info["V"], v) for v in P.vid]
        cols_b = ["#2F6B3A" if v == recs[par]["vid_final"] else ("#9CC77E" if p >= 0.8 else "#D9C9A8")
                  for v, p in zip(P.vid, P.p)]
        fb = go.Figure(go.Bar(x=P.p * 100, y=P.txt, orientation="h", marker_color=cols_b,
                              text=[f"{p:.0%}" for p in P.p], textposition="outside",
                              hovertemplate="%{y}: %{x:.0f}%<extra></extra>"))
        fb.add_vline(x=80, line=dict(color="#B0305A", dash="dash", width=2),
                     annotation_text="80% confidence threshold", annotation_position="top")
        fb.update_layout(height=max(220, 34 * len(P) + 60), margin=dict(l=0, r=30, t=30, b=0),
                         xaxis=dict(range=[0, 112], title="chance to complete the cycle before the rains end (%)"),
                         plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(autorange="reversed"))
        st.plotly_chart(fb, width="stretch", config={"displayModeBar": False})
        st.caption("Dark green: the recommended variety, i.e. the longest (most productive) one with at least an 80% "
                   "chance of maturing before the end of the rains, based on the 20 observed seasons.")
    with c2:
        fr_parts, en_parts = [], []
        for p, rv in enumerate(recs):
            v = info["V"].loc[rv["vid_final"]]
            loc = CROP.get(da.nom_court(v.culture), (da.nom_court(v.culture), ""))[0]
            nm = f"{loc} {v.variete}" if v.nommee else loc
            ok = rv["p_final"] >= 0.8
            fr_parts.append(f"Parcelle {PARCELS[p]} : {nm}, {int(v.cycle)} j" + (f" ({rv['p_final']:.0%})" if ok else " (risqué)"))
            en_parts.append(f"Plot {PARCELS[p]}: {nm}, {int(v.cycle)} days" + (f" ({rv['p_final']:.0%})" if ok else " (risky)"))
        conseil_fr = ("Saison courte prévue : semez rapidement." if ecart > 7 else
                      "Saison longue possible : variétés longues conseillées." if ecart < -7 else "Saison normale.")
        conseil_en = ("Short season expected: sow quickly." if ecart > 7 else
                      "Long season possible: longer varieties advised." if ecart < -7 else "Normal season.")
        date_fr = core.doy_to_str(onset, annee).rstrip(".")
        sms = (f"JAMM AGRI-TECH | {SITE_NAME[site]} : pluies installées le {date_fr}. {conseil_fr}<br><br>"
               + "<br>".join(fr_parts))
        st.markdown(f'<div class="tel"><div class="ecran"><div class="entete-sms">Field Shift · SMS</div>'
                    f'<div class="bulle">{sms}<div class="heure">{d_on.strftime("%d/%m")} · 08:00</div></div></div></div>',
                    unsafe_allow_html=True)
        st.markdown(f'<div class="trad"><b>English translation</b><br>JAMM AGRI-TECH | {SITE_NAME[site]}: rains set in on '
                    f'{date_en(onset, annee)}. {conseil_en}<br><br>' + "<br>".join(en_parts) + "</div>", unsafe_allow_html=True)
        st.caption("Farmers receive the SMS in French on a basic phone, no internet needed.")

# ================================================================== 3. REPLAY A PAST YEAR
with onglets[2]:
    E = info["E"]
    if E.empty:
        st.info("No evaluation for this site: rain-fed farming is not viable here.")
    else:
        st.markdown("#### What if the tool had existed? Replay a past season")
        c1, c2 = st.columns([1, 2.4])
        lab2vid = {v: k_ for k_, v in info["V"].label.items()}
        with c1:
            cultures_e = sorted(E.culture.unique())
            disp = {c_: nom(C.index[C.culture.map(da.nom_court) == c_][0]) for c_ in cultures_e}
            cult = st.selectbox("Crop", cultures_e, index=cultures_e.index("Arachide") if "Arachide" in cultures_e else 0,
                                format_func=lambda c_: disp[c_])
            annees_e = sorted(E.annee.unique())
            an = st.select_slider("Year", annees_e, value=2019 if 2019 in annees_e else annees_e[-1])
            row = E[(E.culture == cult) & (E.annee == an)].iloc[0]
            lab_cl = {"defavorable": "🔴 unfavourable", "moyenne": "🟡 average", "favorable": "🟢 favourable"}
            st.markdown(f"Year classified as **{lab_cl.get(row.classe, row.classe)}** (independent classification by "
                        "team member Issa).")
            succ = info["succ"].set_index(["annee", "vid"])

            def bilan(lbl, ok):
                vid = lab2vid.get(lbl)
                cause = succ.loc[(an, vid)].cause if (an, vid) in succ.index else ""
                return "✅ harvest possible" if ok else f"❌ failure: {CAUSE_EN.get(cause, cause)}"
            vf, vc = lab2vid[row.var_fixe], lab2vid[row.var_conseil]
            st.markdown(f'<div class="carte"><div class="petit">Farmer alone (always the same variety)</div>'
                        f'<b>{var_txt(info["V"], vf)}</b><div class="ligne">{bilan(row.var_fixe, row.ok_fixe)}</div></div>'
                        f'<div class="carte choisie"><div class="petit">Farmer advised by Field Shift</div>'
                        f'<b>{var_txt(info["V"], vc)}</b><div class="ligne">{bilan(row.var_conseil, row.ok_conseil)}</div></div>',
                        unsafe_allow_html=True)
            st.caption("The advice for that year is computed without knowing the year: only its rain-onset date and the "
                       "19 other seasons are used.")
        with c2:
            sa = S[(S.site == site) & (S.annee == an)].iloc[0]
            g = D[(D.site == site) & (D.annee == an)].set_index("doy")
            fen = g.loc[140:330]
            j = lambda d: dt.date(an, 1, 1) + dt.timedelta(days=int(d) - 1)
            fg = go.Figure()
            fg.add_trace(go.Bar(x=[j(d) for d in fen.index], y=fen.PRECTOTCORR, marker_color="#4F8FC0",
                                name="daily rainfall (mm)", hovertemplate="%{x|%d %b}: %{y:.1f} mm<extra></extra>"))
            ymax = max(10, float(fen.PRECTOTCORR.max()))
            if not pd.isna(sa.debut):
                fg.add_vrect(x0=j(sa.debut), x1=j(sa.fin), fillcolor="#2F6B3A", opacity=0.07, line_width=0)
                fg.add_vrect(x0=j(sa.fin), x1=j(sa.fin + info["reserve_j"]), fillcolor="#C8892B", opacity=0.12, line_width=0)
                fg.add_annotation(x=j(sa.fin + info["reserve_j"] / 2), y=ymax * 0.55, text="soil<br>reserve",
                                  showarrow=False, font=dict(size=10, color="#8A6420"))
                fg.add_vline(x=j(sa.debut), line=dict(color="#2F6B3A", width=2))
                fg.add_annotation(x=j(sa.debut), y=ymax * 1.42, text=f"rain onset<br>{date_en(sa.debut, an)}",
                                  showarrow=False, font=dict(size=11, color="#2F6B3A"), xanchor="left")
                fg.add_vline(x=j(sa.fin), line=dict(color="#8C3B2E", width=2, dash="dot"))
                fg.add_annotation(x=j(sa.fin), y=ymax * 1.42, text=f"end of rains<br>{date_en(sa.fin, an)}",
                                  showarrow=False, font=dict(size=11, color="#8C3B2E"), xanchor="right")
                for k_, (vid_, cyc, ok, who) in enumerate([(vf, row.cycle_fixe, row.ok_fixe, "alone"),
                                                           (vc, row.cycle_conseil, row.ok_conseil, "advised")]):
                    y = ymax * (1.12 + 0.13 * k_)
                    fg.add_trace(go.Scatter(x=[j(sa.debut), j(sa.debut + cyc - 1)], y=[y, y], mode="lines+markers",
                                            line=dict(color="#2F6B3A" if ok else "#B0305A", width=9), marker=dict(size=9),
                                            name=f"{who}: {var_txt(info['V'], vid_)}",
                                            hovertemplate=f"{who}: {var_txt(info['V'], vid_)}<br>sowing → maturity<extra></extra>"))
            ticks = [dt.date(an, m_, 1) for m_ in range(6, 13)]
            fg.update_xaxes(tickvals=ticks, ticktext=[t.strftime("%b") for t in ticks])
            fg.update_layout(height=430, margin=dict(l=0, r=0, t=10, b=0), plot_bgcolor="rgba(0,0,0,0)",
                             yaxis=dict(title="rainfall (mm/day)", range=[0, ymax * 1.6]),
                             legend=dict(orientation="h", y=-0.15), bargap=0.1)
            st.plotly_chart(fg, width="stretch", config={"displayModeBar": False})
            st.caption(f"NASA POWER rainfall in {SITE_NAME[site]}, {an}. Horizontal bars: from sowing to maturity of each "
                       "variety (green: cycle completed in time, red: failure). Soil water reserve: "
                       f"{info['reserve_j']} days after the last rain.")

# ================================================================== 4. 20-YEAR EVIDENCE
with onglets[3]:
    tous = pd.concat([v["E"].assign(site=k_) for k_, v in DON["sites"].items() if not v["E"].empty])
    st.markdown("#### Does the tool do better than a farmer who always sows the same variety?")
    st.caption("Groundnut, millet, sorghum and maize in Thiès, Kaolack and Ziguinchor, 2005-2024: 200 sowing decisions "
               "replayed. Each year is judged without the tool knowing it (leave-one-year-out). Years classified "
               "independently of the tool by team member Issa.")
    ef, ec = int((~tous.ok_fixe).sum()), int((~tous.ok_conseil).sum())
    m = st.columns(4)
    m[0].metric("Failures, farmer alone", ef)
    m[1].metric("Failures, farmer advised", ec, delta=f"{ec - ef} failures", delta_color="inverse")
    m[2].metric("Failures avoided", f"{(ef - ec) / ef:.0%}")
    m[3].metric("Mean cycle sown", f"{tous.cycle_conseil.mean():.0f} days",
                delta=f"+{tous.cycle_conseil.mean() - tous.cycle_fixe.mean():.0f} days")
    ordre = ["defavorable", "moyenne", "favorable"]
    G = tous.groupby("classe").agg(fixe=("ok_fixe", lambda x: int((~x).sum())), cons=("ok_conseil", lambda x: int((~x).sum())),
                                   n=("annee", "size")).reindex(ordre)
    fe = go.Figure()
    fe.add_trace(go.Bar(x=[CLASS_EN[c_] for c_ in ordre], y=G.fixe, name="Farmer alone", marker_color="#C8B79A",
                        text=G.fixe, textposition="outside"))
    fe.add_trace(go.Bar(x=[CLASS_EN[c_] for c_ in ordre], y=G.cons, name="Advised by Field Shift", marker_color="#2F6B3A",
                        text=G.cons, textposition="outside"))
    fe.update_layout(barmode="group", height=360, margin=dict(l=0, r=0, t=20, b=0), plot_bgcolor="rgba(0,0,0,0)",
                     yaxis=dict(title="number of failed crop cycles"), legend=dict(orientation="h", y=1.1),
                     bargap=0.35, bargroupgap=0.08)
    c1, c2 = st.columns([1.5, 1])
    c1.plotly_chart(fe, width="stretch", config={"displayModeBar": False})
    with c2:
        st.markdown("**Key takeaways**")
        st.markdown(f"- {ef} failures without the tool, **{ec} with it**: about a quarter fewer.\n"
                    f"- **Unfavourable** years: {G.fixe['defavorable']} → **{G.cons['defavorable']}** failures, mostly "
                    "when the rains start late.\n"
                    f"- **Favourable** years: {G.fixe['favorable']} → **{G.cons['favorable']}**, with longer, more "
                    "productive varieties.\n"
                    "- The tool is sometimes wrong: a season that starts normally then stops early cannot be foreseen.\n"
                    "- \"Failure\" means the crop cycle did not finish in time; it is not a measured yield.")
    T = tous.groupby(["site", "classe"]).agg(**{"Decisions": ("annee", "size"),
                                                "Failures, alone": ("ok_fixe", lambda x: int((~x).sum())),
                                                "Failures, advised": ("ok_conseil", lambda x: int((~x).sum()))}).reset_index()
    T["site"] = T.site.map(SITE_NAME)
    T["classe"] = T.classe.map(CLASS_EN)
    st.dataframe(T.rename(columns={"site": "Site", "classe": "Year type"}), hide_index=True, width="stretch")

# ================================================================== 5. NASA DATA
with onglets[4]:
    st.markdown("#### The data behind every recommendation")
    c1, c2 = st.columns([1.1, 1])
    with c1:
        sources = pd.DataFrame([
            ["NASA POWER", "Daily rainfall, temperature, soil moisture, radiation (2005-2024)",
             "Detect the start and end of each rainy season; test each variety (water, dry spells, heat)"],
            ["GPM IMERG", "Daily satellite rainfall", "Check and correct POWER rainfall (2020 artefact)"],
            ["SMAP", "Satellite soil moisture", "Validate the soil moisture used (monthly correlation 0.84 to 0.95, "
                                                "0.58 in Richard-Toll)"],
            ["MODIS NDVI", "Vegetation greenness", "Check the vegetation seasonality around the sites"],
            ["SoilGrids", "Soil texture, pH, carbon, nitrogen (0-30 cm)", "pH rules; soil water reserve (Saxton & Rawls)"],
            ["Team agronomic database", "16 crops, rotation matrix, agro-climatic zones, rules", "Rotation rules and crop thresholds"],
            ["Variety catalogue (Issa)", "47 real varieties (cycle length, isohyets, sources)", "Choose the variety to sow"],
        ], columns=["Source", "What we use", "What it is for"])
        st.markdown(sources.to_html(index=False, border=0, classes="sources"), unsafe_allow_html=True)
    with c2:
        pm = info["pluie_mois"]
        mois = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        fm = go.Figure(go.Bar(x=mois, y=pm.values, marker_color=["#4F8FC0" if v > 50 else "#BFD3E3" for v in pm.values],
                              hovertemplate="%{x}: %{y:.0f} mm<extra></extra>"))
        fm.update_layout(height=320, margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)",
                         title=dict(text=f"Mean monthly rainfall in {SITE_NAME[site]} (NASA POWER, 2005-2024)",
                                    font=dict(size=13)), yaxis=dict(title="mm"))
        st.plotly_chart(fm, width="stretch", config={"displayModeBar": False})
