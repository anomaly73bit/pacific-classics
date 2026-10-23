"""Key facts of an ad, extracted from the seller's text (DE/CZ/SK/NL/FR/ES/EN/IT) and written in Italian.

Instead of showing the original description, the car sheet lists what matters to a buyer:
service history, owners, inspection, accident/rust statements, equipment, VAT, negotiable price…
"""
from __future__ import annotations

import re

R = re.compile
FACTS: list[tuple[re.Pattern, str]] = [
    (R(r"scheckheft|serviceheft|servisn[íi] kn[íi][žz]k|onderhoudsboek|historique d.entretien|libro de mantenimiento|service ?history|libretto tagliandi|lückenlos"), "Tagliandi documentati"),
    (R(r"\b1\.\s?hand|erstbesitz|erste hand|first owner|1\. majitel|prv[ýy] majite|eerste eigenaar|première main|primera mano|primo proprietario|unico proprietario"), "Primo proprietario"),
    (R(r"unfallfrei|accident[- ]?free|nehavarov|nebourané|schadevrij|jamais accident|sin accidentes|mai incidentat"), "Mai incidentata (dichiarato dal venditore)"),
    (R(r"rostfrei|kein rost|ohne rost|rust[- ]?free|bez koroze|bez hrdze|roestvrij|sans rouille|sin óxido|senza ruggine"), "Senza ruggine (dichiarato)"),
    (R(r"garagen(wagen|fahrzeug)|garagiert|garaged|gar[áa][žz]ov|altijd binnen|toujours au garage|garaje|sempre in garage"), "Tenuta in garage"),
    (R(r"h-?kennzeichen|h-?zulassung|oldtimer-?zulassung|veter[áa]n|youngtimer-?kenteken|carte grise collection|targa oro|certificato asi|\bcrs\b"), "Già con documenti da veicolo storico"),
    (R(r"nichtraucher|ne?kuřácké|nefaj[čc]iar|niet-?roker|non[- ]?fumeur|no fumador|non fumatore"), "Non fumatori"),
    (R(r"originalzustand|originallack|unverbastelt|unverbaut|p[ůu]vodn[íi] stav|origin[áa]ln[íi] stav|originele staat|état d.origine|estado original|stato originale|tutta originale"), "Originale, non modificata"),
    (R(r"restauriert|restauration|renoviert|renovov|restaurov|gerestaureerd|restaurée?|restaurad|restaurat"), "Restaurata"),
    (R(r"motor (neu|überholt|revidiert|generalüberholt)|generálka motoru|generálna oprava motora|motor gereviseerd|moteur refait|motor reconstruido|motore revisionato"), "Motore revisionato"),
    (R(r"zahnriemen (neu|gewechselt|erneuert)|nov[ée] rozvody|distributieriem (nieuw|vervangen)|courroie de distribution (neuve|faite)|correa de distribución (nueva|cambiada)|cinghia (nuova|sostituita|appena fatta)"), "Cinghia di distribuzione sostituita"),
    (R(r"neue reifen|reifen neu|nov[ée] pneu|nieuwe banden|pneus neufs|neumáticos nuevos|gomme nuove"), "Gomme nuove"),
    (R(r"winterreifen|zimn[íi] pneu|winterbanden|pneus hiver|neumáticos de invierno|gomme invernali"), "Con gomme invernali"),
    (R(r"klima(anlage|automatik)?\b|klimatizace|klimatiz[áa]cia|airco|climatisation|aire acondicionado|climatizzat|\ba/?c\b"), "Aria condizionata"),
    (R(r"schiebedach|sonnendach|panoramadach|st[řr]e[šs]n[íi] okno|schuifdak|toit ouvrant|techo solar|tetto apribile|sunroof"), "Tetto apribile"),
    (R(r"\bleder|kožen|ko[žz]a\b|lederen|\bleer\b|cuir|cuero|pelle\b"), "Interni in pelle"),
    (R(r"anhängerkupplung|\bahk\b|ta[žz]n[ée] za[řr][íi]zen|trekhaak|attelage|enganche|gancio traino"), "Gancio traino"),
    (R(r"mwst\.? ausweisbar|mehrwertsteuer ausweisbar|odpo[čc]et dph|btw verrekenbaar|tva récupérable|iva deducible|iva esposta"), "IVA deducibile (utile per aziende)"),
    (R(r"\bvb\b|verhandlungsbasis|verhandelbar|dohodou|n\.?o\.?t\.?k|prix à débattre|negociable|trattabile"), "Prezzo trattabile"),
    (R(r"motorschaden|getriebeschaden|defekt|nicht fahrbereit|nepojízd|nefunk[čc]n|motor kapot|ne roule pas|averiad|non funzionante|da riparare"), "⚠ Guasti dichiarati: da riparare"),
    (R(r"\brost\b|rostet|durchgerostet|koroze|hrdza|roest\b|rouille|óxido|ruggine"), "⚠ Ruggine segnalata dal venditore"),
    (R(r"unfallwagen|unfallschaden|havarovan|bourané|schadeauto|accidenté|accidentado|incidentata"), "⚠ Auto incidentata"),
    (R(r"ohne papiere|ohne brief|bez tp|bez dokladů|zonder papieren|sans papiers|sin papeles|senza documenti"), "⚠ Senza documenti"),
    (R(r"\bexport\b|nur export|nur händler|export only"), "Venduta preferibilmente all'export o a commercianti"),
]
OWNERS = R(r"\b([2-9])\.?\s?(hand|hd\b|majitel|majite|eigenaar|propriétaire|propietario|proprietario)", re.I)
INSPECTION = R(r"\b(tüv|hu|stk|apk|pickerl|itv|ct|revisione)\b[^0-9]{0,15}(?:bis|do|tot|until|fino a|valid[ao]?)?\s*(\d{1,2})[./-](\d{2,4})", re.I)
INSPECTION_NEW = R(r"tüv neu|hu neu|nov[áa] stk|stk nov|apk nieuw|ct ok|revisione (nuova|appena fatta)", re.I)


