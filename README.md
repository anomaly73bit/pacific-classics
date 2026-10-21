# Pacific Classics

**Bulletproof classics from across Europe.** Un robot che cerca su marketplace e concessionari europei i 50 modelli "increvables" dagli anni '80 in poi (Mercedes W124/W201, Volvo 240, Land Cruiser, Golf TDI…), li mette su un'unica pagina con foto, prezzo, posizione e link all'annuncio originale, e per ogni auto aggiunge **consigli e alert**:

- iscrizione storica: FIVA/UE (30 anni) e CRS ASI Italia (20 anni), con anno di idoneità
- prezzo rispetto alla mediana di mercato: affare, in linea, caro, **sospetto/troppo basso**
- calo di prezzo dall'ultima scansione
- motore consigliato o variante debole del modello
- chilometraggio: alto, normale per motori leggendari, troppo basso da verificare
- cambio automatico sui modelli dove è il punto debole
- parole chiave nell'annuncio (DE/IT/CZ/FR/EN): incidente, guasto, ruggine, tagliandi, primo proprietario, già targa storica…
- import in Italia, venditore privato o concessionario, doppioni dello stesso annuncio su più siti
- **Punteggio Pacific** da 0 a 100

Sito in inglese e italiano, statico (nessun server), filtri condivisibili via URL.

## Fonti

| Sito | Paesi | Metodo |
|---|---|---|
| AutoScout24 | DE, AT, BE, NL, LU, FR, ES, IT | dati JSON della pagina di ricerca |
| Sauto.cz | CZ | API JSON della ricerca |
| willhaben.at | AT | dati JSON della pagina di ricerca |
| Kleinanzeigen.de | DE | HTML della pagina di ricerca |
| mobile.de | DE | solo **API ufficiale** (serve account dealer: secret `MOBILEDE_API_USER` / `MOBILEDE_API_PASSWORD`) |

Il robot rispetta `robots.txt`, aspetta 3–7 secondi tra una richiesta e l'altra sullo stesso sito e si ferma su un sito appena riceve un blocco anti-bot. Le foto **non vengono copiate**: sono mostrate dal sito originale e ogni scheda porta all'annuncio.

## Uso

```bash
pip install -r requirements.txt
python -m pacific_classics demo                              # dati di prova per vedere il sito
python -m pacific_classics crawl                             # tutti i siti, tutti i modelli
python -m pacific_classics crawl --sources sauto --models w124 volvo-240
python -m pacific_classics serve                             # http://localhost:8000
python -m pytest -q
```

## Automatico ogni giorno (GitHub Actions)

`.github/workflows/crawl.yml` gira ogni giorno alle 04:17 UTC (o a mano da **Actions → Crawl & publish → Run workflow**), salva i dati nel repo e pubblica il sito su GitHub Pages.

Per attivare Pages: **Settings → Pages → Source: GitHub Actions**. Su un repository privato GitHub Pages richiede un piano a pagamento (Pro/Team); in alternativa rendi il repo pubblico o usa `serve` in locale.

## Personalizzare

- `config/models.yaml` — i 50 modelli: anni, motori buoni/deboli (regex), punti da controllare, slug di ricerca
- `config/sources.yaml` — siti attivi, paesi AutoScout24, pause, parole da escludere (ricambi, cerco…), cambi valuta
- `site/i18n.js` — testi del sito e degli alert in EN/IT

## Struttura

```
pacific_classics/
  sources/        un adattatore per sito (autoscout24, sauto, willhaben, kleinanzeigen, mobilede)
  knowledge.py    base dati modelli + riconoscimento del modello dall'annuncio
  advisor.py      alert, consigli, stato storico, punteggio
  pipeline.py     crawl → normalizza → abbina → consiglia → pubblica JSON
site/             sito statico (index.html, app.js, styles.css, data/*.json)
data/state.json   storico prezzi tra una scansione e l'altra
```

## Note importanti

- I siti cambiano spesso struttura e protezioni anti-bot. Se un sito smette di dare risultati, la scheda **Stato robot** del sito mostra quale fonte è bloccata o in errore e quante auto ha trovato per ogni ricerca.
- Gli adattatori sono testati su campioni di pagina, non ancora sui siti veri: la prima scansione reale potrebbe richiedere qualche ritocco agli slug di ricerca in `models.yaml`.
- I dati raccolti servono per uso interno di ricerca auto; verifica le condizioni d'uso di ciascun sito prima di un uso commerciale o di una pubblicazione aperta.

---
Pacific IT Solutions s.r.o.
