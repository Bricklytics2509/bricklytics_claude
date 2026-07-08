# modules/afa_steuer.py

from typing import Optional, Any, Dict

from modules.steuer import TaxSettings, steuerwirkung_pfad1


# 📦 Gemeinsame AfA- und Steuerlogik für alle Abschnitte
def berechne_afa_und_steuer(
    jahr: int,
    afa_basis: float,
    wohnflaeche: float,
    afa_option: str,
    sonder_afa_effizienzhaus: bool,
    mietertrag: float,
    verwaltungskosten: float,
    zinsen: float,
    # neue Inputs für Progression (Pfad 1)
    tax_settings: Optional[TaxSettings] = None,
    zve_ohne_immo: float = 0.0,
    # AfA-Parameter wie bisher
    afa_satz_degressiv: float = 0.05,
    afa_satz_linear: float = 0.03,
    degressiv_switch_year: int = 7,
    afa_linear_basis_startjahr7: Optional[float] = None,
    bemessungsgrundlage: Optional[float] = None
) -> Dict[str, Any]:
    """
    Gibt zurück:
      - gesamt_afa, neue afa_basis, afa_linear_basis_startjahr7
      - steuerlicher_gewinn (für Pfad 1 relevant)
      - steuerwirkung
      - optional: marginal_rate (wenn Pfad 1 aktiv)
    """

    afa_degressiv = 0.0
    sonder_afa = 0.0
    afa_linear_2 = 0.0
    afa_linear_3 = 0.0
    gesamt_afa = 0.0

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
            # safety: falls Basis aus irgendeinem Grund nicht gesetzt wurde
            if afa_linear_basis_startjahr7 is None:
                afa_linear_basis_startjahr7 = afa_basis
            afa_linear_3 = afa_linear_basis_startjahr7 * afa_satz_linear
            gesamt_afa = afa_linear_3

    # Linear 3%
    elif afa_option.startswith("3%"):
        if bemessungsgrundlage is None:
            raise ValueError("bemessungsgrundlage muss gesetzt sein bei linear 3%")
        afa_linear_3 = bemessungsgrundlage * 0.03
        gesamt_afa = afa_linear_3

    # Linear 2%
    elif afa_option.startswith("2%"):
        if bemessungsgrundlage is None:
            raise ValueError("bemessungsgrundlage muss gesetzt sein bei linear 2%")
        afa_linear_2 = bemessungsgrundlage * 0.02
        gesamt_afa = afa_linear_2

    # Steuerlicher Gewinn/Verlust (EÜR-Logik für Vermietung)
    steuerlicher_gewinn = mietertrag - verwaltungskosten - zinsen - gesamt_afa

    # --- Steuerwirkung ---
    # Wenn Pfad 1 aktiv: echte Progression (ESt + Soli + KiSt)
    # Sonst fallback: wie bisher pauschal 42%
    if tax_settings is not None:
        res = steuerwirkung_pfad1(
            zve_ohne_immo=float(zve_ohne_immo),
            immo_steuerlicher_effekt=float(steuerlicher_gewinn),
            settings=tax_settings,
        )
        steuerwirkung = float(res["steuerwirkung"])
        marginal_rate = float(res["marginal_rate_approx"])
    else:
        steuerwirkung = -float(steuerlicher_gewinn) * 0.42
        marginal_rate = 0.42

    return {
        "gesamt_afa": gesamt_afa,
        "afa_basis_neu": afa_basis,
        "afa_linear_basis_startjahr7": afa_linear_basis_startjahr7,
        "steuerlicher_gewinn": steuerlicher_gewinn,
        "steuerwirkung": steuerwirkung,
        "marginal_rate": marginal_rate,
        "afa_linear_2": afa_linear_2,
        "afa_linear_3": afa_linear_3,
        "afa_degressiv": afa_degressiv,
        "sonder_afa": sonder_afa,
    }