def extract(text: str | None) -> list[str]:
    if not text:
        return []
    t = text.lower()
    out: list[str] = []
    m = INSPECTION.search(text)
    if m:
        year = m.group(3)
        year = ("20" + year) if len(year) == 2 else year
        out.append(f"Revisione/collaudo valida fino al {int(m.group(2)):02d}/{year}")
    elif INSPECTION_NEW.search(text):
        out.append("Revisione/collaudo appena fatta")
    o = OWNERS.search(text)
    for rx, label in FACTS:
        if label == "Primo proprietario" and o:
            continue
        if label.startswith("⚠ Ruggine") and "Senza ruggine (dichiarato)" in out:
            continue
        if label == "⚠ Auto incidentata" and "Mai incidentata (dichiarato dal venditore)" in out:
            continue
        if rx.search(t) and label not in out:
            out.append(label)
    if o:
        out.insert(0, f"{o.group(1)}° proprietario")
    # warnings last
    return [x for x in out if not x.startswith("⚠")] + [x for x in out if x.startswith("⚠")]


# --- documentation signals: True = stated, False = stated missing, None = not mentioned
DOCS = {
    "service_book": (
        R(r"scheckheft|serviceheft|wartungsheft|servisn[íi] kn[íi][žz]k|servisná kniha|onderhoudsboek|onderhoudshistorie|carnet d.entretien|libro de mantenimiento|service ?(book|history)|libretto (dei )?tagliandi|tagliandi (certificati|documentati)|lückenlos"),
        R(r"(ohne|kein|keine)\s+(scheckheft|serviceheft)|scheckheft (fehlt|nicht vorhanden)|bez servisn[íi]|geen onderhoudsboek|sans carnet|no service history|senza libretto"),
    ),
    "invoices": (
        R(r"rechnungen|belege|quittungen|faktur[ay]|facturen|nota's|factures|facturas|invoices|receipts|fatture|ricevute"),
        R(r"(ohne|keine)\s+(rechnungen|belege)|bez faktur|sans factures|senza fatture"),
    ),
    "inspections": (
        R(r"tüv[- ]?(berichte|historie|protokolle)|hu[- ]?berichte|alle tüv|stk protokol|apk[- ]?(rapport|historie)|nap\b|contrôles? techniques?|itv (al día|historial)|storico (delle )?revisioni|revisioni regolari|kilometerstand logisch"),
        None,
    ),
    "owners": (
        R(r"\b([1-9])\.?\s?(hand|hd\b|majitel|majiteľ|eigenaar|propriétaire|propietario|proprietario)|erstbesitz|first owner|unico proprietario|prima mano"),
        None,
    ),
}


def extract_docs(text: str | None) -> dict:
    """Which documents the seller mentions. Missing from the ad != missing: the site says 'ask'."""
    t = (text or "").lower()
    out = {}
    for key, (pos, neg) in DOCS.items():
        if neg is not None and neg.search(t):
            out[key] = False
        elif pos.search(t):
            out[key] = True
        else:
            out[key] = None
    m = DOCS["owners"][0].search(t)
    if m:
        out["owners_n"] = int(m.group(1)) if m.group(1) else 1
    return out
