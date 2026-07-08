from modules.afa_steuer import berechne_afa_und_steuer

def berechne_cashflows(st):
    zinssatz = st.mischzins if st.get("zweiter_kredit_aktiv", False) else st.zinssatz
    tilgungssatz = st.mischtilgung if st.get("zweiter_kredit_aktiv", False) else st.tilgungssatz

    haupt_betrag = st.kreditbetrag
    kfw_betrag = st.kfw_betrag if st.get("zweiter_kredit_aktiv", False) else 0.0
    tilgungsfreie_jahre_kfw = int(st.get("tilgungsfreie_jahre_kfw", 0))  # Wert aus UI holen, sicherstellen dass es ein Integer ist

    zinssatz_kfw = st.kfw_zins
    tilgungssatz_kfw = st.kfw_tilgung

    jahresrate_haupt = haupt_betrag * (zinssatz + tilgungssatz)
    jahresrate_kfw = kfw_betrag * (zinssatz_kfw + tilgungssatz_kfw)

    instandhaltung = st.instandhaltung_monatlich * 12
    verwaltungskosten = st.verwaltungskosten_monatlich * 12
    kaltmiete_start = st.monatskaltmiete * 12

    restschuld_haupt = haupt_betrag
    restschuld_kfw = kfw_betrag
    afa_basis = st.herstellungskosten + st.nebenkosten

    cashflowdaten = []
    kumuliert = 0
    steuerwirkung_vorjahr = 0
    gesamt_tilgung_haupt = 0
    gesamt_tilgung_kfw = 0
    kumulierte_steuerersparnis = 0

    for jahr in range(1, 11):
        mietertrag = kaltmiete_start * ((1 + 0.01) ** (jahr - 1))

        # Bankkredit Berechnung
        zinsen_haupt = restschuld_haupt * zinssatz
        tilgung_haupt = jahresrate_haupt - zinsen_haupt
        restschuld_haupt -= tilgung_haupt
        gesamt_tilgung_haupt += tilgung_haupt

        # KfW-Kredit Berechnung mit tilgungsfreien Jahren
        if st.get("zweiter_kredit_aktiv", False) and kfw_betrag > 0:
            zinsen_kfw = restschuld_kfw * zinssatz_kfw

            if jahr <= tilgungsfreie_jahre_kfw:
                tilgung_kfw = 0.0
                # In tilgungsfreien Jahren wird nur der Zins gezahlt, Restschuld bleibt gleich
            else:
                tilgung_kfw = jahresrate_kfw - zinsen_kfw
                restschuld_kfw -= tilgung_kfw
                gesamt_tilgung_kfw += tilgung_kfw
        else:
            zinsen_kfw = 0.0
            tilgung_kfw = 0.0

        # Afa und Steuer berechnen
        result = berechne_afa_und_steuer(
            jahr=jahr,
            afa_basis=afa_basis,
            wohnflaeche=st.wohnflaeche,
            afa_option=st.afa_option,
            sonder_afa_effizienzhaus=st.sonder_afa_effizienzhaus,
            mietertrag=mietertrag,
            verwaltungskosten=verwaltungskosten,
            zinsen=zinsen_haupt + zinsen_kfw,
            afa_satz_degressiv=st.afa_satz_degressiv,
            afa_satz_linear=st.afa_satz_linear,
            degressiv_switch_year=st.afa_degressiv_switch_year,
            afa_linear_basis_startjahr7=st.afa_linear_basis_startjahr7,
            bemessungsgrundlage=afa_basis
        )

        afa_basis = result["afa_basis_neu"]
        st.afa_linear_basis_startjahr7 = result["afa_linear_basis_startjahr7"]
        steuerwirkung = result["steuerwirkung"]
        kumulierte_steuerersparnis += max(steuerwirkung, 0)

        cashflow_vor_steuer = (
            mietertrag - verwaltungskosten - instandhaltung - zinsen_haupt - zinsen_kfw - tilgung_haupt - tilgung_kfw
        )
        cashflow_nach_steuer = cashflow_vor_steuer + steuerwirkung_vorjahr
        steuerwirkung_vorjahr_alt = steuerwirkung_vorjahr
        steuerwirkung_vorjahr = steuerwirkung
        kumuliert += cashflow_nach_steuer

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
