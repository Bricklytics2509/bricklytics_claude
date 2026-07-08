from modules.cashflow_berechnung import berechne_cashflows

def ki_empfehlung(st, ergebnisse, gesamtgewinn):
    ek = st.eigenkapital
    ziel_rendite = 0.05  # Ziel: mind. 5 % p.a.
    kaufpreis_alt = st.kaufpreis
    miete_alt = st.monatskaltmiete
    cashflow = ergebnisse["kumuliert"]

    # Rendite berechnen
    rendite_ist = (gesamtgewinn / ek) ** (1 / 10) - 1 if ek > 0 else None

    if rendite_ist is None:
        return "❗ Keine Berechnung möglich: Eigenkapital ist 0 oder negativ."

    # Grundbewertung
    if rendite_ist > 0.07 and cashflow > 0:
        text = f"🟢 Solides Investment: EK-Rendite liegt bei {rendite_ist*100:.2f} % p.a., Cashflow ist positiv.\n\n"
    elif rendite_ist > 0.04:
        text = f"🟡 Grenzfall: Die Rendite liegt bei {rendite_ist*100:.2f} %. Verbesserungen möglich.\n\n"
    else:
        text = f"🔴 Unrentabel: Die EK-Rendite liegt bei nur {rendite_ist*100:.2f} %. Cashflow negativ oder gering.\n\n"

    # ➕ Schwellenwert: erforderliche Miete/m²
    neue_miete = miete_alt
    for _ in range(30):
        neue_miete += 0.5
        st.monatskaltmiete = neue_miete
        test_result = berechne_cashflows(st)
        test_gewinn = (
            st.kaufpreis * ((1 + 0.01) ** 10)
            - test_result["restschuld_bank"]
            - test_result["restschuld_kfw"]
            - ek
            + test_result["kumuliert"]
        )
        test_rendite = (test_gewinn / ek) ** (1 / 10) - 1
        if test_rendite >= ziel_rendite:
            break
    st.monatskaltmiete = miete_alt  # Reset

    # ➖ Schwellenwert: maximaler Kaufpreis
    neuer_kp = kaufpreis_alt
    for _ in range(40):
        neuer_kp -= 5000
        st.kaufpreis = neuer_kp
        test_result = berechne_cashflows(st)
        test_gewinn = (
            neuer_kp * ((1 + 0.01) ** 10)
            - test_result["restschuld_bank"]
            - test_result["restschuld_kfw"]
            - ek
            + test_result["kumuliert"]
        )
        test_rendite = (test_gewinn / ek) ** (1 / 10) - 1
        if test_rendite >= ziel_rendite:
            break
    st.kaufpreis = kaufpreis_alt  # Reset

    # Ausgabe
    text += "📌 Optimierung:\n"
    text += f"- Ab **{neue_miete:,.2f} €** Monatskaltmiete (~ {neue_miete / st.wohnflaeche:,.2f} €/m²) wäre EK-Rendite ≥ 5 %.\n"
    text += f"- Alternativ müsste der Kaufpreis auf **unter {neuer_kp:,.0f} €** sinken."

    return text
