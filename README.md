# CV-skills-AI-Powered — Manuale tecnico e operativo

Modulo **skills-gap e riconversione professionale** della piattaforma di staffing **Workint**.

Risponde a quattro domande, nell'ordine in cui un lavoratore se le pone:

1. *Il mio lavoro sta perdendo mercato?* → trend di domanda della sua categoria
2. *Quali lavori in crescita sono più raggiungibili con le competenze che ho già?* → classifica di riconversione
3. *Cosa mi manca esattamente per arrivarci?* → gap deterministico competenza per competenza
4. *Che corsi devo fare per colmare il gap?* → corsi del catalogo agganciati alle competenze mancanti, più un report in linguaggio naturale scritto da un LLM

È un **backend FastAPI**: la UI di produzione è l'app Angular di Workint, che consuma le API REST descritte qui. La Swagger UI su `/docs` fa da frontend di test.

> Documenti correlati: [docs/MANUALE.md](docs/MANUALE.md) è il manuale *didattico* (spiega le librerie e i concetti per chi vuole studiarli; scritto prima dei moduli recommend/courses). [DESIGN_NOTES.md](DESIGN_NOTES.md) è la storia delle decisioni di design. Questo README è il riferimento *operativo*: contratto API, funzionamento interno, formule, pipeline, manutenzione.

---

## Indice

