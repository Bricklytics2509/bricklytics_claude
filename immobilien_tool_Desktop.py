

import streamlit as st
import pandas as pd
import json
import os
import glob
import numpy as np
import plotly.graph_objects as go
 
 
class _StateProxy:
    """Leichter Ersatz für st.session_state.
 
    Damit die Heatmap berechne_cashflows() mit variierten Annahmen
    durchrechnen kann, OHNE den echten Zustand der App zu verändern.
    Unterstützt Attribut-Zugriff (proxy.zinssatz), .get() und das
    Zurückschreiben von proxy.afa_linear_basis_startjahr7.
    """
 
    def __init__(self, data):
        object.__setattr__(self, "_d", dict(data))  # flache Kopie -> isoliert
 
    def __getattr__(self, name):
        try:
            return object.__getattribute__(self, "_d")[name]
        except KeyError:
            raise AttributeError(name)
 
    def __setattr__(self, name, value):
        object.__getattribute__(self, "_d")[name] = value
 
    def get(self, key, default=None):
        return object.__getattribute__(self, "_d").get(key, default)
 
 
def _kpi_szenario(base_state, miete_pro_m2, wertsteigerung):
    """Rechnet EIN Szenario durch.
 
    Gibt (gesamtgewinn, ek_rendite_p_a) zurück.
    ek_rendite ist np.nan, wenn kein sinnvoller CAGR bildbar ist
    (Eigenkapital <= 0 oder Gesamtgewinn <= 0).
    """
    proxy = _StateProxy(base_state)
    proxy.miete_pro_m2 = float(miete_pro_m2)
    proxy.monatskaltmiete = float(proxy.wohnflaeche) * float(miete_pro_m2)
    proxy.afa_linear_basis_startjahr7 = None  # Carryover je Szenario zurücksetzen
 
    erg = berechne_cashflows(proxy)
    kumuliert = erg["kumuliert"]
    restschuld = erg["restschuld_bank"] + erg["restschuld_kfw"]
    ek = float(proxy.eigenkapital)
    kaufpreis = float(proxy.kaufpreis)
 
    verkaufspreis = kaufpreis * ((1 + wertsteigerung) ** 10)
    gesamtgewinn = verkaufspreis - restschuld - ek + kumuliert
 
    if ek > 0 and gesamtgewinn > 0:
        ek_rendite = (gesamtgewinn / ek) ** (1 / 10) - 1
    else:
        ek_rendite = np.nan
 
    return gesamtgewinn, ek_rendite
 
 
