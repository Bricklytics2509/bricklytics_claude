# steuer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Dict, Any


FilingStatus = Literal["single", "joint"]  # joint = Zusammenveranlagung / Splitting
TaxYear = Literal[2025, 2026]


@dataclass(frozen=True)
class TaxSettings:
    year: TaxYear = 2026
    filing_status: FilingStatus = "single"

    # Zuschläge (optional)
    solidarity_surcharge: bool = True
    church_tax: bool = False
    church_tax_state: Literal[
        "BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV", "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH"
    ] = "BY"

    def church_tax_rate(self) -> float:
        # i.d.R. 8% in Bayern/Baden-Württemberg, sonst 9%
        return 0.08 if self.church_tax_state in ("BY", "BW") else 0.09


def _floor_euro(x: float) -> int:
    """Auf volle Euro abrunden."""
    return int(x // 1)


def _clamp_nonneg_euro(x: float) -> int:
    return _floor_euro(max(0.0, x))


# ----------------------------
# Einkommensteuer §32a EStG
# ----------------------------

def einkommensteuer_grundtarif_2025(zve: float) -> int:
    """
    Tarifliche ESt (Grundtarif) für VZ 2025.
    Parameter gem. BMF LStH 2025 (Tarif nach §32a EStG). :contentReference[oaicite:4]{index=4}
    """
    x = _clamp_nonneg_euro(zve)

    # Eckwerte 2025:
    # 1) bis 12.096: 0
    # 2) 12.097 - 17.443: (932,30*y + 1.400)*y, y=(x-12.096)/10.000
    # 3) 17.444 - 68.480: (176,64*z + 2.397)*z + 1.015,13, z=(x-17.443)/10.000
    # 4) 68.481 - 277.825: 0,42*x - 10.911,92
    # 5) ab 277.826: 0,45*x - 19.246,67
    if x <= 12096:
        est = 0.0
    elif x <= 17443:
        y = (x - 12096) / 10000.0
        est = (932.30 * y + 1400.0) * y
    elif x <= 68480:
        z = (x - 17443) / 10000.0
        est = (176.64 * z + 2397.0) * z + 1015.13
    elif x <= 277825:
        est = 0.42 * x - 10911.92
    else:
        est = 0.45 * x - 19246.67

    return _clamp_nonneg_euro(est)


def einkommensteuer_grundtarif_2026(zve: float) -> int:
    """
    Tarifliche ESt (Grundtarif) für VZ 2026.
    Parameter gem. §32a EStG ab VZ 2026. :contentReference[oaicite:5]{index=5}
    """
    x = _clamp_nonneg_euro(zve)

    # Eckwerte 2026:
    # 1) bis 12.348: 0
    # 2) 12.349 - 17.799: (914,51*y + 1.400)*y, y=(x-12.348)/10.000
    # 3) 17.800 - 69.878: (173,10*z + 2.397)*z + 1.034,87, z=(x-17.799)/10.000
    # 4) 69.879 - 277.825: 0,42*x - 11.135,63
    # 5) ab 277.826: 0,45*x - 19.246,67
    if x <= 12348:
        est = 0.0
    elif x <= 17799:
        y = (x - 12348) / 10000.0
        est = (914.51 * y + 1400.0) * y
    elif x <= 69878:
        z = (x - 17799) / 10000.0
        est = (173.10 * z + 2397.0) * z + 1034.87
    elif x <= 277825:
        est = 0.42 * x - 11135.63
    else:
        est = 0.45 * x - 19246.67

    return _clamp_nonneg_euro(est)


def einkommensteuer_grundtarif(zve: float, year: TaxYear) -> int:
    if year == 2025:
        return einkommensteuer_grundtarif_2025(zve)
    if year == 2026:
        return einkommensteuer_grundtarif_2026(zve)
    raise ValueError(f"Year not implemented: {year}")


def einkommensteuer_splitting(zve: float, year: TaxYear) -> int:
    """
    Splittingverfahren: ESt = 2 * ESt( (zvE)/2 )
    (gilt für §32a i.V.m. Splittingtarif – praktisch Standardformel).
    """
    half = max(0.0, zve) / 2.0
    return 2 * einkommensteuer_grundtarif(half, year)


def einkommensteuer(zve: float, settings: TaxSettings) -> int:
    """Zentrale ESt-Funktion (Grundtarif oder Splitting)."""
    if settings.filing_status == "joint":
        return einkommensteuer_splitting(zve, settings.year)
    return einkommensteuer_grundtarif(zve, settings.year)


# ----------------------------
# Solidaritätszuschlag (Soli)
# ----------------------------

def soli_freigrenze_est(year: TaxYear, filing_status: FilingStatus) -> int:
    """
    Freigrenze bezieht sich auf die (tarifliche) Einkommensteuer (Bemessungsgrundlage).
    Werte 2025/2026: singles 19.950/20.350; joint doppelt. :contentReference[oaicite:6]{index=6}
    """
    if year == 2025:
        base = 19950
    elif year == 2026:
        base = 20350
    else:
        raise ValueError(f"Year not implemented: {year}")

    return base if filing_status == "single" else 2 * base


def soli(est: int, settings: TaxSettings) -> int:
    """
    Soli-Logik (annual, stark vereinfacht aber korrekt nach Grundprinzip):
      - Wenn ESt <= Freigrenze => 0
      - Sonst: Soli = min(5,5% * ESt, 11,9% * (ESt - Freigrenze))
    11,9%-Regel: LStH Anhang Soli. :contentReference[oaicite:7]{index=7}
    """
    if not settings.solidarity_surcharge:
        return 0

    est_i = max(0, int(est))
    fg = soli_freigrenze_est(settings.year, settings.filing_status)

    if est_i <= fg:
        return 0

    full = 0.055 * est_i
    mild = 0.119 * (est_i - fg)
    return _clamp_nonneg_euro(min(full, mild))


# ----------------------------
# Kirchensteuer
# ----------------------------

def kirchensteuer(est: int, settings: TaxSettings) -> int:
    if not settings.church_tax:
        return 0
    rate = settings.church_tax_rate()
    return _clamp_nonneg_euro(max(0, est) * rate)


# ----------------------------
# Gesamtsteuer + Pfad 1
# ----------------------------

def gesamtsteuer(zve: float, settings: TaxSettings) -> Dict[str, int]:
    """
    Breakdown:
      - zvE (abgerundet)
      - ESt tariflich
      - Soli
      - KiSt
      - Gesamt
    """
    zve_eur = _clamp_nonneg_euro(zve)
    est = einkommensteuer(zve_eur, settings)
    sol = soli(est, settings)
    kist = kirchensteuer(est, settings)
    total = est + sol + kist

    return {
        "zve": zve_eur,
        "est": est,
        "soli": sol,
        "kist": kist,
        "total_tax": total,
    }


def marginal_rate_approx(zve: float, settings: TaxSettings, step_eur: int = 1) -> float:
    """
    Numerische Grenzsteuer-Approx: (T(zve+step)-T(zve))/step.
    Achtung: wegen Rundungen bei kleinen steps "stufig".
    """
    step = max(1, int(step_eur))
    t0 = gesamtsteuer(zve, settings)["total_tax"]
    t1 = gesamtsteuer(zve + step, settings)["total_tax"]
    return (t1 - t0) / float(step)


def steuerwirkung_pfad1(
    zve_ohne_immo: float,
    immo_steuerlicher_effekt: float,
    settings: TaxSettings,
) -> Dict[str, Any]:
    """
    Pfad 1:
      - zvE ohne Immo
      - zvE mit Immo = zvE_ohne + (steuerlicher Immo-Effekt)
      - Steuerwirkung = Steuer_ohne - Steuer_mit
        (positiv = Entlastung, negativ = Mehrsteuer)
    """
    without = gesamtsteuer(zve_ohne_immo, settings)
    with_ = gesamtsteuer(zve_ohne_immo + immo_steuerlicher_effekt, settings)
    effect = without["total_tax"] - with_["total_tax"]

    mr = marginal_rate_approx(zve_ohne_immo, settings, step_eur=1)

    avg_without = without["total_tax"] / max(1, without["zve"])
    avg_with = with_["total_tax"] / max(1, with_["zve"])

    return {
        "without": without,
        "with": with_,
        "steuerwirkung": effect,
        "marginal_rate_approx": mr,
        "avg_tax_rate_without": avg_without,
        "avg_tax_rate_with": avg_with,
        "inputs": {
            "zve_ohne_immo": _clamp_nonneg_euro(zve_ohne_immo),
            "immo_steuerlicher_effekt": float(immo_steuerlicher_effekt),
            "year": settings.year,
            "filing_status": settings.filing_status,
            "soli": settings.solidarity_surcharge,
            "church_tax": settings.church_tax,
            "church_tax_state": settings.church_tax_state,
        },
    }


# ----------------------------
# Mini-Selbsttest (optional)
# ----------------------------

if __name__ == "__main__":
    # Quick sanity checks (kein offizieller Steuerrechner-Ersatz)
    s = TaxSettings(year=2026, filing_status="single", solidarity_surcharge=True, church_tax=False)
    demo = steuerwirkung_pfad1(
        zve_ohne_immo=90000,
        immo_steuerlicher_effekt=-5000,  # Verlust => Steuerentlastung
        settings=s,
    )
    print(demo)