1. [Il prodotto in una storia (esempio reale)](#1-il-prodotto-in-una-storia-esempio-reale)
2. [Architettura: due fasi](#2-architettura-due-fasi)
3. [I metodi: matematica e motivazioni](#3-i-metodi-matematica-e-motivazioni)
4. [Cosa succede quando l'utente fa una cosa (flussi passo-passo)](#4-cosa-succede-quando-lutente-fa-una-cosa)
5. [Riferimento API completo](#5-riferimento-api-completo)
6. [Il codice, file per file](#6-il-codice-file-per-file)
7. [Il database, tabella per tabella](#7-il-database-tabella-per-tabella)
8. [Installazione da zero](#8-installazione-da-zero)
9. [La pipeline di build del benchmark](#9-la-pipeline-di-build-del-benchmark)
10. [Operatività: aggiornamenti, catalogo corsi, deployment](#10-operatività-aggiornamenti-catalogo-corsi-deployment)
11. [Configurazione completa (.env)](#11-configurazione-completa-env)
12. [Test](#12-test)
13. [Limiti noti e scelte consapevoli](#13-limiti-noti-e-scelte-consapevoli)
14. [Cosa resta da fare (roadmap)](#14-cosa-resta-da-fare-roadmap)

---

## 1. Il prodotto in una storia (esempio reale)

Questa sequenza è stata eseguita davvero contro il server, con `data/sample_cv.pdf` (un CV da cuoco) e i dati di produzione nel DB locale. È il percorso che farà l'utente finale nella UI.

**Passo 1 — il lavoratore carica il CV e dichiara il suo mestiere:**

```bash
curl -X POST "http://127.0.0.1:8077/skills-gap/recommend-cv?k=3&current_job=Cuoco" \
     -F "file=@cv.pdf;type=application/pdf"
```

Risposta (riassunta):

```jsonc
{
  "n_worker_skills": 8,
  "current_job_category": "Cuoco",
  "current_growth_pct": -22.8,        // ← "il tuo mestiere ha perso il 22,8% di quota di mercato"
  "recommendations": [
    { "category_id": 92, "job_category": "Pizzaiolo",       "score": 0.700,
      "coverage_pct": 70.0, "growth_pct": 233.5, "missing_preview": ["utilizzare il forno a legna", ...] },
    { "category_id": 40, "job_category": "Aiuto Cuoco",     "score": 0.660,
      "coverage_pct": 66.0, "growth_pct": 332.1, ... },
    { "category_id": 72, "job_category": "Addetto Catering","score": 0.562, ... }
  ]
}
```

La storia che la UI può raccontare: *"Cuoco è in calo (−22,8%). Pizzaiolo è la tua mossa migliore: possiedi già il 70% delle competenze richieste e la domanda è in forte crescita."*

**Passo 2 — il lavoratore sceglie Pizzaiolo, la UI richiama l'analisi di dettaglio:**

```bash
curl -X POST "http://127.0.0.1:8077/skills-gap/analyze-cv?target_category_id=92" \
     -F "file=@cv.pdf;type=application/pdf"
```

Risposta (riassunta): copertura ESCO 70%, 6 competenze mancanti, e per 4 di esse corsi concreti dal catalogo:

```jsonc
{
  "esco": { "coverage_pct": 70.0, "covered": [...], "missing": ["pianificare i menu", ...] },
  "suggested_courses": [
    { "skill": "occuparsi dell'assistenza clienti",
      "courses": [ { "title": "Corso customer service", "hours": 24, "score": 0.79 } ] },
    { "skill": "pianificare i menu",
      "courses": [ { "title": "Corso di cucina professionale", "hours": 120, "score": 0.61 } ] }
  ],
  "report": {
    "strengths": "Il candidato dimostra solide basi di cucina...",
    "gaps": "Le lacune principali riguardano...",
    "formation": [ "Corso customer service ... 24 ore", "Corso di cucina professionale ... 120 ore" ]
  }
}
```

Il report LLM **cita i corsi reali del catalogo** (titolo e ore), perché glieli passiamo nel prompt: non inventa.

---

## 2. Architettura: due fasi

### Fase A — costruzione del benchmark (offline, periodica, senza LLM)

Riproducibile e deterministica. Trasforma due tassonomie autorevoli in una tabella `job_benchmark` con **una riga per categoria di lavoro** osservata negli annunci:

```
offerte_lavoro (DB esterno) ──► snapshot delle job_category distinte (finestra temporale)
                                          │  485 osservate, 306 con ≥ MIN_POSTINGS annunci
                ┌─────────────────────────┴──────────────────────────┐
          ESCO v1.2.0 (UE)                                  CP2021 (ISTAT/INAPP)
   3.039 occupazioni, 13.939 skill,                    813 unità professionali,
   129.004 relazioni essential/optional                competenze via API INAPP
   classificazione ibrida cat→occupazione              classificazione ibrida cat→cod_5
                └─────────────────────────┬──────────────────────────┘
                                   job_benchmark (306 righe)
                          media: 24,4 skill essenziali + 32,8 opzionali
                                 + 30 competenze CP2021
                                          │
                              + category_trend (domanda)
                              + course (catalogo corsi)
                              + label_emb_<modello>.npz (embedding precomputati)
```

L'unica fase "morbida" (non deterministica) è la mappatura testo libero → occupazione, ed è **isolata e auditata**: ogni mappatura salva i top-5 candidati con punteggi e un flag `needs_review` per la revisione umana (§9.3).

### Fase B — analisi del lavoratore (online, per richiesta)

```
CV PDF ──► estrattore esterno ──┐
                                ├──► competenze del lavoratore ──┬──► /recommend-*  (classifica 306 lavori)
worker_id ──► tabella workers ──┘                                └──► /analyze-*    (gap su 1 lavoro
                                                                       + corsi + report LLM)
```

Il **gap è deterministico** (coseno tra embedding, soglie fisse): a parità di input l'output è identico, testabile, spiegabile. **Solo il report narrativo** usa un LLM, ed è fail-soft: se il provider è giù la risposta arriva comunque con `report: null`.

**Stack:** Python 3.12 · FastAPI · PostgreSQL (SQLAlchemy) · sentence-transformers (`paraphrase-multilingual-mpnet-base-v2`) · rapidfuzz · LLM OpenAI-compatibile (Groq oggi, OpenAI senza cambi di codice). Niente vector-DB: il dataset è piccolo, il matching è in-process con NumPy.

---

## 3. I metodi: matematica e motivazioni

### 3.1 Embedding e similarità coseno

Tutto il matching semantico usa un solo modello: **`paraphrase-multilingual-mpnet-base-v2`** (sentence-transformers), che mappa un testo in un vettore di **768 dimensioni**. Encodiamo sempre con `normalize_embeddings=True`, cioè ogni vettore ha norma 1. Conseguenza pratica:

> similarità coseno(a, b) = (a·b)/(‖a‖‖b‖) = **a·b** (prodotto scalare)

quindi confrontare *n* competenze del lavoratore con *m* etichette del benchmark è **una sola moltiplicazione di matrici** `S = B·Wᵀ` di shape `(m, n)` — microsecondi in NumPy, niente indici vettoriali da gestire.

*Perché questo modello:* è **multilingue** (il benchmark mescola etichette italiane ESCO/CP2021 con titoli inglesi tipo "Software Developer", e i CV mescolano "analisi dati" con "machine learning"), è tarato per similarità tra frasi brevi (paraphrase), e pesa ~1 GB gestibile in RAM. Modello configurabile via `EMBEDDING_MODEL`.

### 3.2 Il gap: copertura per soglia (`app/gap.py`)

Per ogni competenza del benchmark *bᵢ* cerchiamo la competenza del lavoratore più simile:

> `score(bᵢ) = maxⱼ S[i][j]`  →  **coperta** se `score ≥ soglia`, altrimenti **mancante**.

Della competenza coperta salviamo anche `matched_with` (quale skill del lavoratore l'ha coperta) e lo score: la UI può mostrare *"pianificare i menu ✓ coperta da 'gestione cucina' (0.78)"* — trasparenza totale, niente scatola nera.

**Due soglie diverse, ed è il punto delicato:**

| Asse | Soglia | Perché |
|---|---|---|
| ESCO (`GAP_COVER_THRESHOLD`) | **0.62** | Calibrata su CV reali: sotto 0.62 entrano coperture spurie, sopra si perdono parafrasi legittime. |
| CP2021 (`GAP_CP2021_COVER_THRESHOLD`) | **0.68** | Le competenze CP2021 sono trasversali e astratte (stile O*NET: "Resistenza", "Forza del busto"). I **nomi propri tecnici producono falsi positivi fino a ~0.67**: empiricamente "java" matcha "Resistenza" a 0.62–0.67 (l'isola di Giava → resistenza fisica?). I match genuini di profili soft/manuali stanno a 0.70–0.88. La soglia 0.68 taglia il rumore preservando i match veri. |

Conseguenza documentata: per un CV tecnico la copertura CP2021 è ~0% **ed è corretto** (un CV da sviluppatore non elenca destrezza manuale). L'asse primario del gap è ESCO; la sezione CP2021 va letta come *profilo di competenze trasversali*, non come checklist.

### 3.3 Risoluzione del lavoro target: esatto → sinonimi → ibrido

L'utente scrive testo libero ("Sviluppatore Python senior"); il benchmark ha 306 etichette canoniche. La risoluzione (`gap.resolve_category`) procede a cascata:

1. **Match esatto** case-insensitive sull'etichetta → confidenza 1.0.
2. **Mappa dei sinonimi** (`gap._SYNONYMS`, ~40 radici italiane): se l'input contiene la radice ("sviluppator", "infermier", "cuoc"…) si mappa direttamente all'etichetta target → confidenza 1.0. *Perché serve:* il benchmark usa spesso etichette inglesi ("Software Developer") che l'embedding non aggancia bene da "Sviluppatore" — il problema cross-lingua più frequente è risolto a costo zero con una tabella esplicita e ispezionabile.
3. **Match ibrido** su tutte le 306 categorie:

   > `combined = 0.5 · coseno(input, etichetta) + 0.5 · WRatio(input, etichetta)/100`

   dove WRatio è la similarità lessicale fuzzy di rapidfuzz (0–100). *Perché ibrido:* il semantico da solo sbaglia su stem condivisi che il modello sottovaluta ("Magazziniere" ↔ "magazzino"), il lessicale da solo non vede i sinonimi veri; la media dei due è robusta a entrambe le modalità di errore. Lo stesso α=0.5 è usato nella pipeline di classificazione offline (coerenza tra build e runtime).

4. Se `combined ≥ 0.55` (`RESOLVE_MIN_SCORE`) → risolto, con `target_confidence = combined` esposto nella risposta (la UI mostra "abbiamo interpretato il target come X — confermi?" quando < 1.0).
5. Altrimenti → **HTTP 404 strutturato** con i top-3 candidati (`suggest_categories`), così la UI apre un picker "forse cercavi…" e ri-invia con `target_category_id`. Mai un vicolo cieco.

### 3.4 Trend di domanda: quote, non conteggi (`scripts/compute_trends.py`)

Confrontiamo due finestre adiacenti di `TREND_WINDOW_DAYS` (default 90) giorni che terminano alla data àncora:

```
previous = (anchor − 2w, anchor − w]        recent = (anchor − w, anchor]
```

**Non usiamo i conteggi assoluti.** Motivo verificato sui dati: il volume della sorgente segue l'attività dello scraper, non il mercato (ago 2025: 568k annunci; feb 2026: **15**). Coi conteggi assoluti, tutte le categorie risulterebbero "in crollo" quando lo scraper rallenta. Usiamo quindi la **quota di mercato** della categoria in ciascuna finestra:

> `share_r = n_r / T_r` , `share_p = n_p / T_p`
> `growth_pct = 100 · (share_r − share_p) / share_p`

dove `T` è il totale annunci della finestra. La quota cancella il fattore di volume globale: +20% significa *"questo mestiere occupa il 20% di mercato in più di prima"*, qualunque cosa faccia lo scraper.

Protezioni statistiche:
- `n_r + n_p < TREND_MIN_POSTINGS` (default 30) → `growth_pct = NULL` (su numeri piccoli la quota oscilla selvaggiamente; meglio dichiarare "non lo so");
- `share_p = 0` con presenze recenti → cap a +100 (apparso dal nulla);
- cap superiore a +999 (le esplosioni relative di micro-categorie non devono dominare);
- se la finestra recente ha < 5% del volume della precedente, lo script **avvisa** di pinnare `TREND_ANCHOR_DATE` all'ultima data sana (oggi: `2025-10-31`).

Stato attuale del DB: 485 categorie, 412 con trend calcolato (301 in crescita di quota, 111 in calo), 73 NULL per dati insufficienti.

### 3.5 La classifica di riconversione (`app/recommend.py`)

Per **tutte** le 306 categorie si calcola la copertura come in §3.2 (asse ESCO, essential+optional; CP2021 escluso: le competenze trasversali non discriminano tra target). Poi il punteggio:

> `trend01(g) = 0.5 + clip(g, −100, +100)/200` ∈ [0, 1] (lineare; NULL → 0.5 neutro)
> `demand_factor = 0.5 + 0.5 · trend01` ∈ **[0.5, 1.0]**
> **`score = (coverage/100) · demand_factor`** ∈ [0, 1]

**Perché moltiplicativo e non additivo — lezione imparata sul campo.** La prima versione era `0.6·cov + 0.4·trend01`: nel collaudo reale, micro-categorie con crescita di quota al cap (+999%) ma copertura 8% ("Operatore Olistico") scavalcavano lavori realmente raggiungibili. Col prodotto, la domanda **modula** la raggiungibilità invece di sommarsi ad essa:

- copertura 0 → score 0, *sempre*: un lavoro irraggiungibile non viene mai proposto, per quanto esploda la sua domanda;
- il fattore domanda è confinato in [0.5, 1.0]: il crollo totale della domanda al massimo **dimezza** un lavoro raggiungibile, non lo azzera (un lavoro in calo ma a portata di mano resta più sensato di uno in boom irraggiungibile);
- trend ignoto → fattore 0.75, neutro: l'assenza di dati non premia né punisce.

Verifica numerica sul caso reale: Pizzaiolo `0.70 · 1.0 = 0.700` > Aiuto Cuoco `0.66 · 1.0 = 0.660` > Cuoco `0.66 · 0.693 = 0.457` (è il mestiere attuale: trend −22,8% → trend01 0.386 → fattore 0.693 — e comunque viene escluso dalla lista quando `current_job` è noto).

In ogni raccomandazione, `missing_preview` elenca le mancanti **ordinate per similarità discendente** col bagaglio attuale: le prime sono le più economiche da imparare — è l'aggancio naturale per i corsi.

*Costo computazionale:* tutte le etichette del benchmark (6.007 uniche ESCO) sono già nel file di embedding precomputati, quindi la classifica completa è una manciata di prodotti matriciali — ben sotto il secondo, nessun costo di encoding a runtime.

### 3.6 Suggerimento corsi (`app/courses.py`)

Ogni corso è rappresentato dall'embedding di `"titolo. descrizione"`. Per ogni competenza mancante si calcola la similarità con tutti i corsi; si tengono fino a `PER_SKILL=2` corsi sopra **`MIN_COURSE_SIM=0.55`**, e si pubblicano le `MAX_SKILLS=5` competenze col miglior corso disponibile, ordinate per qualità del match.

*Calibrazione (smoke test reali):* match genuini 0.74–0.90 ("nutrizione" → *Corso nutrizione e diete* 0.80; norme igienico-alimentari → *Corso HACCP* 0.83; "gestione di progetto" → *Corso project management* 0.90); rumore ≤ 0.53 (*Corso gestione magazzino* per "gestione di progetto"). La soglia 0.55 separa le due popolazioni. **Una skill senza corso decente viene omessa**: un suggerimento debole è peggio di nessun suggerimento.

*Perché matching semantico e non mappatura manuale corso→skill ESCO:* il catalogo può restare testo libero (qualunque CSV di qualunque fonte), zero lavoro redazionale, e i corsi nuovi agganciano automaticamente le skill giuste.

### 3.7 Cache degli embedding persistente

Le etichette del benchmark sono statiche tra una build e l'altra → si precomputano offline (`scripts/precompute_embeddings.py`) in `data/cache/label_emb_<md5(modello)[:12]>.npz`: **6.133 etichette distinte ≈ 19 MB** float32 (le 126 etichette CP2021 sono condivise tra categorie: dedup → ~6k vettori invece dei ~27k di una cache per-categoria). All'avvio l'API carica il file in un dizionario `testo → vettore` (`gap._EMB_STORE`); le richieste encodano **solo i miss** (le skill inedite del lavoratore) e li memoizzano. Il nome file è derivato dal modello: cambiando `EMBEDDING_MODEL` il file vecchio viene ignorato, mai caricato per sbaglio.

---

## 4. Cosa succede quando l'utente fa una cosa

### 4.1 All'avvio del server

`uvicorn app.main:app` esegue il lifespan di FastAPI che **pre-scalda tutto**: modello mpnet (~400 MB in RAM), store degli embedding dal `.npz`, indice delle 306 categorie, indice skill per il recommender, indice corsi. Avvio in ~10–15 s; **la prima richiesta è già veloce**. (Conseguenza: il server tiene il codice in memoria — dopo aver modificato `app/` va riavviato, o si usa `--reload` in sviluppo.)

### 4.2 `POST /skills-gap/analyze-cv` con un PDF

1. Il PDF è inoltrato all'**estrattore esterno** (`EXTRACTOR_URL`, header `x-access-password`, timeout 120 s, ~7 s misurati). Errore di rete o HTTP ≠ 200 → **502** col motivo. Le estrazioni riuscite sono **cacheate per hash del contenuto** (LRU, 64 voci): il flusso consigliato recommend→analyze carica lo stesso PDF due volte, ma paga l'estrattore una sola; gli errori non vengono cacheati (il retry riparte pulito).
2. La risposta JSON è mappata in un `WorkerProfile` da `sources.profile_from_extracted`: chiavi tolleranti (`competenze_tecniche`, `competenze_soft`, `skills`, `hard_skills`…), pulizia di ogni voce (via bullet `- * • ·` e numerazioni, via markdown `** __ \``, lowercase, trim), deduplica preservando l'ordine. Nessuna skill → **422**.
3. Scelta del target, in priorità:
   - `target_category_id` presente → lookup diretto (id inesistente → 404);
   - altrimenti `target_job_category` (testo) → cascata di risoluzione §3.3; irrisolvibile → **404 con `candidates`** per il picker;
   - altrimenti fallback sul **ruolo dichiarato nel CV** (se l'estrattore l'ha trovato); anche questo assente → 404 esplicativo.
4. Gap ESCO + CP2021 (§3.2) → corsi per le mancanti (§3.6) → report LLM (§4.6). Risposta `GapResult`.

**Cosa cambia per la UI tra i tre casi:** col `target_category_id` la risposta ha `target_confidence: null` (match esatto, nessun avviso); col testo risolto fuzzy ha `target_confidence: 0.xx` (mostrare il banner di conferma); col 404+candidates la UI apre il picker e ri-invia con l'id scelto — il giro completo è: testo → 404 → scelta → id → 200.

### 4.3 `POST /skills-gap/analyze-worker/{id}`

1. Lettura dal DB esterno (`workers`): prima si interroga `information_schema` per verificare che le colonne configurate esistano — se no **501** con l'elenco di quelle disponibili (significa: aggiornare le env `WORKERS_COL_*`, vedi §11). Le colonne PII (nome, email, telefono) **non vengono mai lette**.
2. Worker inesistente → **404**. Senza skill → **422**. Senza lavoro target/preferito → **422** (non possiamo scegliere un benchmark).
3. Da qui identico al flusso CV (punti 3–4 sopra), con `target = worker_preferred_jobs`.

### 4.4 `POST /skills-gap/recommend-cv` e `recommend-worker/{id}`

Stesse sorgenti dei rispettivi `analyze-*` (estrattore / tabella workers), poi:

1. Risoluzione del **lavoro attuale** (`current_job` in query, o fallback sul ruolo del CV / `worker_preferred_jobs`). Se risolve: la sua categoria è **esclusa** dalla classifica e il suo trend è esposto come `current_growth_pct`. Se non risolve o manca: nessuna esclusione, `current_*: null` — la classifica funziona comunque. ⚠️ L'estrattore spesso **non** restituisce il ruolo: il frontend dovrebbe passare sempre `current_job` quando lo conosce.
2. Copertura su tutte le 306 categorie + score moltiplicativo (§3.5) → top-`k` (default 10, max 50).
3. Nessuna chiamata LLM e nessun corso qui: la risposta è pensata per una lista cliccabile; il dettaglio arriva con l'`analyze-*` successivo sul target scelto.

### 4.5 `POST /skills-gap/reload-courses`

Svuota la cache dell'indice corsi e la ricostruisce dal DB; risponde `{"status":"ok","courses":N}`. Serve dopo `scripts/load_courses.py` per aggiornare il catalogo **senza riavviare** (gli embedding dei testi già visti sono memoizzati: ricarica quasi istantanea).

### 4.6 La generazione del report LLM (dentro ogni `analyze-*`)

1. Prompt in italiano con: ruolo target, fino a 8 competenze presenti, fino a 12 mancanti, copertura, e — se il catalogo ha agganciato corsi — il blocco *"Corsi realmente disponibili a catalogo (PREFERISCILI citandone il titolo esatto)"* col miglior corso per skill. Richiesta di **solo JSON** (`response_format: json_object`, `temperature 0.4`, `max_tokens 600`).
2. Difese sull'output, tutte motivate da bug realmente osservati: strip dei fence ` ```json `; i campi `strengths`/`gaps` coerciti a stringa qualunque shape arrivi (dict → join dei valori, list → join); `formation` coercita a lista di stringhe (gestisce `[{nome, durata}]`); prompt che vieta elenchi dentro i paragrafi (il modello incollava liste Python nel testo).
3. **Qualunque eccezione** (provider giù, JSON rotto) → log con stack e `report: null`. Il gap deterministico non si butta mai per colpa del report.

---

## 5. Riferimento API completo

Base path `/skills-gap`. **Autenticazione opzionale**: se la variabile `API_KEY` è impostata, tutti gli endpoint `/skills-gap/*` richiedono l'header `x-api-key` (altrimenti **401**; su Swagger appare il pulsante *Authorize*); `/health` resta sempre libero per i probe del load balancer. Con `API_KEY` assente il servizio è aperto — solo per sviluppo/rete fidata.

| Metodo e path | Input | Output | Scopo |
|---|---|---|---|
| `POST /skills-gap/analyze-cv` | multipart `file=<PDF>`; query `target_category_id` *oppure* `target_job_category` (fallback: ruolo del CV) | `GapResult` | Gap dettagliato su un lavoro target |
| `POST /skills-gap/analyze-worker/{worker_id}` | path `worker_id` int | `GapResult` | Idem, da worker memorizzato |
| `POST /skills-gap/recommend-cv` | multipart `file=<PDF>`; query `current_job`, `k` (1–50, default 10) | `RecommendationResult` | Classifica di riconversione |
| `POST /skills-gap/recommend-worker/{worker_id}` | path `worker_id`; query `k` | `RecommendationResult` | Idem, da worker memorizzato |
| `POST /skills-gap/reload-courses` | – | `{status, courses}` | Ricarica catalogo corsi a caldo |
| `GET /health` | – | `{"status":"ok"}` | Liveness |

### `GapResult`

```jsonc
{
  "category_id": 92,
  "job_category": "Pizzaiolo",        // categoria benchmark agganciata
  "target_confidence": null,           // null = match esatto; 0.xx = risolto fuzzy (UI: chiedere conferma)
  "n_worker_skills": 8,
  "esco": {                            // ASSE PRIMARIO del gap
    "source": "esco",
    "occupation_label": "pizzaiolo/pizzaiola",
    "n_total": 20, "n_covered": 14, "coverage_pct": 70.0,
    "covered": [ { "skill": "cuocere pizze", "matched_with": "preparazione piatti", "score": 0.81 } ],
    "missing": [ "utilizzare il forno a legna", "pianificare i menu", ... ]
  },
  "cp2021": { /* stessa shape; profilo trasversale, non checklist — vedi §3.2 */ },
  "suggested_courses": [               // [] se catalogo non caricato
    { "skill": "occuparsi dell'assistenza clienti",
      "courses": [ { "title": "Corso customer service", "provider": "Ente di formazione",
                     "url": null, "hours": 24, "score": 0.79 } ] }
  ],
  "report": {                          // null se LLM_API_KEY assente o provider in errore
    "strengths": "…", "gaps": "…",
    "formation": [ "Corso customer service … 24 ore", "…" ]
  }
}
```

### `RecommendationResult`

```jsonc
{
  "n_worker_skills": 8,
  "current_category_id": 14,           // null se current_job assente/irrisolto
  "current_job_category": "Cuoco",
  "current_growth_pct": -22.8,         // trend del lavoro ATTUALE (il "perché muoversi")
  "recommendations": [                 // top-k per score, lavoro attuale escluso
    { "category_id": 92, "job_category": "Pizzaiolo",
      "score": 0.700,                  // coverage × demand_factor, vedi §3.5
      "coverage_pct": 70.0, "n_covered": 14, "n_total": 20,
      "growth_pct": 233.5,             // null = trend non disponibile (neutro nel ranking)
      "missing_preview": [ "utilizzare il forno a legna", ... ]  // le più vicine da imparare, in ordine
    }
  ]
}
```

### Codici di errore

| Codice | Quando | Cosa deve fare la UI |
|---|---|---|
| `404` | target irrisolvibile (`detail.candidates` = top-3 con id/label/score) · worker inesistente | aprire il picker "forse cercavi…" e ri-inviare con `target_category_id` · messaggio |
| `422` | nessuna skill estratta dal CV / worker senza skill / worker senza lavoro target | spiegare cosa manca nel profilo |
| `501` | colonne `workers` non corrispondenti alla configurazione | errore di configurazione lato ops (`WORKERS_COL_*`) |
| `502` | estrattore CV irraggiungibile o in errore | riprova / segnala il servizio |

### Note per lo sviluppatore frontend

- `esco.coverage_pct` → progress bar; `esco.covered` → lista con `matched_with` + `score`; `esco.missing` → chips.
- `target_confidence != null` → banner "abbiamo interpretato il target come X — confermi?".
- `report` può essere `null` → `*ngIf`; `suggested_courses` può essere `[]`.
- Su `recommend-*` passare **sempre** `current_job` quando noto (l'estrattore spesso non fornisce il ruolo).
- Flusso consigliato: `recommend-*` → click su una card → `analyze-*` con `target_category_id` della card (il secondo upload dello stesso PDF non ripaga l'estrattore: cache per hash lato server).
- Se `API_KEY` è attiva, inviare l'header `x-api-key` su ogni chiamata `/skills-gap/*`.
- `CORS_ORIGINS` va impostato sull'origin Angular.

---

## 6. Il codice, file per file

### `app/` — il servizio online

**[app/main.py](app/main.py)** — Gli endpoint e nient'altro. Contiene: il lifespan di pre-warm (§4.1); `_extract_profile` (PDF→estrattore→profilo, con la mappatura errori 502/422) condiviso dai due flussi CV; `_run` che traduce `TargetNotFound` nel 404 strutturato con candidati; i sei endpoint. La logica di dominio sta tutta nei moduli sotto: ogni endpoint è ~10 righe.

**[app/config.py](app/config.py)** — Tutta la configurazione letta da `.env` in un punto solo, più i tre singleton processo-wide (`@lru_cache(maxsize=1)`): engine del DB locale, engine del DB esterno, modello sentence-transformer. Il modello è importato *lazy* dentro la funzione: importare `config` (nei test, negli script) non carica torch.

**[app/models.py](app/models.py)** — Il contratto Pydantic, cioè l'unica cosa che il frontend deve conoscere: `WorkerProfile` (interno), `SkillMatch`, `BenchmarkGap`, `CourseSuggestion`, `SkillCourses`, `Report`, `GapResult`, `RecommendationItem`, `RecommendationResult`. Niente logica: solo shape e descrizioni dei campi.

**[app/gap.py](app/gap.py)** — Il motore deterministico. In ordine:
- `_SYNONYMS`: la mappa radici italiane → etichette benchmark (§3.3), volutamente una lista piatta nel codice: ispezionabile, diffabile, zero magia;
- `TargetNotFound`: eccezione che **trasporta i candidati** per il 404 strutturato;
- `_EMB_STORE` / `_load_emb_store` / `_encode`: la cache persistente degli embedding (§3.7) — `_encode` è l'unico punto del runtime che chiama il modello, e solo sui miss;
- `_category_index`: (id, etichette, embedding) delle 306 categorie, cached;
- `_hybrid_scores` / `resolve_category` / `suggest_categories`: la cascata di risoluzione del target (§3.3);
- `_labels`: estrae le label dai JSONB del benchmark (tollera list già parsate o stringhe JSON);
- `_load_benchmark`: carica la riga `job_benchmark` per id o per testo (con `_target_confidence` annesso);
- `_gap`: il confronto a soglia (§3.2) che produce un `BenchmarkGap`;
- `analyze`: orchestrazione — carica il benchmark, pulisce le skill, **una** moltiplicazione di matrici per asse, due `_gap`, corsi, report, logging del risultato.

**[app/recommend.py](app/recommend.py)** — La classifica di riconversione (§3.5). `_benchmark_skill_index` (cached) carica le 306 categorie con le rispettive label ESCO e costruisce **una** matrice di embedding sulle 6.007 label uniche, con una lista di indici per categoria (le label ricorrono tra lavori simili: dedup sostanziale). `_load_trends` (cached) legge `category_trend` e **tollera la tabella assente** (ranking solo-skill, log di warning). `_trend_score` / `_combined_score`: le formule pure di §3.5, testate unitariamente. `recommend`: risolve il lavoro attuale, calcola `best = max` delle similarità per label unica, deriva copertura e score per categoria, esclude l'attuale, ordina, tronca a `k`.

**[app/courses.py](app/courses.py)** — Suggerimento corsi (§3.6). `_course_index` (cached, fail-soft se la tabella manca) carica il catalogo e ne encoda `"titolo. descrizione"`; `suggest_courses` fa il matching a soglia e l'ordinamento per qualità. La `cache_clear()` di `_course_index` è ciò che l'endpoint `reload-courses` invoca.

**[app/sources.py](app/sources.py)** — Gli adattatori di input, cioè il confine col mondo sporco:
- *Flusso CV:* `call_extractor` (POST multipart con header password, verify SSL configurabile perché l'host ha un certificato self-signed); `profile_from_extracted` con le liste di chiavi tolleranti e `_as_skill_list` che pulisce bullet/markdown/maiuscole e splitta stringhe su `;`/newline;
- *Flusso worker:* `_WORKER_COLS` (mappatura colonne env-overridabile), `load_worker` che valida lo schema via `information_schema` prima di leggere (→ 501 parlante invece di un errore SQL criptico) e **non seleziona mai le colonne PII**.

**[app/llm.py](app/llm.py)** — Il report narrativo (§4.6). Client OpenAI-compatibile con `base_url` per provider (Groq/OpenAI: si cambia in `.env`, zero codice); costruzione del prompt incluso il blocco corsi; le coercizioni difensive `_to_str` / `_to_str_list`; il try/except totale che degrada a `None`.

### `scripts/` — la pipeline offline

**[scripts/db.py](scripts/db.py)** — Helper condivisi: engine locali/esterni, costanti della finestra postings e dei trend, `safe_identifier` (whitelist `[A-Za-z_][A-Za-z0-9_]*` per i nomi tabella/colonna interpolati da env — non input utente, ma comunque validati).

**[scripts/init_db.py](scripts/init_db.py)** — Applica `sql/schema.sql` (idempotente: tutto `IF NOT EXISTS`). ⚠️ psycopg2 interpreta i `%` letterali come placeholder in `exec_driver_sql`: lo schema non deve contenere percentuali nei commenti.

**[scripts/load_esco.py](scripts/load_esco.py)** — Carica il bundle CSV ESCO italiano pinnato (`ESCO_VERSION`) in `esco_occupation` (3.039), `esco_skill` (13.939), `esco_occupation_skill` (129.004 relazioni essential/optional). Tollera varianti dei nomi file/colonne tra release ESCO; scarta le relazioni con endpoint mancanti; tagga ogni riga con la versione.

**[scripts/load_cp2021.py](scripts/load_cp2021.py)** — Da `CP2021.xlsx` (foglio `quinto_digit`): le 813 unità professionali in `cp2021_profession` (il `cod_5` puntato, es. `2.1.1.1.1`, è anche il codice dell'API INAPP). Da `cp2021_classificazione.xlsx` (foglio voci professionali, 6° digit): i titoli specifici in `cp2021_label` (7.626 etichette), usati come gli altLabels ESCO per aumentare il recall della classificazione.

**[scripts/mirror_categories.py](scripts/mirror_categories.py)** — Lo snapshot: conta gli annunci per `job_category` distinta nella finestra `DATE_FROM`–`DATE_TO` sul DB esterno e li scrive in `job_category` locale con `in_benchmark = (count ≥ MIN_POSTINGS)`. Registra finestra e colonna data usate: la selezione resta riproducibile anche se la sorgente è volatile. Stato: 485 categorie, 306 in benchmark.

**[scripts/classify_categories.py](scripts/classify_categories.py)** — Il passo "morbido", reso auditabile. Matcha ogni categoria contro **tutte le etichette** ESCO (preferred + altLabels — le foglie ESCO sono iper-specifiche, i termini generici stanno negli altLabels: indicizzarli è essenziale) con lo score ibrido `0.5·coseno + 0.5·WRatio` (stesso α del runtime). Per categoria: top-5 occupazioni distinte con punteggi (sem/lex separati) salvate in `job_occupation_map.candidates_considered` (audit), `confidence = top1`, `needs_review = (top1 < 0.70)`.

**[scripts/classify_cp2021.py](scripts/classify_cp2021.py)** — Identico, verso le 813 professioni CP2021 (su nome_5 + voci) → `job_cp2021_map`.

**[scripts/fetch_cp2021_skills.py](scripts/fetch_cp2021_skills.py)** — Per ogni `cod_5` mappato interroga l'API INAPP (`survey.php`, dataset 1=compiti 2=conoscenze 4/5=skill 6=attività 8=stili) e salva ogni dimensione con `importanza`/`complessità` in `cp2021_profession_skill` (39.274 righe). Tollera le due shape di risposta dell'API e i codici senza dati (coperture parziali delle wave INAPP); throttle di 50 ms tra chiamate.

**[scripts/materialize_benchmark.py](scripts/materialize_benchmark.py)** — Il join finale, solo SQL deterministico: per ogni categoria in benchmark, le skill essential/optional dell'occupazione ESCO mappata (aggregate in JSONB `{uri,label,type}`) + le top-`CP2021_TOPN` (default 30) competenze CP2021 per importanza (sezioni `skill`+`conoscenze`) → **`job_benchmark`, una riga per categoria**. Da rilanciare dopo ogni passata di review o refetch.

**[scripts/precompute_embeddings.py](scripts/precompute_embeddings.py)** — Estrae tutte le label distinte dal benchmark (essential+optional+cp2021 = 6.133), le encoda in batch e salva il `.npz` (§3.7). Da rilanciare **dopo ogni rebuild del benchmark o cambio modello**.

**[scripts/compute_trends.py](scripts/compute_trends.py)** — I trend di domanda share-based (§3.4) → `category_trend`. Avvisa se la finestra recente è affamata di dati; `TREND_ANCHOR_DATE` per pinnare.

**[scripts/load_courses.py](scripts/load_courses.py)** — Carica un CSV `;`-separato (`title;provider;url;description;hours` + opzionali `region;external_id`) in `course`. **Multi-sorgente:** `--source X` sostituisce solo le righe di quella sorgente (Forma.Temp, GOL regionali, MOOC convivono con cadenze indipendenti); `--delete-source seed` elimina la demo. Dopo il load: `POST /skills-gap/reload-courses`.

**[scripts/export_review.py](scripts/export_review.py) / [scripts/import_review.py](scripts/import_review.py)** — Il ciclo di revisione umana della classificazione (§9.3): export CSV con i 5 candidati per categoria (flaggate prima le `needs_review` ad alto volume); l'umano compila `pick` (1–5) o `correct_uri`; l'import applica gli override (`classification_method='manual'`, `confidence=1.0`, `reviewed=true`) validando gli URI contro ESCO. Dopo: rilanciare materialize + precompute.

### Altro

**[sql/schema.sql](sql/schema.sql)** — Lo schema completo, commentato (vedi §7). **[conftest.py](conftest.py)** — bootstrap pytest: `app` importabile dal root + registrazione del marker `integration`. **[tests/](tests/)** — vedi §12. **[docker-compose.yml](docker-compose.yml)** — Postgres locale di sviluppo su :5433. **[data/](data/)** — download ESCO/CP2021, cache embeddings, seed corsi, CSV di review (gitignored salvo i seed).

---

## 7. Il database, tabella per tabella

| Tabella | Righe oggi | Contenuto e ruolo |
|---|---|---|
| `job_category` | 485 | Snapshot delle categorie distinte osservate negli annunci nella finestra; `posting_count`, finestra usata, `in_benchmark` (≥ `MIN_POSTINGS`). L'unità del benchmark. |
| `esco_occupation` | 3.039 | Occupazioni ESCO it (URI, ISCO, label, altLabels, descrizione, versione). Snapshot read-only. |
| `esco_skill` | 13.939 | Skill ESCO it (tipo knowledge/skill, reuse level…). |
| `esco_occupation_skill` | 129.004 | Relazioni occupazione↔skill `essential`/`optional`. |
| `job_occupation_map` | 306 | **L'unico passo soft, auditato**: categoria → occupazione ESCO con metodo, confidenza, top-5 candidati JSONB, flag `needs_review`/`reviewed`. |
| `cp2021_profession` | 813 | Unità professionali CP2021 (cod_5, nome, descrizione). |
| `cp2021_label` | 7.626 | Etichette di match (nome_5 + voci professionali 6° digit). |
| `cp2021_profession_skill` | 39.274 | Dimensioni INAPP per professione (sezione, label, importanza, complessità). |
| `job_cp2021_map` | 306 | Categoria → professione CP2021 (parallela a job_occupation_map). |
| `job_benchmark` | **306** | **La tabella che l'API legge**: una riga per categoria con `essential_skills`/`optional_skills`/`cp2021_skills` in JSONB + label e contatori. Media: 24,4 essenziali, 32,8 opzionali, 30 CP2021. |
| `category_trend` | 485 | Trend di domanda share-based per categoria (412 con `growth_pct` valorizzato). |
| `course` | 42 (seed demo) | Catalogo corsi multi-sorgente (`source`, `region`, `external_id`). |

Filosofia dello schema: i contenuti "cosa richiede il mestiere X" vengono **solo** da snapshot version-pinnati delle tassonomie (deterministici, rifare la build dà lo stesso risultato); l'unica inferenza (il mapping) è confinata in due tabelle con audit trail completo e ciclo di revisione.

---

## 8. Installazione da zero

### Prerequisiti

- **Docker** (Postgres locale del benchmark) · **Python 3.12** (`py -3.12` su Windows)
- Accesso di rete a: Postgres esterno (`workint-clone`), estrattore CV (`ai-services.workint.expleoitalia.it`), provider LLM (Groq/OpenAI), API INAPP (solo per la build), Hugging Face (primo download del modello).

### Setup

```bash
docker compose up -d                  # Postgres locale su :5433

py -3.12 -m venv .venv
.venv\Scripts\activate                # Windows
pip install -r requirements.txt

copy .env.example .env                # poi compilare i valori reali (vedi §11)
python scripts/init_db.py             # crea lo schema (idempotente)
```

### Acquisizione dati (manuale, una tantum, version-pinnata)

**ESCO** → in `data/esco/` (da <https://esco.ec.europa.eu/en/use-esco/download>): selezionare **v1.2.0**, lingua **Italian (it)**, formato **CSV**; servono `occupations_it.csv`, `skills_it.csv`, `occupationSkillRelations_it.csv`.

**CP2021** → in `data/cp2021/` (da <https://www.istat.it/it/archivio/18132>): `CP2021.xlsx` (col foglio `quinto_digit`) e `cp2021_classificazione.xlsx` (voci professionali). Le *competenze* CP2021 non sono nei file: arrivano live dall'API INAPP durante la build.

I file sono gitignored: ogni ambiente li scarica una volta e li pinna.

---

## 9. La pipeline di build del benchmark

### 9.1 Ordine di esecuzione

Da rilanciare integralmente a ogni refresh dei dati o ri-snapshot degli annunci:

```bash
python scripts/load_esco.py              # 1. tassonomia ESCO        → esco_*
python scripts/load_cp2021.py            # 2. tassonomia CP2021      → cp2021_profession, cp2021_label
python scripts/mirror_categories.py      # 3. snapshot categorie     → job_category (485, 306 in benchmark)
python scripts/classify_categories.py    # 4. cat → ESCO (ibrido)    → job_occupation_map
python scripts/classify_cp2021.py        # 5. cat → CP2021 (ibrido)  → job_cp2021_map
python scripts/fetch_cp2021_skills.py    # 6. API INAPP              → cp2021_profession_skill
python scripts/materialize_benchmark.py  # 7. join finale            → job_benchmark (306 righe)
python scripts/precompute_embeddings.py  # 8. cache embedding        → data/cache/label_emb_*.npz
python scripts/compute_trends.py         # 9. trend di domanda       → category_trend
python scripts/load_courses.py           # 10. catalogo corsi        → course
```

Dipendenze: 4 e 5 richiedono 1–3; 6 richiede 5; 7 richiede 4+6; 8 richiede 7; 9 richiede 3; 10 è indipendente. Dopo l'8 (e il 10 se il server gira) riavviare l'API o chiamare `reload-courses`.

### 9.2 Trend: il pin dell'àncora

La sorgente annunci ha avuto un crollo di volume dopo ottobre 2025 (scraper fermo). Finché non riprende, calcolare i trend pinnati all'ultimo periodo sano:

```bash
TREND_ANCHOR_DATE=2025-10-31 python scripts/compute_trends.py
```

(o mettere la variabile in `.env`). Lo script avvisa da solo quando la finestra recente è sospetta. Quando lo scraper riprende: togliere il pin e rilanciare.

### 9.3 Revisione umana della classificazione (opzionale ma consigliata)

```bash
python scripts/export_review.py   # → data/review/job_occupation_review.csv
# aprire il CSV: per ogni riga, `pick` = numero (1-5) del candidato giusto,
# oppure `correct_uri` = URI ESCO se nessuno dei 5 è corretto; vuoto = lascia com'è
python scripts/import_review.py   # applica le decisioni
python scripts/materialize_benchmark.py && python scripts/precompute_embeddings.py
```

Le righe flaggate `needs_review` (confidenza < 0.70) e ad alto volume vengono prime nel CSV: il tempo umano va dove conta.

---

## 10. Operatività: aggiornamenti, catalogo corsi, deployment

### 10.1 Avvio

```bash
python -m uvicorn app.main:app --port 8077            # produzione: + --workers N dietro proxy/TLS
python -m uvicorn app.main:app --reload --port 8077   # sviluppo: riavvio automatico su modifica
# Swagger: http://127.0.0.1:8077/docs
```

### 10.2 Catalogo corsi: fonti reali e cadenze (stato giugno 2026)

Il matcher è agnostico rispetto alla fonte (testo libero): "implementare i corsi" è un problema di **acquisizione dati**, non di codice. Fonti in ordine di valore:

1. **Catalogo interno / partner Forma.Temp** — *primaria per un'agenzia per il lavoro*: corsi a cui Workint può davvero iscrivere i lavoratori, spesso finanziati. Export CSV dal gestionale → `load_courses.py file.csv --source formatemp`. Cadenza mensile.
2. **Cataloghi GOL regionali** — autorevoli e gratuiti per il lavoratore, ma **senza API pubbliche**: portali riservati agli enti accreditati ([Campania](https://servizi-digitali.regione.campania.it/GolCatalogo), [Sicilia](https://catalogo-gol.regione.sicilia.it/), [Umbria](https://www.arpalumbria.it/catalogo-offerta-formativa-gol), [Calabria](https://www.regione.calabria.it/dipartimento-lavoro/aree-tematiche/programma-gol/avviso-2/catalogo-offerta-formativa/)) o PDF. Se Workint/un partner è ente accreditato: export trimestrale, un `--source gol_<regione>` per regione.
3. **API affiliate dei MOOC** (Udemy Affiliate, Coursera) — programmatiche, buon complemento per le skill digitali; richiedono registrazione affiliato. Cadenza mensile scriptabile.
4. ~~Open data Regione Lombardia~~ — verificato via API Socrata (`p9ej-dnv5`, `im6s-navj`): fermi al 2019 / percorsi scolastici. Non utilizzabili.

Flusso di aggiornamento (qualunque fonte), schedulabile con Task Scheduler/cron, **zero downtime**:

```bash
python scripts/load_courses.py <export.csv> --source <tag> [--region <Regione>]
curl -X POST http://<api>/skills-gap/reload-courses
```

Quando entra il primo catalogo vero: `python scripts/load_courses.py --delete-source seed` per togliere la demo, e ricalibrare `MIN_COURSE_SIM` su un campione (vedi §3.6).

### 10.3 Aggiornamenti periodici suggeriti

| Cosa | Comando | Cadenza |
|---|---|---|
| Trend di domanda | `compute_trends.py` | mensile (o al riavvio dello scraper) |
| Snapshot + benchmark completo | pipeline §9.1 (passi 3–8) | trimestrale, o quando cambiano le categorie |
| Catalogo corsi | `load_courses.py --source …` + reload | mensile per fonte |
| Tassonomie ESCO/CP2021 | passi 1–2 + tutto a valle | solo a nuova release (pinnate) |

### 10.4 Deployment

- Servire con uvicorn/gunicorn dietro il reverse proxy esistente (TLS lì).
- Il benchmark **deve essere già costruito** nel Postgres puntato da `LOCAL_DB_URL`; il Docker locale è solo sviluppo.
- Primo avvio: il modello (~1 GB) viene scaricato da Hugging Face e cacheato; nelle immagini container conviene baker il modello e il `.npz`.
- Accessi in uscita necessari: estrattore (cert self-signed → `EXTRACTOR_VERIFY_SSL=false` o `EXTRACTOR_CA_BUNDLE`), DB esterno, provider LLM.
- RAM: ~1,5 GB a regime (modello + embedding + indici).

### 10.5 Troubleshooting (gotchas verificati)

- **Modifiche ad `app/` non visibili** → il server tiene il codice in memoria: riavviare (o `--reload`).
- **`init_db.py`: `immutabledict is not a sequence`** → c'è un `%` letterale in `schema.sql` (psycopg2 lo legge come placeholder). Riformulare il commento.
- **Tutti i trend a −100% / "0 growing"** → scraper fermo: pinnare `TREND_ANCHOR_DATE` (§9.2).
- **`/tmp` tra git-bash e python Windows non è lo stesso posto** → negli script di test passare i dati via stdin, non file temporanei condivisi.
- **502 dall'estrattore con errore SSL** → host con certificato self-signed: `EXTRACTOR_VERIFY_SSL=false`.
- **CP2021 sempre 0% su CV tecnici** → comportamento corretto, non un bug (§3.2).
- **501 su analyze-worker** → mappatura colonne: impostare `WORKERS_COL_*` sui nomi reali (il messaggio di errore elenca le colonne disponibili).

---

## 11. Configurazione completa (`.env`)

| Variabile | Default | Effetto |
|---|---|---|
| `LOCAL_DB_URL` | — (obbligatoria) | Postgres del benchmark (letto dall'API e dagli script) |
| `EXTERNAL_JOBS_DB_URL` | — (obbligatoria) | Postgres esterno read-only (`offerte_lavoro`, `workers`) |
| `POSTINGS_TABLE` / `DATE_COLUMN` | `offerte_lavoro` / `mapping_timestamp` | Sorgente annunci per snapshot e trend |
| `DATE_FROM` / `DATE_TO` / `MIN_POSTINGS` | `2026-04-01` / ∅ / `10` | Finestra snapshot e soglia di ingresso nel benchmark |
| `TREND_WINDOW_DAYS` | `90` | Ampiezza delle due finestre del trend |
| `TREND_MIN_POSTINGS` | `30` | Sotto questo totale il trend è NULL (anti-rumore) |
| `TREND_ANCHOR_DATE` | ∅ (= data più recente) | Pin dell'àncora trend (es. `2025-10-31`) |
| `ESCO_VERSION` / `ESCO_DATA_DIR` | `v1.2.0` / `data/esco` | Pin e percorso del bundle ESCO |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-mpnet-base-v2` | Modello embedding (cambia anche il nome della cache .npz) |
| `GAP_COVER_THRESHOLD` | `0.62` | Soglia copertura ESCO (§3.2) |
| `GAP_CP2021_COVER_THRESHOLD` | `0.68` | Soglia copertura CP2021 (§3.2) |
| `HYBRID_ALPHA` | `0.5` | Peso semantico/lessicale nella classificazione offline |
| `CP2021_TOPN` | `30` | Competenze CP2021 per categoria nel materialize |
| `CP_DATASETS` / `CP_FETCH_LIMIT` | `1,2,4,5,6` / `0` | Dataset INAPP da scaricare / limite di test |
| `EXTRACTOR_URL` / `EXTRACTOR_PASSWORD` | URL interno / — | Estrattore CV (header `x-access-password`) |
| `EXTRACTOR_VERIFY_SSL` / `EXTRACTOR_CA_BUNDLE` | `true` / ∅ | Verifica TLS dell'estrattore (self-signed → `false` o CA) |
| `WORKERS_TABLE` / `WORKERS_COL_ID` / `WORKERS_COL_SKILLS` / `WORKERS_COL_ROLE` / `WORKERS_COL_TARGET_JOB` | `workers` / `worker_id` / `worker_personal_skills` / `worker_preferred_jobs` / idem | Mappatura della tabella worker esterna |
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_MODEL` | `groq` / ∅ / `llama-3.1-8b-instant` | Report LLM; chiave assente = `report: null` (tutto il resto funziona) |
| `CORS_ORIGINS` | `*` | Origin Angular ammessi (csv) |
| `API_KEY` | ∅ (= aperto) | Se impostata, `/skills-gap/*` richiedono l'header `x-api-key` |

---

## 12. Test

```bash
pytest -m "not integration"   # 52 test veloci: pure functions, scoring, coercizioni, mock — niente DB/modello
pytest -m integration         # 7 test end-to-end: richiedono DB locale su e modello scaricato
pytest                        # tutti: 59
```

Organizzazione: `tests/test_gap.py` (risoluzione target, determinismo, soglia CP2021 anti-"java→Resistenza", persistenza .npz), `tests/test_recommend.py` (formule di scoring con proprietà esplicite — es. *"un boom irraggiungibile non scavalca mai un calo raggiungibile"* — e ranking su indice finto ortogonale), `tests/test_courses.py` (soglia, ordinamento, cap, cataloghi vuoti), `tests/test_llm.py` (coercizioni dell'output LLM), `tests/test_sources.py` (pulizia skill e mappature estrattore). I test di integrazione si **auto-skippano** con motivo se DB o modello mancano: la suite veloce gira ovunque, anche in CI senza infrastruttura.

---

## 13. Limiti noti e scelte consapevoli

- **Il catalogo corsi attuale è demo** (42 righe seed): le architetture sono pronte, i dati veri no (§10.2). I suggerimenti sono plausibili ma non prenotabili.
- **I trend dipendono dalla salute dello scraper**: con la sorgente ferma (post ott-2025) vanno pinnati all'ultimo periodo sano; la crescita di quota su volumi piccoli resta più rumorosa di quella su volumi grandi anche sopra la soglia minima.
- **CP2021 ≈ 0% sui CV concreti è corretto** ma va spiegato alla UI (profilo, non checklist).
- **La risoluzione del target può mancare sinonimi italiani** assenti da benchmark e mappa `_SYNONYMS`; il sistema degrada bene (404 con candidati), ma la mappa va arricchita col tempo guardando i log (`target not resolved`).
- **L'estrattore spesso non restituisce il ruolo** → `current_job` va passato dalla UI quando noto.
- **Qualità delle skill dei worker memorizzati variabile** (righe sparse/free-text): il gap riflette la qualità dell'input.
- **Autenticazione minima** (API key condivisa opzionale, §5): adeguata dietro proxy in rete interna; per esposizioni più ampie servono rate-limit e ruoli (roadmap).
- **`score` LLM-free, report LLM-only**: scelta deliberata — i numeri sono sempre difendibili e riproducibili; il testo è un di più sacrificabile.

---

## 14. Cosa resta da fare (roadmap)

In ordine di valore/urgenza:

1. **Catalogo corsi reale** *(non è codice, è il blocco #1)*: ottenere l'export Forma.Temp/partner; al primo CSV vero: load con `--source`, `--delete-source seed`, ricalibrare `MIN_COURSE_SIM` su un campione di match a mano. Poi: fetcher automatico per la prima fonte API disponibile (Udemy affiliate quando c'è la chiave).
2. **Integrazione frontend Angular**: consumare `recommend-*` (card cliccabili → `analyze-*`), banner `target_confidence`, picker sul 404 con `candidates`, vista corsi. Il contratto è in §5.
3. **Ripristino dello scraper annunci** (fuori da questo repo) → poi togliere `TREND_ANCHOR_DATE` e schedulare `compute_trends.py` mensile.
4. **Rate-limit e ruoli sull'API** — la API key condivisa c'è (`API_KEY`, header `x-api-key`); restano il rate-limit e l'eventuale ruolo admin separato per `reload-courses` prima di esporla oltre la rete interna.
5. **Endpoint "percorso completo"**: `recommend` + `analyze` sul top-1 in una chiamata sola, per ridurre la latenza percepita della UI (due upload del PDF oggi → uno).
6. **Persistenza degli esiti**: salvare le analisi (worker, target, gap, corsi) per follow-up nel tempo ("6 mesi fa ti mancavano 8 competenze, oggi 3") e per metriche di prodotto.
7. **Miglioramenti del matching** (quando ci saranno dati di feedback): soglie differenziate per `skill_type` ESCO (knowledge vs skill/competence), eventuale cross-encoder di re-ranking sui top-k del recommend, arricchimento `_SYNONYMS` data-driven dai log dei 404.
8. **Report LLM**: valutare structured output nativo (json_schema) sui provider che lo supportano; includere nel prompt anche il trend ("il tuo settore cresce/cala") per un report più consulenziale.
9. **CI** — la suite veloce gira a ogni push (`.github/workflows/ci.yml`); resta l'eventuale job notturno con gli integration test (richiede un Postgres di servizio e il modello cacheato).
10. **Containerizzazione dell'API** con modello e `.npz` baked, healthcheck su `/health`, per allineare dev e prod.
11. **Estensione del ciclo di review anche a CP2021** (`export/import_review` oggi coprono solo l'asse ESCO).
12. **Aggiornamento di docs/MANUALE.md** (didattico): è fermo a prima dei moduli `recommend.py`/`courses.py`/trend.

---

*Ultimo aggiornamento: giugno 2026 — benchmark a 306 categorie, 59 test verdi, flusso end-to-end collaudato con CV reale.*