def _heatmap_farbe(v, vmin, vmax):
    """Rot -> Gelb -> Grün, normalisiert zwischen vmin und vmax."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "background-color:#2b2b2b; color:#777;"
    t = 0.5 if vmax <= vmin else (v - vmin) / (vmax - vmin)
    t = max(0.0, min(1.0, t))
    if t < 0.5:                      # rot -> gelb
        r, g, b = 200, int(70 + 130 * (t / 0.5)), 60
    else:                            # gelb -> grün
        r, g, b = int(200 - 140 * ((t - 0.5) / 0.5)), 180, 70
    return f"background-color: rgb({r},{g},{b}); color:#111; font-weight:600;"
 
 
def _kpi_card(titel, wert_str, farbe, sub):
    """Eine farbige KPI-Kachel fürs Cockpit (HTML)."""
    return (
        f'<div style="flex:1; min-width:160px; background:{farbe}; '
        f'border-radius:14px; padding:16px 18px; color:#fff;">'
        f'<div style="font-size:0.78rem; opacity:0.85;">{titel}</div>'
        f'<div style="font-size:1.6rem; font-weight:700; margin-top:4px;">{wert_str}</div>'
        f'<div style="font-size:0.76rem; opacity:0.92; margin-top:3px;">{sub}</div>'
        f'</div>'
    )
 
 
# Farbpalette (Ampel)
_GRUEN = "#1f7a3d"
_GELB = "#b58a00"
_ROT = "#a12b2b"
 

from modules.afa_steuer import berechne_afa_und_steuer
from modules.cashflow_berechnung import berechne_cashflows
from modules.vergleich import vergleichsuebersicht
from modules.steuer import TaxSettings

def _hex_to_rgb(hexfarbe):
    h = hexfarbe.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
 
 
def _pdf_clean(txt):
    """Ersetzt €/² durch PDF-sichere Zeichen (Kernschrift kann sie nicht)."""
    txt = (
        str(txt)
        .replace("€", " EUR")
        .replace("²", "2")
        .replace("—", "-")   # 👈 NEU: Geviertstrich
        .replace("–", "-")
        .replace("’", "'")
    )
    return txt.encode("latin-1", "replace").decode("latin-1")
 
 
def _pdf_grid(pdf, title, items, y, col_w=90, row_h=6, label_w=42):
    """Zeichnet eine Titel-Zeile + Label:Wert-Grid (2 Spalten). Gibt neue y zurück."""
    pdf.set_xy(15, y)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _pdf_clean(title), ln=True)
    y2 = y + 8
    for i, (label, val) in enumerate(items):
        col, row = i % 2, i // 2
        x = 15 + col * col_w
        pdf.set_xy(x, y2 + row * row_h)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(label_w, row_h, _pdf_clean(label + ":"))
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(col_w - label_w - 2, row_h, _pdf_clean(val))
    rows = (len(items) + 1) // 2
    return y2 + rows * row_h + 8
 
 
def _pdf_bericht(objekt_name, objekt_items, finanzierung_items, steuer_items,
                  kpis, ergebnis_items, etf_label, etf_rendite, etf_wert_nach_steuer):
    from fpdf import FPDF
    import datetime
 
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
 
    # --- Kopfbereich ---
    pdf.set_fill_color(30, 34, 43)
    pdf.rect(0, 0, 210, 26, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(15, 7)
    pdf.set_font("Helvetica", "B", 19)
    pdf.cell(0, 8, _pdf_clean("Bricklytics — Investment-Check"))
    pdf.set_xy(15, 17)
    pdf.set_font("Helvetica", "", 10)
    heute = datetime.date.today().strftime("%d.%m.%Y")
    pdf.cell(0, 6, _pdf_clean(f"{objekt_name}   |   Stand: {heute}"))
    pdf.set_text_color(20, 20, 20)
 
    y = 34
    y = _pdf_grid(pdf, "Objektdaten", objekt_items, y)
    y = _pdf_grid(pdf, "Finanzierung", finanzierung_items, y)
    y = _pdf_grid(pdf, "Steuerliche Annahmen", steuer_items, y)
 
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(15, y - 4)
    pdf.multi_cell(
        180, 3.2,
        _pdf_clean(
            "Die steuerliche Wirkung im Ergebnis basiert auf diesen Annahmen und "
            "ist eine Näherung – die individuelle Veranlagung kann abweichen."
        ),
    )
    pdf.set_text_color(20, 20, 20)
 
    # --- KPI-Kacheln ---
    y_kpi = y + 4
    pdf.set_xy(15, y_kpi)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, _pdf_clean("Auf einen Blick"), ln=True)
    y_kpi += 8
 
    box_w, box_h, gap = 42, 26, 3
    for i, k in enumerate(kpis):
        x = 15 + i * (box_w + gap)
        r, g, b = _hex_to_rgb(k["farbe"])
        pdf.set_fill_color(r, g, b)
        pdf.rect(x, y_kpi, box_w, box_h, style="F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(x + 2.5, y_kpi + 2.5)
        pdf.set_font("Helvetica", "", 7.5)
        pdf.multi_cell(box_w - 5, 3.2, _pdf_clean(k["titel"]))
        pdf.set_xy(x + 2.5, y_kpi + 9)
        pdf.set_font("Helvetica", "B", 12.5)
        pdf.cell(box_w - 5, 6, _pdf_clean(k["wert"]))
        pdf.set_xy(x + 2.5, y_kpi + 17)
        pdf.set_font("Helvetica", "", 6.8)
        pdf.multi_cell(box_w - 5, 3, _pdf_clean(k["sub"]))
    pdf.set_text_color(20, 20, 20)
 
    y = y_kpi + box_h + 10
    y = _pdf_grid(pdf, "Ergebnis nach 10 Jahren", ergebnis_items, y, label_w=48)

    # --- ETF-Hinweis ---
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_xy(15, y)   # explizit auf neue Zeile setzen – verhindert "Anhängen" an letzte Zelle
    pdf.multi_cell(
        180, 5,
        _pdf_clean(
            f"ETF-Vergleichsszenario: {etf_label} ({etf_rendite*100:.1f} % p.a.) "
            f"-> ETF-Wert nach Steuer (10 J): {etf_wert_nach_steuer:,.0f} EUR"
        ),
    )
    y_footer_start = pdf.get_y() + 6

    # --- Footer ---
    pdf.set_xy(15, 270)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, 268, 195, 268)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(
        180, 3.6,
        _pdf_clean(
            "Diese Zusammenfassung dient ausschließlich Informationszwecken und "
            "stellt keine Finanz-, Steuer- oder Anlageberatung dar. Steuerliche "
            "Effekte sind individuell und sollten durch einen Steuerberater "
            "geprüft werden. Erstellt mit Bricklytics."
        ),
    )
 
    raw = pdf.output()
    return bytes(raw) if not isinstance(raw, str) else raw.encode("latin-1")
 

def _verlauf_daten(base_state, wertsteigerung, etf_rendite):
    """Jahr-für-Jahr, Immobilie vs. ETF, Jahr 0–10.

    Liefert für beide Ansichten die Werte zurück:
      - Gewinn  (Eigenkapital abgezogen)
      - Vermögen (absolut)
    ETF nutzt dieselbe Zuzahlungs-/Steuerlogik wie die Cockpit-Kachel.
    """
    proxy = _StateProxy(base_state)
    proxy.afa_linear_basis_startjahr7 = None
    erg = berechne_cashflows(proxy)
    cfd = erg["cashflowdaten"]

    ek = float(proxy.eigenkapital)
    kaufpreis = float(proxy.kaufpreis)
    restschuld = float(proxy.kreditbetrag) + (
        float(proxy.kfw_betrag) if proxy.get("zweiter_kredit_aktiv", False) else 0.0
    )

    # Zuzahlung wie in der Kachel: Gesamt-Cashflow gleichmäßig auf 120 Monate
    kumuliert_final = cfd[-1]["Kumuliert"]
    zusatz_pa = (abs(kumuliert_final) / (10 * 12)) * 12 if kumuliert_final < 0 else 0.0

    jahre = [0]
    immo_verm, etf_verm = [ek], [ek]        # Vermögen startet beim eingesetzten EK
    immo_gew, etf_gew = [0.0], [0.0]        # Gewinn startet bei 0

    for j in range(1, 11):
        jahre.append(j)                     
        row = cfd[j - 1]
        restschuld = max(restschuld - (abs(row["Tilgung Bank"]) + abs(row["Tilgung KfW"])), 0.0)
        kum_cashflow = row["Kumuliert"]

        # --- Immobilie ---
        objektwert = kaufpreis * ((1 + wertsteigerung) ** j)
        v_immo = objektwert - restschuld + kum_cashflow   # Vermögen (Netto-Position)
        immo_verm.append(v_immo)
        immo_gew.append(v_immo - ek)                       # Gewinn = Vermögen − Einsatz

        # --- ETF (EK + aufgezinste Zuzahlungen, dann 25 % Steuer auf Gewinn) ---
        etf_vor = ek * ((1 + etf_rendite) ** j)
        etf_vor += sum(zusatz_pa * ((1 + etf_rendite) ** (j - k)) for k in range(1, j + 1))
        etf_gewinn_roh = (etf_vor - ek) * 0.75             # Steuer nur auf den Gewinn
        v_etf = ek + etf_gewinn_roh                        # Vermögen = Einsatz + Netto-Gewinn
        etf_verm.append(v_etf)
        etf_gew.append(etf_gewinn_roh)

    return jahre, immo_verm, etf_verm, immo_gew, etf_gew

# ---------------------------------------------
# einmalige Defaults für die §7b/DIN-277 Seite
# ---------------------------------------------
DIN_DEFAULTS = {
    "din_wohnflaeche": 0.0,
    "din_keller": 0.0,
    "din_tg": 0.0,
    "din_fahrrad": 0.0,
    "din_muell": 0.0,
    "din_gemeinschaft": 0.0,
    "din_kaufpreis_gesamt": 0.0,
    "din_anteil_tg_euro": 0.0,
    "din_anteil_grundstueck_euro": 0.0,
}

def init_din_keys():
    for k, v in DIN_DEFAULTS.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_din_keys()

TAX_DEFAULTS = {
    "tax_year": 2026,
    "filing_status": "single",
    "soli_aktiv": True,
    "kist_aktiv": False,
    "kist_state": "BY",
    "zve_ohne_immo": 80000.0,
}

def init_tax_defaults():
    for k, v in TAX_DEFAULTS.items():
        st.session_state.setdefault(k, v)
    if "tax_settings_obj" not in st.session_state or st.session_state["tax_settings_obj"] is None:
        st.session_state["tax_settings_obj"] = TaxSettings(
            year=st.session_state["tax_year"],
            filing_status=st.session_state["filing_status"],
            solidarity_surcharge=st.session_state["soli_aktiv"],
            church_tax=st.session_state["kist_aktiv"],
            church_tax_state=st.session_state["kist_state"],
        )

init_tax_defaults()

# --- Cookie Hinweis hier ---
#if "cookie_accepted" not in st.session_state:
 #   with st.sidebar:
  #      st.info("🍪 Diese App verwendet Cookies, um die Benutzererfahrung zu verbessern. Durch die Nutzung stimmen Sie der Verwendung von Cookies zu.")
   #     if st.button("OK, verstanden ✅"):
    #        st.session_state.cookie_accepted = True
#
#if "cookie_accepted" not in st.session_state or not st.session_state.cookie_accepted:
 #   st.stop()


def check_password():
    """Zugangscode-Abfrage. Gibt True zurück, wenn der Code stimmt."""
    def code_eingegeben():
        eingabe = st.session_state.get("code_input", "")
        gueltige_codes = st.secrets.get("access_codes", [])
        if eingabe in gueltige_codes:
            st.session_state["auth_ok"] = True
            st.session_state["code_input"] = ""  # Code nicht im Speicher lassen
        else:
            st.session_state["auth_ok"] = False

    if st.session_state.get("auth_ok", False):
        return True

    st.title("🔒 Bricklytics – Zugang")
    st.text_input(
        "Zugangscode eingeben",
        type="password",
        on_change=code_eingegeben,
        key="code_input",
    )
    if "auth_ok" in st.session_state and not st.session_state["auth_ok"]:
        st.error("❌ Ungültiger Zugangscode.")
    st.info("Noch keinen Zugang? Schreib eine Mail an deine@mail.de")
    return False


if not check_password():
    st.stop()

import streamlit as st

# --- Hier startet dein eigentliches Bricklytics Tool ---
st.title("🏠 Bricklytics Dashboard")
# ... dein restlicher Code ...

# 🧭 Seiten-Navigation
st.sidebar.title("📚 Navigation")
seite = st.sidebar.radio("Gehe zu", [
    "🏠 Startseite",
    "📋 Basisdaten",
    "💶 Finanzierung",
     "🏦 Kapitaldienstfähigkeit",   # 👈 neu
    "📈 Steuer",
    "🧮 Baukostenprüfung §7b",
    "💸 Cashflow",
    "📊 Ergebnis",
    "📊 Ergebnis (alte KPIs)",
    "💽 Projektverwaltung",
    "📚 Vergleich",
    "⚖️ Disclaimer"
])

# 📦 Gemeinsame Variablen
st.session_state.setdefault("kaufpreis", 300000)
st.session_state.setdefault("bundesland", "Hamburg")

# Seite 0: Start
if seite == "🏠 Startseite":
    st.title("🏠 Startseite")
    st.image("images/Bricklytics.png", width=300)
    st.markdown("""
    **Bricklytics** ist dein persönliches Tool für:
    
    - Immobilien-Analyse
    - Steuerberechnung
    - Cashflow-Planung
    - ETF-Vergleich

    👉 Wähle links im Menü deinen Startpunkt und lege los!
    """)

# Seite 1: Basisdaten
if seite == "📋 Basisdaten":
    st.title("📋 Basisdaten der Immobilie")

    # Kaufpreis
    st.session_state.kaufpreis = st.number_input("Kaufpreis (€)", value=st.session_state.kaufpreis)

    st.markdown("---")
    st.subheader("🏗️ Aufteilung des Kaufpreises")

    # Grundstücksanteil als session_state
    st.session_state.grundstueck_anteil_prozent = st.number_input(
        "Anteil Grundstückskosten (%)",
        value=st.session_state.get("grundstueck_anteil_prozent", 18.0)
    )

    grundstueckskosten = st.session_state.kaufpreis * (st.session_state.grundstueck_anteil_prozent / 100)
    herstellungskosten = st.session_state.kaufpreis - grundstueckskosten

    st.write(f"📌 Grundstückskosten: **{grundstueckskosten:,.2f} €**")
    st.write(f"🏗️ Herstellungskosten (Rest): **{herstellungskosten:,.2f} €**")

    st.session_state.grundstueckskosten = grundstueckskosten
    st.session_state.herstellungskosten = herstellungskosten

    # Standortwahl mit Speicherung
    st.session_state.bundesland = st.selectbox(
        "📍 Standort",
        ["Bayern", "Bremen","Hamburg", "Sachsen", "Schleswig Holstein"],
        index=["Bayern", "Bremen","Hamburg", "Sachsen", "Schleswig Holstein"].index(st.session_state.get("bundesland", "Hamburg"))
    )

    if st.session_state.bundesland == "Hamburg":
        grundsteuer_satz = 5.5
    elif st.session_state.bundesland == "Bayern":
        grundsteuer_satz = 3.5
    elif st.session_state.bundesland == "Bremen":
        grundsteuer_satz = 5.0
    elif st.session_state.bundesland == "Sachsen":
        grundsteuer_satz = 5.5
    elif st.session_state.bundesland == "Schleswig Holstein":
        grundsteuer_satz = 6.5
    notar_grundbuch_satz = 2.0

    st.markdown("#### 🧑‍💼 Maklerkosten")
    makler_option = st.radio(
        "Maklerkosten wählen:",
        ["0 % (keine Maklerkosten)", "3,57 % (Standard)", "Eigener Wert"],
        index=["0 % (keine Maklerkosten)", "3,57 % (Standard)", "Eigener Wert"].index(st.session_state.get("makler_option", "3,57 % (Standard)")),
        key="makler_radio"
    )

    # Den ausgewählten Text speichern
    st.session_state.makler_option = makler_option

    # Maklerkosten setzen
    if makler_option == "0 % (keine Maklerkosten)":
        makler_satz = 0.0
    elif makler_option == "3,57 % (Standard)":
        makler_satz = 3.57
    else:
        st.session_state.makler_eigener_wert = st.number_input(
            "Maklerprovision in %",
            value=st.session_state.get("makler_eigener_wert", 3.0),
            step=0.1
        )
        makler_satz = st.session_state.makler_eigener_wert

    # Maklerprovision speichern
    st.session_state.makler_satz = makler_satz

    # ➡️ Nebenkosten neu berechnen (Makler wird ja gewählt)
    nebenkosten = st.session_state.kaufpreis * (grundsteuer_satz + notar_grundbuch_satz + st.session_state.makler_satz) / 100

    st.session_state.nebenkosten = nebenkosten
    st.write(f"📦 Gesamte Nebenkosten: **{nebenkosten:,.2f} €**")
   

    st.markdown("---")
    st.subheader("📐 Wohnfläche & Miete")

    st.session_state.wohnflaeche = st.number_input(
    "Wohnfläche in m²",
    value=float(st.session_state.get("wohnflaeche", 80.0)),  # 👉 jetzt float
    format="%.1f"
    )

    st.session_state.miete_pro_m2 = st.number_input(
    "Kaltmiete pro m² (€)",
    value=float(st.session_state.get("miete_pro_m2", 10.0)),  # 👉 jetzt float
    format="%.2f"
    )

    st.markdown("### 📈 Mietentwicklung")

    st.session_state.setdefault("mietmodell", "Prozent p.a.")
    st.session_state.setdefault("mietsteigerung_prozent", 1.0)
    st.session_state.setdefault("staffel_eur_monat", 38.0)

    mietmodell = st.selectbox(
        "Modell wählen:",
        ["Prozent p.a.", "Staffelmiete (€/Monat pro Jahr)"],
        index=0 if st.session_state.get("mietmodell") == "Prozent p.a." else 1
    )

    st.session_state.mietmodell = mietmodell

    if mietmodell == "Prozent p.a.":
        st.session_state.mietsteigerung_prozent = st.number_input(
            "Mietsteigerung p.a. (%)",
            value=float(st.session_state.get("mietsteigerung_prozent", 1.0)),
            step=0.1
        )
        st.session_state.mietsteigerung = st.session_state.mietsteigerung_prozent / 100
        st.session_state.staffel_eur_monat = 0.0
    else:
        st.session_state.staffel_eur_monat = st.number_input(
            "Erhöhung pro Jahr (€/Monat)",
            value=float(st.session_state.get("staffel_eur_monat", 38.0)),
            step=1.0
        )
        st.session_state.mietsteigerung = 0.0

    monatskaltmiete = st.session_state.wohnflaeche * st.session_state.miete_pro_m2
    st.write(f"📆 Monatliche Kaltmiete: **{monatskaltmiete:,.2f} €**")
    st.write(f"📅 Jährliche Kaltmiete: **{monatskaltmiete * 12:,.2f} €**")

    st.session_state.monatskaltmiete = monatskaltmiete

# Seite 2: Finanzierung
elif seite == "💶 Finanzierung":
    st.title("💶 Finanzierung")
    st.write(f"**Kaufpreis:** {st.session_state.kaufpreis:,.2f} €")

    # Steuersätze je nach Bundesland
    if st.session_state.bundesland == "Hamburg":
        grundsteuer_satz = 5.5
    elif st.session_state.bundesland == "Bayern":
        grundsteuer_satz = 3.5
    elif st.session_state.bundesland == "Bremen":
        grundsteuer_satz = 5.0
    elif st.session_state.bundesland == "Schleswig Holstein":
        grundsteuer_satz = 6.5
    elif st.session_state.bundesland == "Sachsen":
        grundsteuer_satz = 5.5
    else:
        grundsteuer_satz = 5.5  # fallback

    notar_grundbuch_satz = 2.0
    makler_satz = st.session_state.get("makler_satz", 3.57)

    nebenkosten = st.session_state.kaufpreis * (grundsteuer_satz + notar_grundbuch_satz + makler_satz) / 100
    st.session_state.nebenkosten = nebenkosten

    st.write(f"**Nebenkosten:** {nebenkosten:,.2f} €")

    # Eingabe Eigenkapital
    st.session_state.eigenkapital = st.number_input(
        "Eigenkapital (€)",
        value=float(st.session_state.get("eigenkapital", nebenkosten)),
        step=1000.0,
        key="eigenkapital_input"
    )

    # Eingabe Hauptdarlehen
    st.session_state.kreditbetrag = st.number_input(
        "Kreditbetrag (€)",
        value=float(st.session_state.get("kreditbetrag", 300000)),
        step=1000.0,
        key="kreditbetrag_input"
    )

    st.session_state.zinssatz_anzeige = st.number_input(
        "Zinssatz (%)",
        value=float(st.session_state.get("zinssatz_anzeige", 2.5)),
        step=0.1,
        key="zinssatz_input"
    )

    st.session_state.tilgungssatz_anzeige = st.number_input(
        "Tilgungssatz (%)",
        value=float(st.session_state.get("tilgungssatz_anzeige", 2.0)),
        step=0.1,
        key="tilgungssatz_input"
    )

    # Umrechnen für Berechnung
    st.session_state.zinssatz = st.session_state.zinssatz_anzeige / 100
    st.session_state.tilgungssatz = st.session_state.tilgungssatz_anzeige / 100

    # Hauptdarlehensrate berechnen
    zins = st.session_state.kreditbetrag * st.session_state.zinssatz
    tilgung = st.session_state.kreditbetrag * st.session_state.tilgungssatz
    rate = zins + tilgung

    st.session_state.rate = rate

    st.write(f"💸 Monatliche Kreditrate (nur Hauptkredit): **{rate / 12:,.2f} €**")
    st.write(f"💸 Jährliche Kreditrate (nur Hauptkredit): **{rate:,.2f} €**")

    # Zweites Darlehen aktivieren
    st.markdown("### 💡 Zweites Darlehen hinzufügen (z. B. KfW-Förderung)")

    if "zweiter_kredit_aktiv" not in st.session_state:
        st.session_state.zweiter_kredit_aktiv = False

    st.session_state.zweiter_kredit_aktiv = st.checkbox(
        "➕ Zweites Darlehen aktivieren",
        value=st.session_state.zweiter_kredit_aktiv,
        key="zweiter_kredit_checkbox"
    )

    if st.session_state.zweiter_kredit_aktiv:
        st.session_state.kfw_betrag = st.number_input(
            "Darlehenshöhe zweites Darlehen (€)",
            value=st.session_state.get("kfw_betrag", 40000.0),
            step=1000.0
        )

        st.session_state.kfw_zins_anzeige = st.number_input(
            "Zinssatz zweites Darlehen (%)",
            value=st.session_state.get("kfw_zins_anzeige", 1.0),
            step=0.1
        )

        st.session_state.kfw_tilgung_anzeige = st.number_input(
            "Tilgungssatz zweites Darlehen (%)",
            value=st.session_state.get("kfw_tilgung_anzeige", 1.5),
            step=0.1
        )

        st.session_state["tilgungsfreie_jahre_kfw"] = st.number_input("Tilgungsfreie Jahre (KfW)",
        min_value=0,
        max_value=10,
        value=st.session_state.get("tilgungsfreie_jahre_kfw", 1),
        step=1,
        key="tilgungsfreie_jahre_kfw_input"
        )



        st.session_state.kfw_zins = st.session_state.kfw_zins_anzeige / 100
        st.session_state.kfw_tilgung = st.session_state.kfw_tilgung_anzeige / 100
    else:
        st.session_state.kfw_betrag = 0.0
        st.session_state.kfw_zins = 0.0
        st.session_state.kfw_tilgung = 0.0

    if st.session_state.zweiter_kredit_aktiv:
        kfw_zinsbetrag = st.session_state.kfw_betrag * st.session_state.kfw_zins
        kfw_tilgungsbetrag = st.session_state.kfw_betrag * st.session_state.kfw_tilgung
        kfw_rate = kfw_zinsbetrag + kfw_tilgungsbetrag

        st.session_state.kfw_rate = kfw_rate

        st.write(f"💸 Monatliche Kreditrate (zweites Darlehen): **{kfw_rate / 12:,.2f} €**")
        st.write(f"💸 Jährliche Kreditrate (zweites Darlehen): **{kfw_rate:,.2f} €**")
    else:
        st.session_state.kfw_rate = 0.0

    # Mischzinsberechnung
    haupt_betrag = st.session_state.kreditbetrag
    haupt_zins = st.session_state.zinssatz
    haupt_tilgung = st.session_state.tilgungssatz

    kfw_betrag = st.session_state.kfw_betrag
    kfw_zins = st.session_state.kfw_zins
    kfw_tilgung = st.session_state.kfw_tilgung

    gesamt_kredit = haupt_betrag + kfw_betrag

    if gesamt_kredit > 0:
        mischzins = (haupt_betrag * haupt_zins + kfw_betrag * kfw_zins) / gesamt_kredit
        mischtilgung = (haupt_betrag * haupt_tilgung + kfw_betrag * kfw_tilgung) / gesamt_kredit

        st.session_state.mischzins = mischzins
        st.session_state.mischtilgung = mischtilgung
        st.session_state.gesamtdarlehen = gesamt_kredit

        st.markdown("#### 🔀 Mischfinanzierung (automatisch berechnet)")
        st.write(f"📌 Gesamtdarlehen: **{gesamt_kredit:,.0f} €**")
        st.write(f"📊 Mischzins: **{mischzins * 100:.2f} %**")
        st.write(f"📉 Mischtilgung: **{mischtilgung * 100:.2f} %**")

    gesamt_rate = st.session_state.rate + st.session_state.kfw_rate

    st.markdown("#### 💰 Gesamtrate beider Darlehen")
    st.write(f"💸 Monatliche Gesamtrate: **{gesamt_rate / 12:,.2f} €**")
    st.write(f"💸 Jährliche Gesamtrate: **{gesamt_rate:,.2f} €**")
 
#Seite Kapitaldeinstfähigkeit
elif seite == "🏦 Kapitaldienstfähigkeit":
    st.title("🏦 Kapitaldienstfähigkeit")
    st.caption(
        "Bankensicht: Kann dieser Kredit neben den laufenden Lebenshaltungskosten "
        "getragen werden? Diese Rechnung ist eine Näherung – jede Bank hat eigene "
        "Pauschalen und Stress-Annahmen."
    )

    if ("herstellungskosten" not in st.session_state or "monatskaltmiete" not in st.session_state
            or "kreditbetrag" not in st.session_state):
        st.warning("⚠️ Bitte zuerst die Seiten 'Basisdaten' und 'Finanzierung' ausfüllen.")
        st.stop()

    st.markdown("### 📥 Haushaltsdaten")

    st.session_state.setdefault("hh_nettoeinkommen", 5000.0)
    st.session_state.setdefault("hh_haushaltsgroesse", "2 Erwachsene")
    st.session_state.setdefault("hh_lebenshaltung", 2600.0)
    st.session_state.setdefault("hh_aktuelle_wohnkosten", 0.0)
    st.session_state.setdefault("hh_sonstige_raten", 0.0)
    st.session_state.setdefault("hh_anrechnungssatz", 75)
    st.session_state.setdefault("hh_stresszins", 5.5)

    st.session_state.hh_nettoeinkommen = st.number_input(
        "Haushaltsnettoeinkommen (mtl., alle Personen zusammen)",
        value=float(st.session_state.hh_nettoeinkommen), step=100.0,
    )

    lebenshaltung_defaults = {
        "1 Erwachsener": 1300.0,
        "2 Erwachsene": 2600.0,
        "2 Erwachsene + Kind(er)": 3200.0,
    }
    hg = st.selectbox(
        "Haushaltsgröße (setzt Vorschlagswert für Lebenshaltung)",
        list(lebenshaltung_defaults.keys()),
        index=list(lebenshaltung_defaults.keys()).index(st.session_state.hh_haushaltsgroesse),
    )
    if hg != st.session_state.hh_haushaltsgroesse:
        st.session_state.hh_lebenshaltung = lebenshaltung_defaults[hg]
    st.session_state.hh_haushaltsgroesse = hg

    st.session_state.hh_lebenshaltung = st.number_input(
        "Lebenshaltungspauschale (mtl.)",
        value=float(st.session_state.hh_lebenshaltung), step=50.0,
        help="Bankübliche Pauschale für Lebensunterhalt – variiert je Institut.",
    )
    st.session_state.hh_aktuelle_wohnkosten = st.number_input(
        "Aktuelle Wohnkosten (mtl., z.B. eigene Miete – 0 falls entfällt)",
        value=float(st.session_state.hh_aktuelle_wohnkosten), step=50.0,
    )
    st.session_state.hh_sonstige_raten = st.number_input(
        "Sonstige Kreditraten / Unterhaltszahlungen (mtl.)",
        value=float(st.session_state.hh_sonstige_raten), step=50.0,
    )
    st.session_state.hh_anrechnungssatz = st.slider(
        "Anrechnungssatz Mieteinnahmen (bankueblich 70-80 %)",
        min_value=50, max_value=100, value=int(st.session_state.hh_anrechnungssatz),
    )

    # --- Werte aus anderen Seiten ziehen ---
    kapitaldienst_mtl = (float(st.session_state.rate) + float(st.session_state.get("kfw_rate", 0.0))) / 12.0
    bewirtschaftung_mtl = (
        float(st.session_state.get("verwaltungskosten_monatlich", 0.0))
        + float(st.session_state.get("instandhaltung_monatlich", 0.0))
    )
    angerechnete_miete = float(st.session_state.monatskaltmiete) * (st.session_state.hh_anrechnungssatz / 100.0)

    einnahmen = st.session_state.hh_nettoeinkommen + angerechnete_miete
    ausgaben = (
        st.session_state.hh_lebenshaltung
        + st.session_state.hh_aktuelle_wohnkosten
        + st.session_state.hh_sonstige_raten
        + bewirtschaftung_mtl
        + kapitaldienst_mtl
    )
    ueberschuss = einnahmen - ausgaben
    ueberschuss_quote = (ueberschuss / st.session_state.hh_nettoeinkommen * 100) if st.session_state.hh_nettoeinkommen else 0.0

    st.markdown("### 📊 Haushaltsrechnung")
    tabelle = [
        {"Position": "Haushaltsnettoeinkommen", "Betrag": f"+ {st.session_state.hh_nettoeinkommen:,.0f} €"},
        {"Position": f"Angerechnete Kaltmiete ({st.session_state.hh_anrechnungssatz:.0f} %)", "Betrag": f"+ {angerechnete_miete:,.0f} €"},
        {"Position": "Summe Einnahmen", "Betrag": f"{einnahmen:,.0f} €"},
        {"Position": "Lebenshaltungspauschale", "Betrag": f"- {st.session_state.hh_lebenshaltung:,.0f} €"},
        {"Position": "Aktuelle Wohnkosten", "Betrag": f"- {st.session_state.hh_aktuelle_wohnkosten:,.0f} €"},
        {"Position": "Sonstige Raten/Unterhalt", "Betrag": f"- {st.session_state.hh_sonstige_raten:,.0f} €"},
        {"Position": "Bewirtschaftung (nicht umlagefähig)", "Betrag": f"- {bewirtschaftung_mtl:,.0f} €"},
        {"Position": "Kapitaldienst neue Finanzierung", "Betrag": f"- {kapitaldienst_mtl:,.0f} €"},
        {"Position": "Monatlicher Überschuss", "Betrag": f"{ueberschuss:,.0f} €"},
    ]
    st.dataframe(pd.DataFrame(tabelle).set_index("Position"), use_container_width=True)

    if ueberschuss < 0:
        st.error(f"🔴 Unterdeckung: {ueberschuss:,.0f} € / Monat – Finanzierung mit diesen Annahmen nicht tragbar.")
    elif ueberschuss_quote < 15:
        st.warning(f"🟡 Knapper Überschuss: {ueberschuss:,.0f} € / Monat ({ueberschuss_quote:.0f} % vom Netto) – wenig Puffer.")
    else:
        st.success(f"🟢 Komfortabler Überschuss: {ueberschuss:,.0f} € / Monat ({ueberschuss_quote:.0f} % vom Netto).")

    # --- Stresstest: höherer Zinssatz ---
    st.markdown("### ⚠️ Stresstest: höherer Zinssatz")
    st.caption("Wie tragfähig wäre die Finanzierung bei einem höheren Zinssatz (z. B. Anschlussfinanzierung)?")
    st.session_state.hh_stresszins = st.number_input(
        "Angenommener Stress-Zinssatz (%)",
        value=float(st.session_state.hh_stresszins), step=0.5,
    )
    kfw_aktiv = st.session_state.get("zweiter_kredit_aktiv", False)
    kredit_gesamt_heute = float(st.session_state.kreditbetrag) + (float(st.session_state.kfw_betrag) if kfw_aktiv else 0.0)
    rate_stress_mtl = kredit_gesamt_heute * (st.session_state.hh_stresszins / 100 + float(st.session_state.tilgungssatz)) / 12
    ueberschuss_stress = einnahmen - (
        st.session_state.hh_lebenshaltung + st.session_state.hh_aktuelle_wohnkosten
        + st.session_state.hh_sonstige_raten + bewirtschaftung_mtl + rate_stress_mtl
    )
    st.write(
        f"Bei **{st.session_state.hh_stresszins:.2f} %** Zins auf den heutigen Kreditbetrag "
        f"({kredit_gesamt_heute:,.0f} €) läge die Rate bei **{rate_stress_mtl:,.0f} € / Monat** "
        f"statt aktuell **{kapitaldienst_mtl:,.0f} € / Monat** – Überschuss dann: "
        f"**{ueberschuss_stress:,.0f} € / Monat**."
    )
    if ueberschuss_stress < 0:
        st.error("🔴 Im Stress-Szenario wäre die Finanzierung nicht mehr tragbar.")
    else:
        st.success("🟢 Auch im Stress-Szenario bleibt ein positiver Überschuss.")

    st.caption(
        "ℹ️ Banken nutzen eigene, teils strengere Pauschalen und Stresstest-Methoden. "
        "Diese Rechnung dient der Ersteinschätzung und ersetzt keine Bankprüfung."
    )

# Seite 3: Steuerrechnung
elif seite == "📈 Steuer":
    st.title("📈 Steuerrechnung über 10 Jahre")

    if "herstellungskosten" not in st.session_state or "monatskaltmiete" not in st.session_state:
        st.warning("⚠️ Bitte zuerst die Seiten 'Basisdaten' und 'Finanzierung' ausfüllen.")
        st.stop()

    # --- Steuerprogressionsmodell (Pfad 1) Einstellungen ---
    st.markdown("### 🧾 Einkommensteuer (Pfad 1 – Progression)")

    st.session_state.setdefault("tax_year", 2026)
    st.session_state.setdefault("filing_status", "single")  # single / joint
    st.session_state.setdefault("soli_aktiv", True)
    st.session_state.setdefault("kist_aktiv", False)
    st.session_state.setdefault("kist_state", "BY")
    st.session_state.setdefault("zve_ohne_immo", 80000.0)   # pragmatischer Startwert

    st.session_state.tax_year = st.selectbox("Steuerjahr", [2025, 2026], index=[2025, 2026].index(st.session_state.tax_year))
    st.session_state.filing_status = st.selectbox("Veranlagung", ["single", "joint"], index=["single", "joint"].index(st.session_state.filing_status))
    st.session_state.soli_aktiv = st.checkbox("Soli berücksichtigen", value=st.session_state.soli_aktiv)
    st.session_state.kist_aktiv = st.checkbox("Kirchensteuer berücksichtigen", value=st.session_state.kist_aktiv)
    if st.session_state.kist_aktiv:
        st.session_state.kist_state = st.selectbox("Bundesland KiSt", ["BY","BW","NW","HH","HE","BE","SN","SH","NI","RP","SL","ST","TH","BB","HB","MV"], index=["BY","BW","NW","HH","HE","BE","SN","SH","NI","RP","SL","ST","TH","BB","HB","MV"].index(st.session_state.kist_state))

    st.session_state.zve_ohne_immo = st.number_input(
        "Zu versteuerndes Einkommen (zvE) OHNE Immobilie (€/Jahr)",
        value=float(st.session_state.zve_ohne_immo),
        step=1000.0
    )

    tax_settings = TaxSettings(
        year=st.session_state.tax_year,
        filing_status=st.session_state.filing_status,
        solidarity_surcharge=st.session_state.soli_aktiv,
        church_tax=st.session_state.kist_aktiv,
        church_tax_state=st.session_state.kist_state,
    )
    st.session_state["tax_settings_obj"] = tax_settings  # für andere Seiten/Module

    # Defaults
    st.session_state.setdefault("afa_satz_degressiv", 0.05)
    st.session_state.setdefault("afa_satz_linear", 0.03)
    st.session_state.setdefault("afa_degressiv_switch_year", 7)
    st.session_state.setdefault("afa_linear_basis_startjahr7", None)

    # Verwaltungskosten (p.a.)
    st.session_state.verwaltungskosten_monatlich = st.number_input(
        "Verwaltungskosten (Euro pro Monat)",
        value=st.session_state.get("verwaltungskosten_monatlich", 50.0)
    )
    verwaltungskosten = float(st.session_state.verwaltungskosten_monatlich) * 12.0

    # Bemessungsgrundlage
    bemessungsgrundlage = float(st.session_state.herstellungskosten) + float(st.session_state.nebenkosten)
    st.write(f"📐 Bemessungsgrundlage: **{bemessungsgrundlage:,.2f} €**")

    # AfA-Option
    abschreibung_option = st.selectbox(
        "Abschreibungssatz wählen:",
        ["5% (Neubau ab 01.10.23)", "3% (ab 01.01.23)", "2% (vor 01.01.23)"],
        index=["5% (Neubau ab 01.10.23)", "3% (ab 01.01.23)", "2% (vor 01.01.23)"].index(
            st.session_state.get("afa_option", "5% (Neubau ab 01.10.23)")
        )
    )
    st.session_state.afa_option = abschreibung_option

    sonder_afa_effizienzhaus = abschreibung_option.startswith("5%") and st.checkbox(
        "✅ Sonder-AfA Effizienzhaus 40 möglich",
        value=st.session_state.get("sonder_afa_effizienzhaus", False),
        key="sonder_afa_effizienzhaus_checkbox"
    )
    st.session_state.sonder_afa_effizienzhaus = sonder_afa_effizienzhaus

    # Eingaben / Sätze
    kaltmiete_start = float(st.session_state.monatskaltmiete) * 12.0

    # WICHTIG: Getrennte Sätze, KEIN Mischzins in Berechnungen
    zinssatz_bank     = float(st.session_state.zinssatz)         # z.B. 0.0384
    tilgungssatz_bank = float(st.session_state.tilgungssatz)     # z.B. 0.01

    zweiter_aktiv = bool(st.session_state.get("zweiter_kredit_aktiv", False))
    zinssatz_kfw      = float(st.session_state.kfw_zins) if zweiter_aktiv else 0.0   # z.B. 0.0103
    tilgungssatz_kfw  = float(st.session_state.kfw_tilgung) if zweiter_aktiv else 0.0 # z.B. 0.0264
    tfj = int(st.session_state.get("tilgungsfreie_jahre_kfw", 0)) if zweiter_aktiv else 0

    # Start-Restschulden
    restschuld_bank = float(st.session_state.kreditbetrag)
    restschuld_kfw  = float(st.session_state.kfw_betrag) if zweiter_aktiv else 0.0

    # Fixe Anfangs-Annuitäten je Darlehen (Rate bleibt konstant)
    jahresrate_bank_fix = restschuld_bank * (zinssatz_bank + tilgungssatz_bank)
    jahresrate_kfw_fix  = restschuld_kfw  * (zinssatz_kfw  + tilgungssatz_kfw) if zweiter_aktiv else 0.0

    # Laufende Größen
    afa_basis = bemessungsgrundlage
    tilgungsdaten = []
    steuerdaten = []
    st.session_state.steuerwirkung_jahre = {}
    progressionsdaten = []

    for jahr in range(1, 11):
        mietmodell = st.session_state.get("mietmodell", "Prozent p.a.")

        if mietmodell == "Staffelmiete (€/Monat pro Jahr)":
            staffel = float(st.session_state.get("staffel_eur_monat", 0.0))
            mietertrag = (kaltmiete_start / 12.0 + staffel * (jahr - 1)) * 12.0
        else:
            mietsteigerung = float(st.session_state.get("mietsteigerung", 0.01))
            mietertrag = kaltmiete_start * ((1.0 + mietsteigerung) ** (jahr - 1))
    
        # --- Bankdarlehen ---
        rest_bank_anfang = restschuld_bank
        zinsen_bank = restschuld_bank * zinssatz_bank
        tilgung_bank = max(jahresrate_bank_fix - zinsen_bank, 0.0)
        restschuld_bank = max(restschuld_bank - tilgung_bank, 0.0)

        # --- KfW-Darlehen ---
        zinsen_kfw = tilgung_kfw = 0.0
        rest_kfw_anfang = restschuld_kfw if zweiter_aktiv else 0.0

        if zweiter_aktiv and restschuld_kfw > 0.0:
            zinsen_kfw = restschuld_kfw * zinssatz_kfw
            if jahr <= tfj:
                # Tilgungsfrei: nur Zinsen werden gezahlt
                tilgung_kfw = 0.0
                # (Rate = zinsen_kfw, aber für AfA/Steuer irrelevant)
            else:
                # Nach TFP: konstante Anfangsrate wie üblich
                tilgung_kfw = max(jahresrate_kfw_fix - zinsen_kfw, 0.0)

            restschuld_kfw = max(restschuld_kfw - tilgung_kfw, 0.0)

        # --- AfA & Steuerberechnung ---
        result = berechne_afa_und_steuer(
            jahr=jahr,
            afa_basis=afa_basis,
            wohnflaeche=st.session_state.wohnflaeche,
            afa_option=st.session_state.afa_option,
            sonder_afa_effizienzhaus=st.session_state.sonder_afa_effizienzhaus,
            mietertrag=mietertrag,
            verwaltungskosten=verwaltungskosten,
            zinsen=(zinsen_bank + zinsen_kfw),
            afa_satz_degressiv=st.session_state.afa_satz_degressiv,
            afa_satz_linear=st.session_state.afa_satz_linear,
            degressiv_switch_year=st.session_state.afa_degressiv_switch_year,
            afa_linear_basis_startjahr7=st.session_state.afa_linear_basis_startjahr7,
            bemessungsgrundlage=bemessungsgrundlage,
            tax_settings=st.session_state.get("tax_settings_obj"),
            zve_ohne_immo=float(st.session_state.get("zve_ohne_immo", 0.0)),
        )

    
        gesamt_afa = result["gesamt_afa"]
        afa_basis = result["afa_basis_neu"]
        st.session_state.afa_linear_basis_startjahr7 = result["afa_linear_basis_startjahr7"]
        steuerwirkung = result["steuerwirkung"]
        afa_linear_2 = result["afa_linear_2"]
        afa_linear_3 = result["afa_linear_3"]
        afa_degressiv = result["afa_degressiv"]
        sonder_afa = result["sonder_afa"]
        st.session_state.steuerwirkung_jahre[jahr] = steuerwirkung

        steuerlicher_gewinn = float(result.get("steuerlicher_gewinn", 0.0))
        zve_ohne = float(st.session_state.get("zve_ohne_immo", 0.0))
        zve_mit = zve_ohne + steuerlicher_gewinn
        marginal = float(result.get("marginal_rate", 0.0))  # z.B. 0.42

        progressionsdaten.append({
            "Jahr": jahr,
            "zvE ohne Immo": f"{zve_ohne:,.0f} €",
            "Steuerl. Immo-Effekt": f"{steuerlicher_gewinn:,.0f} €",
            "zvE mit Immo": f"{zve_mit:,.0f} €",
            "Grenzsteuer approx": f"{marginal*100:.1f} %",
            "Steuerwirkung (+/-)": f"{float(steuerwirkung):,.0f} €",
            "Immo-Steuersatz effektiv": (
                f"{(float(steuerwirkung)/abs(steuerlicher_gewinn)*100):.1f} %"
                if abs(steuerlicher_gewinn) > 1e-9 else ""
            ),
        })

        steuerdaten.append({
            "Jahr": jahr,
            "Mietertrag (brutto)": f"{mietertrag:,.0f} €",
            "Verwaltungskosten": f"{-verwaltungskosten:,.0f} €",
            "Zinsen gesamt": f"{-(zinsen_bank + zinsen_kfw):,.0f} €",
            "AfA gesamt": f"{-gesamt_afa:,.0f} €",
            "AfA linear 2%": f"{-afa_linear_2:,.0f} €" if afa_linear_2 else "",
            "AfA linear 3%": f"{-afa_linear_3:,.0f} €" if afa_linear_3 else "",
            "AfA degressiv 5%": f"{-afa_degressiv:,.0f} €" if afa_degressiv else "",
            "Sonder-AfA EH40": f"{-sonder_afa:,.0f} €" if sonder_afa else "",
            "Gewinn vor Steuer": f"{mietertrag - verwaltungskosten - zinsen_bank - zinsen_kfw - gesamt_afa:,.0f} €",
            "Steuer (+/-)": f"{steuerwirkung:,.0f} €"
        })

        tilgungsdaten.append({
            "Jahr": jahr,
            "Restschuld Bank Start": f"{rest_bank_anfang:,.0f} €",
            "Tilgung Bank": f"{-tilgung_bank:,.0f} €",
            "Restschuld Bank Ende": f"{restschuld_bank:,.0f} €",
            "Restschuld KfW Start": f"{rest_kfw_anfang:,.0f} €" if rest_kfw_anfang else "",
            "Tilgung KfW": f"{-tilgung_kfw:,.0f} €" if tilgung_kfw else "",
            "Restschuld KfW Ende": f"{restschuld_kfw:,.0f} €" if restschuld_kfw else "",
            "Restschuld Gesamt": f"{restschuld_bank + restschuld_kfw:,.0f} €"
        })

    st.markdown("#### 📈 Steuerberechnung pro Jahr")
    st.dataframe(pd.DataFrame(steuerdaten).set_index("Jahr"))

    st.markdown("#### 📊 Tilgungsübersicht pro Jahr (Bank & KfW)")
    st.dataframe(pd.DataFrame(tilgungsdaten).set_index("Jahr"))

    st.markdown("#### 🧾 Progressions-Check (Pfad 1)")
    st.dataframe(pd.DataFrame(progressionsdaten).set_index("Jahr"))


# Seite: 🧮 Baukostenprüfung §7b
elif seite == "🧮 Baukostenprüfung §7b":
    st.title("🧮 Baukostenprüfung nach §7b EStG (Effizienzhaus 40)")

    if not st.session_state.get("sonder_afa_effizienzhaus", False):
        st.warning("⚠️ Effizienzhaus 40 wurde nicht aktiviert – §7b EStG Prüfung nicht möglich.")
    else:
        st.subheader("🏗️ Flächenangaben nach DIN 277")

        # Eingaben für Flächen – Werte bleiben erhalten durch key=
        st.number_input("Wohnfläche der Wohnung (m²)", key="din_wohnflaeche", min_value=0.0)
        st.number_input("Kellerfläche (m²)", key="din_keller", min_value=0.0)
        st.number_input("Tiefgaragenstellplatz (m²)", key="din_tg", min_value=0.0)
        st.number_input("Fahrradraum (anteilig, m²)", key="din_fahrrad", min_value=0.0)
        st.number_input("Müllraum (anteilig, m²)", key="din_muell", min_value=0.0)
        st.number_input("Gemeinschaftsraum (anteilig, m²)", key="din_gemeinschaft", min_value=0.0)

        # Gesamtnutzfläche berechnen
        gesamtflaeche = (
            st.session_state.get("din_wohnflaeche", 0.0) +
            st.session_state.get("din_keller", 0.0) +
            st.session_state.get("din_tg", 0.0) +
            st.session_state.get("din_fahrrad", 0.0) +
            st.session_state.get("din_muell", 0.0) +
            st.session_state.get("din_gemeinschaft", 0.0)
        )
        st.session_state["gesamtflaeche_din277"] = gesamtflaeche
        st.markdown(f"📏 **Gesamtnutzfläche nach DIN 277:** **{gesamtflaeche:.2f} m²**")

        st.subheader("💰 Kaufpreis und Anteile")
        st.number_input("Kaufpreis gesamt (€)", key="din_kaufpreis_gesamt", min_value=0.0)
        st.number_input("Anteil Tiefgarage (€)", key="din_anteil_tg_euro", min_value=0.0)
        st.number_input("Anteil Grund und Boden (€)", key="din_anteil_grundstueck_euro", min_value=0.0)

        kaufpreis_gesamt = st.session_state.get("din_kaufpreis_gesamt", 0.0)
        anteil_tg = st.session_state.get("din_anteil_tg_euro", 0.0)
        anteil_grundstueck = st.session_state.get("din_anteil_grundstueck_euro", 0.0)

        # Baukosten pro m²
        gebaeudewert = kaufpreis_gesamt - anteil_grundstueck
        gebaeudewert_inkl_tg = gebaeudewert + anteil_tg
        baukosten_pro_m2 = gebaeudewert_inkl_tg / gesamtflaeche if gesamtflaeche > 0 else 0.0

        st.markdown(f"🏗️ **Baukosten je m²:** **{baukosten_pro_m2:,.2f} €**")

        if baukosten_pro_m2 > 5200:
            st.error("🔴 Die Baukosten je m² liegen über 5.200 € – §7b EStG-Kriterium **nicht erfüllt**.")
        else:
            st.success("🟢 Die Baukosten je m² liegen unter 5.200 € – §7b EStG-Kriterium **erfüllt**.")

        st.subheader("🔍 Optimale Grundstückswert-Berechnung")
        optimaler_grundstueckswert = kaufpreis_gesamt - (5200 * gesamtflaeche - anteil_tg)
        optimaler_grundstueckswert = max(0, optimaler_grundstueckswert)
        optimaler_anteil_prozent = 100 * optimaler_grundstueckswert / kaufpreis_gesamt if kaufpreis_gesamt > 0 else 0

        st.markdown(f"""
        💡 **Optimale Grundstücksaufteilung für 5.200 €/m²-Grenze:**

        - Maximaler Grundstückswert: **{optimaler_grundstueckswert:,.2f} €**
        - Das entspricht **{optimaler_anteil_prozent:.2f} %** des Kaufpreises
        """)

        if optimaler_grundstueckswert > anteil_grundstueck:
            st.warning("📌 Hinweis: Der aktuell eingegebene Grundstücksanteil ist *niedriger* als notwendig – keine §7b-Garantie.")
        elif optimaler_grundstueckswert < anteil_grundstueck:
            st.info("✅ Der Grundstückswert ist konservativ genug – gute Grundlage für die Steuerprüfung.")

        st.caption("ℹ️ Die DIN 277-Fläche sollte durch nachvollziehbare Unterlagen belegt werden (z. B. Bauunterlagen, Architekt).")


# Seite 4: Cashflow
elif seite == "💸 Cashflow":
    st.title("💸 Cashflow über 10 Jahre")

    if "herstellungskosten" not in st.session_state or "monatskaltmiete" not in st.session_state:
        st.warning("⚠️ Bitte zuerst die Seiten 'Basisdaten' und 'Finanzierung' ausfüllen.")
        st.stop()

    from modules.cashflow_berechnung import berechne_cashflows
    import pandas as pd

    # Defaults setzen
    st.session_state.setdefault("afa_satz_degressiv", 0.05)
    st.session_state.setdefault("afa_satz_linear", 0.03)
    st.session_state.setdefault("afa_degressiv_switch_year", 7)
    st.session_state.setdefault("afa_linear_basis_startjahr7", None)

    # Eingabe für Instandhaltungsrücklage
    st.session_state.instandhaltung_monatlich = st.number_input(
        "Instandhaltungsrücklage (Euro pro Monat)", 
        value=st.session_state.get("instandhaltung_monatlich", 60.0)
    )

    # ✅ Pfad 1 Defaults sicherstellen (falls Nutzer nicht auf 📈 Steuer war)
    st.session_state.setdefault("tax_year", 2026)
    st.session_state.setdefault("filing_status", "single")
    st.session_state.setdefault("soli_aktiv", True)
    st.session_state.setdefault("kist_aktiv", False)
    st.session_state.setdefault("kist_state", "BY")
    st.session_state.setdefault("zve_ohne_immo", 80000.0)

    if "tax_settings_obj" not in st.session_state or st.session_state["tax_settings_obj"] is None:
        st.session_state["tax_settings_obj"] = TaxSettings(
            year=st.session_state.tax_year,
            filing_status=st.session_state.filing_status,
            solidarity_surcharge=st.session_state.soli_aktiv,
            church_tax=st.session_state.kist_aktiv,
            church_tax_state=st.session_state.kist_state,
        )


    # 👉 zentrale Berechnung starten
    ergebnisse = berechne_cashflows(st.session_state)

    df_cashflow = pd.DataFrame(ergebnisse["cashflowdaten"]).set_index("Jahr")

    # Formatierung
    df_anzeige = df_cashflow.map(lambda x: f"{x:,.0f} €")

    st.markdown("#### 💸 Cashflow pro Jahr")
    st.dataframe(df_anzeige)


    st.markdown("#### 📈 Zusammenfassung")
    st.metric("Kumulierte Cashflows", f"{ergebnisse['kumuliert']:,.0f} €")
    st.metric("Gesparte Steuern", f"{ergebnisse['kumulierte_steuerersparnis']:,.0f} €")
    st.metric("Getilgt (Bank)", f"{ergebnisse['gesamt_tilgung_bank']:,.0f} €")
    if st.session_state.get("zweiter_kredit_aktiv", False):
        st.metric("Getilgt (KfW)", f"{ergebnisse['gesamt_tilgung_kfw']:,.0f} €")
    st.metric("Restschuld gesamt", f"{(ergebnisse['restschuld_bank'] + ergebnisse['restschuld_kfw']):,.0f} €")

#5  📊 Ergebnis
elif seite == "📊 Ergebnis":
    
        
    st.title("📊 Ergebnis")
    
    # --- Pflicht-Basisdaten prüfen (verhindert Absturz bei Direkteinstieg) ---
    if "herstellungskosten" not in st.session_state or "monatskaltmiete" not in st.session_state:
        st.warning("⚠️ Bitte zuerst die Seiten 'Basisdaten' und 'Finanzierung' ausfüllen.")
        st.stop()
    
    # --- Defaults absichern (falls Nutzer die Steuer-Seite übersprungen hat) ---
    st.session_state.setdefault("afa_satz_degressiv", 0.05)
    st.session_state.setdefault("afa_satz_linear", 0.03)
    st.session_state.setdefault("afa_degressiv_switch_year", 7)
    st.session_state.setdefault("afa_linear_basis_startjahr7", None)
    st.session_state.setdefault("afa_option", "5% (Neubau ab 01.10.23)")
    st.session_state.setdefault("sonder_afa_effizienzhaus", False)
    st.session_state.setdefault("verwaltungskosten_monatlich", 50.0)
    st.session_state.setdefault("instandhaltung_monatlich", 60.0)
    
    # --- Annahme: Wertsteigerung (steuert Verkaufspreis) ---
    wertsteigerung_pro_jahr = st.number_input(
        "Angenommene jährliche Wertsteigerung (%)", value=1.0
    ) / 100
    
    # --- Basis-Szenario einmal rechnen ---
    ergebnisse = berechne_cashflows(st.session_state)
    kumuliert = ergebnisse["kumuliert"]
    kumulierte_steuerersparnis = ergebnisse["kumulierte_steuerersparnis"]
    restschuld = ergebnisse["restschuld_bank"] + ergebnisse["restschuld_kfw"]
    gesamt_tilgung = ergebnisse["gesamt_tilgung_bank"] + ergebnisse["gesamt_tilgung_kfw"]
    
    ek = float(st.session_state.eigenkapital)
    kaufpreis = float(st.session_state.kaufpreis)
    monatskaltmiete = float(st.session_state.monatskaltmiete)
    
    verkaufspreis = kaufpreis * ((1 + wertsteigerung_pro_jahr) ** 10)
    gesamtgewinn = verkaufspreis - restschuld - ek + kumuliert
    
    # --- ETF-Szenario wählen (steuert die Vergleichskachel) ---
    etf_optionen = ["3% (defensiv)", "5% (konservativ)", "7% (offensiv)", "Eigener Wert"]
    st.session_state.etf_option = st.radio(
        "📈 ETF-Vergleich – erwartete Rendite p.a.:",
        etf_optionen,
        index=etf_optionen.index(st.session_state.get("etf_option", "5% (konservativ)")),
        horizontal=True,
        key="etf_option_radio_ergebnis",
    )
    if st.session_state.etf_option == "Eigener Wert":
        st.session_state.etf_rendite_eigen = st.number_input(
            "Eigene ETF-Rendite p.a. (%)",
            value=float(st.session_state.get("etf_rendite_eigen", 6.0)),
            step=0.5,
        )
        etf_rendite = st.session_state.etf_rendite_eigen / 100
    else:
        etf_rendite = float(st.session_state.etf_option[:1]) / 100

    etf_basis = ek


    if kumuliert < 0:
        zusatzmonatlich = abs(kumuliert) / (10 * 12)
        zusatzwert = sum(
            zusatzmonatlich * 12 * ((1 + etf_rendite) ** (10 - j)) for j in range(1, 11)
        )
    else:
        zusatzmonatlich, zusatzwert = 0.0, 0.0
    etf_wert_nach_steuer = (etf_basis * ((1 + etf_rendite) ** 10) + zusatzwert) * 0.75
    etf_gewinn_10 = etf_wert_nach_steuer - ek        # ETF als Gewinn (EK abgezogen)
    immo_vs_etf = gesamtgewinn - etf_gewinn_10       # faire Differenz (Gewinn vs. Gewinn)
    # --- Kern-Kennzahlen für das Cockpit ---
    cashflow_mtl_j1 = ergebnisse["cashflowdaten"][0]["Cashflow nach Steuer"] / 12.0
    cashflow_mtl_schnitt = (kumuliert / 10.0) / 12.0  # Ø über 10 Jahre, inkl. Steuerwirkung
    ek_rendite = (gesamtgewinn / ek) ** (1 / 10) - 1 if (ek > 0 and gesamtgewinn > 0) else None
    jahreskaltmiete = monatskaltmiete * 12.0
    bruttorendite = (jahreskaltmiete / kaufpreis) * 100 if kaufpreis else 0.0
    
    # =========================== COCKPIT (oben) ================================
    st.markdown("## 🎯 Auf einen Blick")
    
    # 1) Cashflow monatlich – Ø über 10 Jahre bestimmt die Ampel
    if cashflow_mtl_schnitt >= 0:
        cf_farbe, cf_sub = _GRUEN, "trägt sich im Schnitt selbst"
    elif cashflow_mtl_schnitt >= -150:
        cf_farbe, cf_sub = _GELB, "leichte Zuzahlung im Schnitt"
    else:
        cf_farbe, cf_sub = _ROT, "spürbare Zuzahlung im Schnitt"
    
    # 2) EK-Rendite p.a. (CAGR über 10 J)
    if ek_rendite is None:
        ekr_farbe, ekr_str, ekr_sub = _ROT, "negativ", "Verlust auf das Eigenkapital"
    elif ek_rendite >= 0.08:
        ekr_farbe, ekr_str, ekr_sub = _GRUEN, f"{ek_rendite*100:.1f} % p.a.", "starke Verzinsung"
    elif ek_rendite >= 0.05:
        ekr_farbe, ekr_str, ekr_sub = _GELB, f"{ek_rendite*100:.1f} % p.a.", "solide, Luft nach oben"
    else:
        ekr_farbe, ekr_str, ekr_sub = _ROT, f"{ek_rendite*100:.1f} % p.a.", "schwache Verzinsung"
    
    # 3) Immobilie vs. ETF
    if immo_vs_etf > 0:
        etf_farbe, etf_str, etf_sub = _GRUEN, f"+{immo_vs_etf:,.0f} €", "Immobilie schlägt den ETF"
    else:
        etf_farbe, etf_str, etf_sub = _ROT, f"{immo_vs_etf:,.0f} €", "ETF wäre besser gewesen"
    
    # 4) Bruttorendite (Markt-Einordnung, 1. Jahr)
    if bruttorendite < 3:
        br_farbe, br_sub = _ROT, "sehr gering (<3 %)"
    elif bruttorendite < 4:
        br_farbe, br_sub = _GELB, "eher gering (3–4 %)"
    elif bruttorendite < 5:
        br_farbe, br_sub = _GRUEN, "solide (4–5 %)"
    else:
        br_farbe, br_sub = _GRUEN, "attraktiv (>5 %)"
    
    cards = "".join([
        _kpi_card(
            "Cashflow / Monat",
            f"{cashflow_mtl_schnitt:,.0f} €",
            cf_farbe,
            f"Ø 10 J · 1. Jahr: {cashflow_mtl_j1:,.0f} €",
        ),
        _kpi_card("Eigenkapital-Rendite", ekr_str, ekr_farbe, ekr_sub),
        _kpi_card("Immobilie vs. ETF (10 J)", etf_str, etf_farbe, etf_sub),
        _kpi_card("Bruttorendite (1. Jahr)", f"{bruttorendite:.2f} %", br_farbe, br_sub),
    ])
    st.markdown(
        f'<div style="display:flex; gap:12px; flex-wrap:wrap;">{cards}</div>',
        unsafe_allow_html=True,
    )
    def _info_card(titel, wert_str):
        return (
            f'<div style="flex:1; min-width:150px; background:#1e222b; '
            f'border:1px solid #2c313c; border-radius:12px; padding:14px 16px;">'
            f'<div style="font-size:0.74rem; color:#8b94a3; text-transform:uppercase; '
            f'letter-spacing:0.03em;">{titel}</div>'
            f'<div style="font-size:1.35rem; font-weight:700; color:#e8ebf0; '
            f'margin-top:4px;">{wert_str}</div>'
            f'</div>'
        )

    info_cards = "".join([
        _info_card("Verkaufspreis (Jahr 10)", f"{verkaufspreis:,.0f} €"),
        _info_card("Gesamtgewinn", f"{gesamtgewinn:,.0f} €"),
        _info_card("Restschuld", f"{restschuld:,.0f} €"),
        _info_card("Getilgt", f"{gesamt_tilgung:,.0f} €"),
    ])
    st.markdown(
        f'<div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:10px;">'
        f'{info_cards}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "ℹ️ Steuerrückzahlungen und -nachzahlungen laufen der Kapitalanlage "
        "ca. 1 Jahr hinterher – der absolute Cashflow im 1. Jahr ist daher nur "
        "näherungsweise zu betrachten. Steuerwirkungen sind immer individuell und "
        "sollten durch einen Steuerberater geprüft werden."
    )
    
    # =========================== HEATMAP (Szenarien) ===========================
    st.markdown("## 🔥 Szenario-Analyse")
    st.markdown(
        "Wie robust ist dein Ergebnis, wenn **Miete** und **Wertsteigerung** anders "
        "laufen als geplant? Grün = gut, Rot = schwach."
    )

    metrik = st.radio(
        "Farbe zeigt:",
        ["EK-Rendite p.a.", "Gesamtgewinn (10 J)"],   # EK-Rendite ist jetzt Standard
        horizontal=True,
    )
    ist_gewinn = metrik.startswith("Gesamt")

    # Achsen: Miete/m² (um aktuellen Wert) × Wertsteigerung 0–4 %
    base_state = dict(st.session_state)
    m0 = float(st.session_state.miete_pro_m2)
    miete_werte = [round(m0 + d, 1) for d in (-2, -1, 0, 1, 2)]
    miete_werte = [m for m in miete_werte if m > 0]
    wert_werte = [0.0, 0.01, 0.02, 0.03, 0.04]

    daten = []
    for m in miete_werte:
        zeile = []
        for w in wert_werte:
            gewinn, rendite = _kpi_szenario(base_state, m, w)
            zeile.append(gewinn if ist_gewinn else rendite)
        daten.append(zeile)

    df_hm = pd.DataFrame(
        daten,
        index=[f"{m:.1f} €/m²" for m in miete_werte],
        columns=[f"+{w*100:.0f}% Wert" for w in wert_werte],
    )
    df_hm.index.name = "Miete/m²"

    # --- Aktuelles Basis-Szenario zum Markieren bestimmen ---
    base_miete = round(m0, 1)
    base_row = f"{base_miete:.1f} €/m²"
    base_w = min(wert_werte, key=lambda w: abs(w - wertsteigerung_pro_jahr))
    base_col = f"+{base_w*100:.0f}% Wert"

    # --- Farbskala: absolut (Rendite) vs. relativ (Gewinn) ---
    if ist_gewinn:
        _fin = df_hm.values.astype(float)
        _fin = _fin[np.isfinite(_fin)]
        _vmin, _vmax = (float(_fin.min()), float(_fin.max())) if _fin.size else (0.0, 1.0)
    else:
        _vmin, _vmax = 0.0, 0.10   # feste Skala: 0 % … 10 % p.a.

    def _style_hm(frame):
        styled = pd.DataFrame("", index=frame.index, columns=frame.columns)
        for i in frame.index:
            for c in frame.columns:
                css = _heatmap_farbe(frame.loc[i, c], _vmin, _vmax)
                if i == base_row and c == base_col:
                    css += " outline: 3px solid #ffffff; outline-offset: -3px;"
                styled.loc[i, c] = css
        return styled

    if ist_gewinn:
        _fmt = lambda v: "–" if pd.isna(v) else f"{v:,.0f} €"
    else:
        _fmt = lambda v: "–" if pd.isna(v) else f"{v*100:.1f} %"

    st.markdown(
        f"**{'Gesamtgewinn' if ist_gewinn else 'EK-Rendite p.a.'} nach 10 Jahren**  ·  "
        "Zeilen = **Miete pro m²**, Spalten = **jährliche Wertsteigerung**"
    )

    styler = (
        df_hm.style
        .apply(_style_hm, axis=None)
        .format(_fmt)
        .set_table_styles([
            {"selector": "th",
             "props": [("padding", "6px 10px"), ("text-align", "center"),
                       ("color", "#ddd"), ("font-weight", "600"),
                       ("background-color", "#1e1e1e")]},
            {"selector": "td",
             "props": [("padding", "8px 12px"), ("text-align", "right")]},
            {"selector": "table",
             "props": [("border-collapse", "collapse"), ("width", "100%"),
                       ("font-size", "0.95rem")]},
        ])
    )
    st.markdown(styler.to_html(), unsafe_allow_html=True)

    if ist_gewinn:
        st.caption(
            f"⬜ Weiß umrandet = dein aktuelles Szenario ({base_row}, "
            f"+{base_w*100:.0f}% Wertsteigerung).  ·  Farben hier **relativ** zur "
            "Tabelle (heller/dunkler), da „gut“ vom eingesetzten Eigenkapital abhängt."
        )
    else:
        st.caption(
            f"⬜ Weiß umrandet = dein aktuelles Szenario ({base_row}, "
            f"+{base_w*100:.0f}% Wertsteigerung).  ·  Feste Farbskala: "
            "unter ~5 % rötlich, ~5 % gelb, ab ~8 % grün."
        )

    st.caption(
        "Hinweis: Der monatliche Cashflow im 1. Jahr hängt NICHT von der "
        "Wertsteigerung ab – deshalb zeigt die Heatmap bewusst Gesamtgewinn "
        "bzw. EK-Rendite über 10 Jahre."
    )

    # =========================== VERLAUFS-CHART ===============================
    st.markdown("## 📈 Immobilie vs. ETF über 10 Jahre")

    ansicht = st.radio(
        "Ansicht:",
        ["Vermögen (absolut)", "Gewinn (Einsatz abgezogen)"],
        horizontal=True,
    )
    ist_vermoegen = ansicht.startswith("Vermögen")

    jahre, immo_verm, etf_verm, immo_gew, etf_gew = _verlauf_daten(
        dict(st.session_state), wertsteigerung_pro_jahr, etf_rendite
    )
    immo_linie = immo_verm if ist_vermoegen else immo_gew
    etf_linie = etf_verm if ist_vermoegen else etf_gew

    if ist_vermoegen:
        st.caption("Absolutes Vermögen am Jahresende – beide starten beim eingesetzten Eigenkapital.")
    else:
        st.caption("Gewinn nach Abzug des eingesetzten Eigenkapitals – beide starten bei 0 €.")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=jahre, y=immo_linie, name="Immobilie",
        mode="lines+markers", line=dict(color="#2e7d32", width=3),
        hovertemplate="Jahr %{x}<br>Immobilie: %{y:,.0f} €<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=jahre, y=etf_linie, name="ETF",
        mode="lines+markers", line=dict(color="#1565c0", width=3, dash="dot"),
        hovertemplate="Jahr %{x}<br>ETF: %{y:,.0f} €<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#888", width=1))
    fig.update_layout(
        template="plotly_dark", height=420,
        margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        xaxis_title="Jahr", yaxis_title=("Vermögen (€)" if ist_vermoegen else "Gewinn (€)"),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


    # Break-even-Hinweis: Ab wann liegt die Immobilie vorn?
    kreuzung = next((j for j, i, e in zip(jahre, immo_verm, etf_verm) if j > 0 and i >= e), None)
    if kreuzung:
        st.caption(f"🎯 Ab Jahr {kreuzung} liegt die Immobilie vor dem ETF.")
    else:
        st.caption("📉 In diesem Szenario bleibt der ETF über die 10 Jahre vorn.")
    
    # =========================== DETAILS (ausklappbar) =========================
    with st.expander("📋 Alle Detailwerte anzeigen"):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**Objekt & Miete**")
            st.metric("Kaufpreis", f"{kaufpreis:,.0f} €")
            st.metric("Nebenkosten", f"{st.session_state.nebenkosten:,.0f} €")
            st.metric("Wohnfläche", f"{st.session_state.wohnflaeche:,.1f} m²")
            st.metric("Kaltmiete mtl.", f"{monatskaltmiete:,.0f} €")
            st.metric("Kaufpreisfaktor", f"{(kaufpreis/jahreskaltmiete):.1f}" if jahreskaltmiete else "–")
        with c2:
            st.markdown("**Finanzierung**")
            st.metric("Eigenkapital", f"{ek:,.0f} €")
            st.metric("Getilgt gesamt", f"{gesamt_tilgung:,.0f} €")
            st.metric("Restschuld gesamt", f"{restschuld:,.0f} €")
            st.metric("Kumulierte Cashflows", f"{kumuliert:,.0f} €")
            st.metric("Gesparte Steuern", f"{kumulierte_steuerersparnis:,.0f} €")
        with c3:
            st.markdown("**Ergebnis & ETF**")
            st.metric("Verkaufspreis (Jahr 10)", f"{verkaufspreis:,.0f} €")
            st.metric("Gesamtgewinn", f"{gesamtgewinn:,.0f} €")
            st.metric("ETF-Wert nach Steuer", f"{etf_wert_nach_steuer:,.0f} €")
            st.metric("Immobilie − ETF", f"{immo_vs_etf:,.0f} €")

    # --- PDF-Report ---
    st.markdown("## 📄 PDF-Bericht")
    objekt_name = st.text_input(
        "Objektbezeichnung (erscheint im Bericht)",
        value=st.session_state.get("objekt_name_pdf", "Immobilie"),
        key="objekt_name_pdf",
    )

    # --- Objektdaten ---
    if st.session_state.get("mietmodell") == "Staffelmiete (€/Monat pro Jahr)":
        miete_wachstum_text = f"+{st.session_state.get('staffel_eur_monat', 0):.0f} EUR/Monat p.a. (Staffel)"
    else:
        miete_wachstum_text = f"{st.session_state.get('mietsteigerung_prozent', 0):.1f} % p.a."

    objekt_items = [
        ("Kaufpreis", f"{kaufpreis:,.0f} EUR"),
        ("Wohnfläche", f"{st.session_state.wohnflaeche:,.1f} m2"),
        ("Miete / m2", f"{st.session_state.miete_pro_m2:,.2f} EUR"),
        ("Kaltmiete mtl.", f"{monatskaltmiete:,.0f} EUR"),
        ("Nebenkosten", f"{st.session_state.nebenkosten:,.0f} EUR"),
        ("Bundesland", st.session_state.bundesland),
        ("Wertsteigerung p.a.", f"{wertsteigerung_pro_jahr*100:.1f} %"),
        ("Mietentwicklung", miete_wachstum_text),
    ]

    # --- Finanzierung ---
    kfw_aktiv = st.session_state.get("zweiter_kredit_aktiv", False)
    rate_bank_mtl = st.session_state.rate / 12.0

    finanzierung_items = [
        ("Eigenkapital", f"{ek:,.0f} EUR"),
        ("Bankdarlehen", f"{st.session_state.kreditbetrag:,.0f} EUR"),
        ("Zinssatz (Bank)", f"{st.session_state.zinssatz_anzeige:.2f} %"),
        ("Tilgungssatz (Bank)", f"{st.session_state.tilgungssatz_anzeige:.2f} %"),
        ("Monatl. Rate (Bank)", f"{rate_bank_mtl:,.0f} EUR"),
    ]
    if kfw_aktiv:
        rate_kfw_mtl = st.session_state.get("kfw_rate", 0.0) / 12.0
        finanzierung_items += [
            ("2. Darlehen (KfW)", f"{st.session_state.kfw_betrag:,.0f} EUR"),
            ("Zinssatz (KfW)", f"{st.session_state.kfw_zins_anzeige:.2f} %"),
            ("Tilgungssatz (KfW)", f"{st.session_state.kfw_tilgung_anzeige:.2f} %"),
            ("Monatl. Rate (KfW)", f"{rate_kfw_mtl:,.0f} EUR"),
        ]
    rate_gesamt_monatlich = (st.session_state.rate + st.session_state.get("kfw_rate", 0.0)) / 12.0
    finanzierung_items.append(("Monatl. Rate (gesamt)", f"{rate_gesamt_monatlich:,.0f} EUR"))

    # --- Steuerliche Annahmen ---
    veranlagung_text = (
        "Zusammenveranlagung" if st.session_state.get("filing_status") == "joint"
        else "Einzelveranlagung"
    )
    afa_kurz = st.session_state.get("afa_option", "–").split(" ")[0]
    if st.session_state.get("sonder_afa_effizienzhaus", False):
        afa_kurz += " + EH40"
    steuer_items = [
        ("Veranlagung", veranlagung_text),
        ("zvE ohne Immobilie", f"{st.session_state.get('zve_ohne_immo', 0):,.0f} EUR/Jahr"),
        ("Steuerjahr", str(st.session_state.get("tax_year", "–"))),
        ("AfA-Modell", afa_kurz),
        ("Solidaritätszuschlag", "berücksichtigt" if st.session_state.get("soli_aktiv") else "nicht berücksichtigt"),
        ("Kirchensteuer", "berücksichtigt" if st.session_state.get("kist_aktiv") else "nicht berücksichtigt"),
    ]

    # --- KPI-Kacheln (aus dem Cockpit oben) ---
    pdf_kpis = [
        {"titel": "Cashflow / Monat", "wert": f"{cashflow_mtl_schnitt:,.0f} EUR", "sub": cf_sub, "farbe": cf_farbe},
        {"titel": "Eigenkapital-Rendite", "wert": ekr_str, "sub": ekr_sub, "farbe": ekr_farbe},
        {"titel": "Immobilie vs. ETF", "wert": etf_str, "sub": etf_sub, "farbe": etf_farbe},
        {"titel": "Bruttorendite (1. Jahr)", "wert": f"{bruttorendite:.2f} %", "sub": br_sub, "farbe": br_farbe},
    ]

    # --- Ergebnis nach 10 Jahren ---
    ergebnis_items = [
        ("Verkaufspreis (Jahr 10)", f"{verkaufspreis:,.0f} EUR"),
        ("Gesamtgewinn", f"{gesamtgewinn:,.0f} EUR"),
        ("Restschuld", f"{restschuld:,.0f} EUR"),
        ("Getilgt (gesamt)", f"{gesamt_tilgung:,.0f} EUR"),
    ]

    pdf_bytes = _pdf_bericht(
        objekt_name=objekt_name,
        objekt_items=objekt_items,
        finanzierung_items=finanzierung_items,
        steuer_items=steuer_items,
        kpis=pdf_kpis,
        ergebnis_items=ergebnis_items,
        etf_label=st.session_state.etf_option,
        etf_rendite=etf_rendite,
        etf_wert_nach_steuer=etf_wert_nach_steuer,  
    )

    st.download_button(
        "📄 PDF-Bericht herunterladen",
        data=pdf_bytes,
        file_name=f"Bricklytics_{objekt_name.replace(' ', '_')}.pdf",
        mime="application/pdf",
    )

 
    # --- Export-Werte für andere Seiten (Vergleich etc.) ---
    st.session_state.restschuld = restschuld
    st.session_state.gesamt_tilgung = gesamt_tilgung
    st.session_state.kumuliert = kumuliert
    st.session_state.verkaufspreis = verkaufspreis
    st.session_state.gesamtgewinn = gesamtgewinn
    st.session_state.etf_wert_nach_steuer = etf_wert_nach_steuer
    st.session_state.etf_differenz = immo_vs_etf
    
#5  📊 Ergebnis
elif seite == "📊 Ergebnis (alte KPIs)":    
    st.title("📊 Ergebnis (alte KPIs)")

    if "herstellungskosten" not in st.session_state or "monatskaltmiete" not in st.session_state:
        st.warning("⚠️ Bitte zuerst die Seiten 'Basisdaten' und 'Finanzierung' ausfüllen.")
        st.stop()

    from modules.cashflow_berechnung import berechne_cashflows

    # Defaults setzen
    st.session_state.setdefault("afa_satz_degressiv", 0.05)
    st.session_state.setdefault("afa_satz_linear", 0.03)
    st.session_state.setdefault("afa_degressiv_switch_year", 7)
    st.session_state.setdefault("afa_linear_basis_startjahr7", None)

    # Annahmen für Verkaufswert
    wertsteigerung_pro_jahr = st.number_input(
        "Angenommene jährliche Wertsteigerung (%)", 
        value=1.0
    ) / 100

    verkaufspreis = st.session_state.kaufpreis * ((1 + wertsteigerung_pro_jahr) ** 10)

    # Berechnung starten
    ergebnisse = berechne_cashflows(st.session_state)

    kumuliert = ergebnisse["kumuliert"]
    kumulierte_steuerersparnis = ergebnisse["kumulierte_steuerersparnis"]
    restschuld = ergebnisse["restschuld_bank"] + ergebnisse["restschuld_kfw"]
    gesamt_tilgung = ergebnisse["gesamt_tilgung_bank"] + ergebnisse["gesamt_tilgung_kfw"]

    gesamtgewinn = verkaufspreis - restschuld - st.session_state.eigenkapital + kumuliert

    # 📊 Darstellung
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.subheader("📋 Basisdaten")
        st.metric("Kaufpreis", f"{st.session_state.kaufpreis:,.0f} €")
        st.metric("Nebenkosten", f"{st.session_state.nebenkosten:,.0f} €")
        st.metric("Wohnfläche", f"{st.session_state.wohnflaeche:,.1f} m²")
        st.metric("Miete pro m²", f"{st.session_state.miete_pro_m2:,.2f} €")
        st.metric("Kaltmiete mtl.", f"{st.session_state.monatskaltmiete:,.0f} €")
        st.metric("Instandhaltung (mtl.)", f"{st.session_state.instandhaltung_monatlich:,.0f} €")
        st.metric("Verwaltung (mtl.)", f"{st.session_state.verwaltungskosten_monatlich:,.0f} €")

    with col2:
        st.subheader("🏦 Tilgung & Schulden")
        st.metric("Getilgt (Bank)", f"{ergebnisse['gesamt_tilgung_bank']:,.0f} €")
        if st.session_state.get("zweiter_kredit_aktiv", False):
            st.metric("Getilgt (KfW)", f"{ergebnisse['gesamt_tilgung_kfw']:,.0f} €")
        st.metric("Gesamttilgung", f"{gesamt_tilgung:,.0f} €")
        st.metric("Restschuld gesamt", f"{restschuld:,.0f} €")
        st.metric("Zinssatz Bank", f"{st.session_state.zinssatz*100:.2f} %")
        st.metric("Tilgungssatz Bank", f"{st.session_state.tilgungssatz*100:.2f} %")
        if st.session_state.get("zweiter_kredit_aktiv", False):
            st.metric("Zinssatz KfW", f"{st.session_state.kfw_zins*100:.2f} %")
            st.metric("Tilgungssatz KfW", f"{st.session_state.kfw_tilgung*100:.2f} %")

        afa_text = ""
        if st.session_state.afa_option.startswith("5%"):
            afa_text = "5 % degressiv + Sonder-AfA (EH40)" if st.session_state.get("sonder_afa_effizienzhaus", False) else "5 % degressiv + 3 % linear ab Jahr 7"
        elif st.session_state.afa_option.startswith("3%"):
            afa_text = "3 % linear"
        elif st.session_state.afa_option.startswith("2%"):
            afa_text = "2 % linear"
        st.markdown(f"**AfA-Prämisse:** {afa_text}")

    with col3:
        st.subheader("📊 Cashflow & Gewinn")
        st.metric("Eigenkapital", f"{st.session_state.eigenkapital:,.0f} €")
        st.metric("Kumulierte Cashflows", f"{kumuliert:,.0f} €")
        st.metric("Gesparte Steuern", f"{kumulierte_steuerersparnis:,.0f} €")
        st.metric("Verkaufspreis (Jahr 10)", f"{verkaufspreis:,.0f} €")
        st.metric("Gesamtgewinn", f"{gesamtgewinn:,.0f} €")

        ek = st.session_state.eigenkapital
        if ek > 0 and gesamtgewinn > 0:
            # Durchschnittliche jährliche Wachstumsrate (CAGR)
            ek_rendite = (gesamtgewinn / ek) ** (1/10) - 1
            ek_rendite_prozent = ek_rendite * 100

            if ek_rendite > 0.08:
                st.success(f"🏅 EK-Wachstumsrate (10 J): {ek_rendite_prozent:.2f} % p.a.")
            elif ek_rendite > 0.05:
                st.warning(f"🟡 EK-Wachstumsrate (10 J): {ek_rendite_prozent:.2f} % p.a.")
            else:
                st.error(f"🔻 EK-Wachstumsrate (10 J): {ek_rendite_prozent:.2f} % p.a.")

            # Klassische jährliche Eigenkapitalrendite (letztes Jahr)
            klassische_ek_rendite = (gesamtgewinn / ek) * 100
            st.info(f"ℹ️ Klassische EK-Rendite: {klassische_ek_rendite:.2f} %")
        else:
            st.info("ℹ️ EK-Wachstumsrate (10 J) negativ.")

        # ➡️ Bruttorendite und Kaufpreisfaktor im ersten Jahr
        if (
            'kaufpreis' in st.session_state and
            'wohnflaeche' in st.session_state and
            'miete_pro_m2' in st.session_state
        ):
            # Monatskaltmiete berechnen
            monatskaltmiete = st.session_state.wohnflaeche * st.session_state.miete_pro_m2
            # Jahresnettokaltmiete
            jahresnettokaltmiete = monatskaltmiete * 12
            # Kaufpreis
            kaufpreis = st.session_state.kaufpreis

            # Bruttorendite und Kaufpreisfaktor
            bruttorendite = (jahresnettokaltmiete / kaufpreis) * 100
            kaufpreisfaktor = kaufpreis / jahresnettokaltmiete

            # Bruttorendite-Beurteilung
            if bruttorendite < 3:
                bruttorendite_text = "🚨 Sehr gering (unter 3 %)"
            elif bruttorendite < 4:
                bruttorendite_text = "⚠️ Eher gering (3–4 %)"
            elif bruttorendite < 5:
                bruttorendite_text = "✅ Solide (4–5 %)"
            elif bruttorendite < 6:
                bruttorendite_text = "✅ Gut (5–6 %)"
            else:
                bruttorendite_text = "🏅 Sehr attraktiv (über 6 %)"

            # Kaufpreisfaktor-Beurteilung
            if kaufpreisfaktor > 25:
                kpf_text = "🚨 Sehr teuer (über 25)"
            elif kaufpreisfaktor > 20:
                kpf_text = "⚠️ Eher teuer (20–25)"
            elif kaufpreisfaktor > 15:
                kpf_text = "✅ Solide (15–20)"
            else:
                kpf_text = "🏅 Sehr günstig (unter 15)"

            # Ausgabe mit Legenden direkt dabei
            st.info(f"🏠 **Bruttorendite (1. Jahr)**: {bruttorendite:.2f} % – {bruttorendite_text}")
            st.info(f"🏷️ **Kaufpreisfaktor (1. Jahr)**: {kaufpreisfaktor:.2f} – {kpf_text}")

    with col4:
        st.subheader("📈 ETF-Vergleich")

        etf_optionen = ["3% (defensiv)", "5% (konservativ)", "7% (offensiv)", "Eigener Wert"]
        st.session_state.etf_option = st.radio(
            "ETF-Szenario wählen:",
            etf_optionen,
            index=etf_optionen.index(st.session_state.get("etf_option", "5% (konservativ)")),
            horizontal=True,
            key="etf_option_radio"
        )

        if st.session_state.etf_option == "Eigener Wert":
            st.session_state.etf_rendite_eigen = st.number_input(
                "Eigene ETF-Rendite p.a. (%)",
                value=st.session_state.get("etf_rendite_eigen", 6.0)
            )
            etf_rendite = st.session_state.etf_rendite_eigen / 100
        else:
            etf_rendite = float(st.session_state.etf_option[:1]) / 100

        etf_basis = st.session_state.eigenkapital
        zusatzwert = 0
        zusatzmonatlich = 0

        if kumuliert < 0:
            zusatzmonatlich = abs(kumuliert) / (10 * 12)
            for jahr in range(1, 11):
                zusatzwert += zusatzmonatlich * 12 * ((1 + etf_rendite) ** (10 - jahr))

        etf_wert_vor_steuer = etf_basis * ((1 + etf_rendite) ** 10) + zusatzwert
        etf_wert_nach_steuer = etf_wert_vor_steuer * 0.75

        st.metric("Startkapital", f"{etf_basis:,.0f} €")
        st.metric("Sparrate mtl.", f"{zusatzmonatlich:,.0f} €")
        st.metric("ETF-Wert vor Steuer", f"{etf_wert_vor_steuer:,.0f} €")
        st.metric("ETF-Wert nach Steuer", f"{etf_wert_nach_steuer:,.0f} €")

        differenz = gesamtgewinn - etf_wert_nach_steuer
        if differenz > 0:
            st.success(f"🏠 Immobilie besser um {differenz:,.0f} €")
        else:
            st.warning(f"📉 ETF besser um {-differenz:,.0f} €")


   

    # Export-Werte für andere Seiten
    st.session_state.restschuld = restschuld
    st.session_state.gesamt_tilgung = gesamt_tilgung
    st.session_state.kumuliert = kumuliert
    st.session_state.verkaufspreis = verkaufspreis
    st.session_state.gesamtgewinn = gesamtgewinn
    st.session_state.etf_basis = etf_basis
    st.session_state.zusatzmonatlich = zusatzmonatlich
    st.session_state.etf_wert_vor_steuer = etf_wert_vor_steuer
    st.session_state.etf_wert_nach_steuer = etf_wert_nach_steuer
    st.session_state.etf_differenz = differenz


# 📁 Projektverwaltung – Download/Upload (cloud-tauglich)
elif seite == "💽 Projektverwaltung":
    st.title("💽 Projekt speichern & laden")
    st.caption(
        "Projekte werden als Datei auf deinem eigenen Gerät gespeichert – "
        "sie verlassen den Server nicht."
    )

    import json

    # --- SPEICHERN (als Download) ---
    st.subheader("💾 Aktuelles Projekt speichern")
    projektname = st.text_input(
        "🔖 Projektname",
        value=st.session_state.get("projektname", "Mein Projekt"),
    )

    # Nur JSON-kompatible Typen (verhindert, dass TaxSettings-Objekte stören)
    erlaubte_typen = (str, int, float, bool, list, dict)
    data = {
        k: v for k, v in st.session_state.items()
        if not k.startswith("_") and isinstance(v, erlaubte_typen)
    }
    data["projektname"] = projektname
    json_str = json.dumps(data, indent=4, ensure_ascii=False)

    st.download_button(
        "⬇️ Projekt herunterladen",
        data=json_str.encode("utf-8"),
        file_name=f"{projektname}.json",
        mime="application/json",
    )

    st.markdown("---")

    # --- LADEN (per Upload) ---
    st.subheader("📂 Gespeichertes Projekt laden")
    hochgeladen = st.file_uploader(
        "Projekt-Datei (.json) auswählen", type=["json"], key="projekt_upload"
    )
    if hochgeladen is not None:
        if st.button("📂 Dieses Projekt laden"):
            try:
                hochgeladen.seek(0)
                geladen = json.load(hochgeladen)

                # Login-Status über das Leeren hinweg retten
                auth = st.session_state.get("auth_ok", False)

                st.session_state.clear()
                for key, value in geladen.items():
                    st.session_state[key] = value
                 
                st.session_state["auth_ok"] = auth   # Login wiederherstellen
                st.success(f"✅ Projekt '{geladen.get('projektname', '?')}' geladen.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Fehler beim Laden: {e}")

# === 📚 Vergleichsseite ===
# === 📚 Vergleich – aus hochgeladenen Dateien ===
elif seite == "📚 Vergleich":
    import json
    from modules.vergleich import vergleichsuebersicht

    st.title("📚 Projektvergleich")
    st.caption("Lade mehrere gespeicherte Projekt-Dateien hoch, um sie zu vergleichen.")

    dateien = st.file_uploader(
        "Projekt-Dateien (.json) auswählen",
        type=["json"],
        accept_multiple_files=True,
        key="vergleich_upload",
    )

    if not dateien:
        st.info("Bitte mindestens ein Projekt hochladen.")
    else:
        ausgewaehlt = []
        for f in dateien:
            try:
                f.seek(0)
                projekt = json.load(f)
                projekt["projektname"] = projekt.get(
                    "projektname", f.name.replace(".json", "")
                )
                ausgewaehlt.append(projekt)
            except Exception as e:
                st.error(f"❌ {f.name}: {e}")

        if ausgewaehlt:
            df = vergleichsuebersicht(ausgewaehlt)
            st.markdown("### 📊 Vergleichstabelle")
            st.dataframe(df)

# Seite 8: Haftungsausschluss
elif seite == "⚖️ Disclaimer":
    st.title("⚖️ Disclaimer")

    st.markdown("""
    **Haftungsausschluss**

    Die Inhalte und Berechnungen auf dieser Website, insbesondere das Tool „Bricklytics“, dienen ausschließlich Informationszwecken.  
    Sie stellen **keine Finanz-, Steuer-, Anlage- oder Rechtsberatung** dar und können eine individuelle Beratung durch einen Experten nicht ersetzen.

    Obwohl die Informationen mit größtmöglicher Sorgfalt erstellt wurden, wird **keine Gewähr für Richtigkeit, Vollständigkeit oder Aktualität** übernommen.  
    Die Nutzung der bereitgestellten Informationen erfolgt auf **eigene Verantwortung**.

    Bricklytics und die Betreiber dieser Website übernehmen **keine Haftung** für direkte oder indirekte Schäden, die durch die Anwendung der hier bereitgestellten Inhalte entstehen könnten.

    Vor Entscheidungen über Immobilienkauf, Finanzierung oder Investitionen wird ausdrücklich empfohlen, eine **individuelle Beratung** durch qualifizierte Fachpersonen (z.B. Steuerberater, Finanzberater, Anwälte) in Anspruch zu nehmen.

    Alle Angaben gelten vorbehaltlich gesetzlicher Änderungen und Entwicklungen am Markt.  
    Eine Garantie für künftige Renditen, Steuerersparnisse oder andere finanzielle Ergebnisse wird ausdrücklich **nicht übernommen**.

    **Stand: April 2025**
    """)
