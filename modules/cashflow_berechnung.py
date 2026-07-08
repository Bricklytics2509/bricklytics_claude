from modules.afa_steuer import berechne_afa_und_steuer

def berechne_cashflows(st):
    # --- Bank-Sätze (niemals Mischzins/-tilgung verwenden)
    zinssatz_bank     = float(st.zinssatz)
    tilgungssatz_bank = float(st.tilgungssatz)

    # --- KfW (falls aktiv)
    zweiter_aktiv = bool(st.get("zweiter_kredit_aktiv", False))
    zinssatz_kfw     = float(st.kfw_zins)    if zweiter_aktiv else 0.0
    tilgungssatz_kfw = float(st.kfw_tilgung) if zweiter_aktiv else 0.0
    tfj = int(st.get("tilgungsfreie_jahre_kfw", 0)) if zweiter_aktiv else 0

    haupt_betrag = float(st.kreditbetrag)
    kfw_betrag   = float(st.kfw_betrag) if zweiter_aktiv else 0.0

    # konstante Anfangsannuitäten je Kredit
    jahresrate_bank_fix = haupt_betrag * (zinssatz_bank + tilgungssatz_bank)
    jahresrate_kfw_fix  = kfw_betrag   * (zinssatz_kfw  + tilgungssatz_kfw) if zweiter_aktiv else 0.0

    instandhaltung    = float(st.instandhaltung_monatlich) * 12.0
    verwaltungskosten = float(st.verwaltungskosten_monatlich) * 12.0
    kaltmiete_start   = float(st.monatskaltmiete) * 12.0

    restschuld_haupt = haupt_betrag
    restschuld_kfw   = kfw_betrag
    afa_basis        = float(st.herstellungskosten) + float(st.nebenkosten)

    cashflowdaten = []
    kumuliert = 0.0
    steuerwirkung_vorjahr = 0.0
    gesamt_tilgung_haupt = 0.0
    gesamt_tilgung_kfw = 0.0
    kumulierte_steuerersparnis = 0.0

    mietmodell = st.get("mietmodell", "Prozent p.a.")
    mietsteigerung = float(st.get("mietsteigerung", 0.01))
    staffel = float(st.get("staffel_eur_monat", 0.0))

    for jahr in range(1, 11):
        if mietmodell == "Staffelmiete (€/Monat pro Jahr)":
            mietertrag = (kaltmiete_start / 12.0 + staffel * (jahr - 1)) * 12.0
        else:
            mietertrag = kaltmiete_start * ((1.0 + mietsteigerung) ** (jahr - 1))
        
        # --- Bank ---
        zinsen_haupt  = restschuld_haupt * zinssatz_bank
        tilgung_haupt = max(jahresrate_bank_fix - zinsen_haupt, 0.0)
        restschuld_haupt = max(restschuld_haupt - tilgung_haupt, 0.0)
        gesamt_tilgung_haupt += tilgung_haupt

        # --- KfW ---
        zinsen_kfw = 0.0
        tilgung_kfw = 0.0
        if zweiter_aktiv and restschuld_kfw > 0.0:
            zinsen_kfw = restschuld_kfw * zinssatz_kfw
            if jahr <= tfj:
                tilgung_kfw = 0.0
            else:
                tilgung_kfw = max(jahresrate_kfw_fix - zinsen_kfw, 0.0)
                restschuld_kfw = max(restschuld_kfw - tilgung_kfw, 0.0)
                gesamt_tilgung_kfw += tilgung_kfw

        # --- AfA & Steuer
        result = berechne_afa_und_steuer(
            jahr=jahr,
            afa_basis=afa_basis,
            wohnflaeche=st.wohnflaeche,
            afa_option=st.afa_option,
            sonder_afa_effizienzhaus=st.sonder_afa_effizienzhaus,
            mietertrag=mietertrag,
            verwaltungskosten=verwaltungskosten,
            zinsen=(zinsen_haupt + zinsen_kfw),
            afa_satz_degressiv=st.afa_satz_degressiv,
            afa_satz_linear=st.afa_satz_linear,
            degressiv_switch_year=st.afa_degressiv_switch_year,
            afa_linear_basis_startjahr7=st.afa_linear_basis_startjahr7,
            bemessungsgrundlage=(float(st.herstellungskosten) + float(st.nebenkosten)),  # ✅ korrekt
            tax_settings=st.get("tax_settings_obj"),                                   # ✅ neu
            zve_ohne_immo=float(st.get("zve_ohne_immo", 0.0)),                         # ✅ neu
        )

        afa_basis = result["afa_basis_neu"]
        st.afa_linear_basis_startjahr7 = result["afa_linear_basis_startjahr7"]
        steuerwirkung = float(result["steuerwirkung"])
        if steuerwirkung > 0:
            kumulierte_steuerersparnis += steuerwirkung

        cashflow_vor_steuer = (
            mietertrag - verwaltungskosten - instandhaltung
            - zinsen_haupt - zinsen_kfw
            - tilgung_haupt - tilgung_kfw
        )
        cashflow_nach_steuer = cashflow_vor_steuer + steuerwirkung_vorjahr

        kumuliert += cashflow_nach_steuer
        steuerwirkung_vorjahr_alt = steuerwirkung_vorjahr
        steuerwirkung_vorjahr = steuerwirkung

        cashflowdaten.append({
            "Jahr": jahr,
            "Mietertrag": mietertrag,
            "Verwaltungskosten": -verwaltungskosten,
            "Instandhaltung": -instandhaltung,
            "Zinsen Bank": -zinsen_haupt,
            "Tilgung Bank": -tilgung_haupt,
            "Zinsen KfW": -zinsen_kfw if zinsen_kfw else 0.0,
            "Tilgung KfW": -tilgung_kfw if tilgung_kfw else 0.0,
            "Cashflow vor Steuer": cashflow_vor_steuer,
            "Steuerbetrachtung (Vorjahr)": steuerwirkung_vorjahr_alt,
            "Cashflow nach Steuer": cashflow_nach_steuer,
            "Kumuliert": kumuliert
        })

    return {
        "cashflowdaten": cashflowdaten,
        "kumuliert": kumuliert,
        "kumulierte_steuerersparnis": kumulierte_steuerersparnis,
        "gesamt_tilgung_bank": gesamt_tilgung_haupt,
        "gesamt_tilgung_kfw": gesamt_tilgung_kfw,
        "restschuld_bank": restschuld_haupt,
        "restschuld_kfw": restschuld_kfw
    }
