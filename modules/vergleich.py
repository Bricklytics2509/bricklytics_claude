import pandas as pd

def vergleichsuebersicht(projekte: list[dict]) -> pd.DataFrame:
    daten = []

    for projekt in projekte:
        name = projekt.get("projektname", "Projekt")
        ek = projekt.get("eigenkapital", 0)
        gewinn = projekt.get("gesamtgewinn", 0)
        rendite = (gewinn / ek) ** (1 / 10) - 1 if ek > 0 else None

        daten.append({
            "Projekt": name,
            "EK-Rendite (p.a.)": f"{rendite*100:.2f} %" if rendite else "n/a",
            "Cashflow gesamt": f"{projekt.get('kumuliert', 0):,.0f} €",
            "Gesparte Steuern": f"{projekt.get('kumulierte_steuerersparnis', 0):,.0f} €",
            "Verkaufspreis": f"{projekt.get('verkaufspreis', 0):,.0f} €",
            "Gesamtgewinn": f"{gewinn:,.0f} €"
        })

    return pd.DataFrame(daten)
