# 📦 Gemeinsame AfA- und Steuerlogik für alle Abschnitte

def berechne_afa_und_steuer(
    jahr,
    afa_basis,
    wohnflaeche,
    afa_option,
    sonder_afa_effizienzhaus,
    mietertrag,
    verwaltungskosten,
    zinsen,
    afa_satz_degressiv=0.05,
    afa_satz_linear=0.03,
    degressiv_switch_year=7,
    afa_linear_basis_startjahr7=None,
    bemessungsgrundlage=None
):
    """
    Gibt zurück: gesamt_afa, neue_afa_basis, afa_linear_basis_startjahr7, steuerwirkung
    """
    afa_degressiv = 0
    sonder_afa = 0
    afa_linear_2 = 0
    afa_linear_3 = 0
    gesamt_afa = 0

    # Sonder-AfA + degressive AfA
    if sonder_afa_effizienzhaus:
        if jahr <= 4:
            sonder_afa = wohnflaeche * 4000 * 0.05
            afa_degressiv = afa_basis * 0.05
            afa_basis -= afa_degressiv
            gesamt_afa = sonder_afa + afa_degressiv
        elif jahr <= 6:
            afa_degressiv = afa_basis * 0.05
            afa_basis -= afa_degressiv
            gesamt_afa = afa_degressiv
        else:
            if afa_linear_basis_startjahr7 is None:
                afa_linear_basis_startjahr7 = afa_basis
            afa_linear_3 = afa_linear_basis_startjahr7 * 0.03
            gesamt_afa = afa_linear_3

    # Degressiv 5%, danach linear
    elif afa_option.startswith("5%"):
        if jahr < degressiv_switch_year:
            afa_degressiv = afa_basis * afa_satz_degressiv
            afa_basis -= afa_degressiv
            gesamt_afa = afa_degressiv
            if jahr == degressiv_switch_year - 1:
                afa_linear_basis_startjahr7 = afa_basis
        else:
            afa_linear_3 = afa_linear_basis_startjahr7 * afa_satz_linear
            gesamt_afa = afa_linear_3

    # Linear 3%
    elif afa_option.startswith("3%"):
        afa_linear_3 = bemessungsgrundlage * 0.03
        gesamt_afa = afa_linear_3

    # Linear 2%
    elif afa_option.startswith("2%"):
        afa_linear_2 = bemessungsgrundlage * 0.02
        gesamt_afa = afa_linear_2

    steuergewinn = mietertrag - verwaltungskosten - zinsen - gesamt_afa
    steuerwirkung = -steuergewinn * 0.42

    return {
        "gesamt_afa": gesamt_afa,
        "afa_basis_neu": afa_basis,
        "afa_linear_basis_startjahr7": afa_linear_basis_startjahr7,
        "steuerwirkung": steuerwirkung,
        "afa_linear_2": afa_linear_2,
        "afa_linear_3": afa_linear_3,
        "afa_degressiv": afa_degressiv,
        "sonder_afa": sonder_afa
    }

# 🔁 Beispielaufruf in Schleife:
# result = berechne_afa_und_steuer(...)
