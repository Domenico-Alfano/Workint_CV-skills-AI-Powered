# Manuale tecnico — CV-skills-AI-Powered

Manuale di studio del progetto: spiega **cosa fa ogni file**, **quali librerie usa e perché**,
e la **logica** dietro ogni scelta. Pensato per imparare le librerie e i concetti, non solo
per usare il codice. I link portano alla documentazione ufficiale.

> Convenzioni: i blocchi di codice citano funzioni reali del progetto. Dove serve, spiego
> prima il *concetto* (es. "cosa è un embedding") e poi *come è usato qui*.

---

## Indice

1. [Concetti chiave (da capire prima del codice)](#1-concetti-chiave)
2. [Le librerie usate](#2-le-librerie-usate)
3. [Architettura: le due fasi](#3-architettura-le-due-fasi)
4. [Parte A — il servizio API (`app/`)](#4-parte-a--il-servizio-api-app)
   - config.py · models.py · gap.py · sources.py · llm.py · main.py
5. [Parte B — la pipeline offline (`scripts/`)](#5-parte-b--la-pipeline-offline-scripts)
6. [Il database (`sql/schema.sql`)](#6-il-database-sqlschemasql)
7. [Approfondimenti trasversali](#7-approfondimenti-trasversali)
8. [Riepilogo link documentazione](#8-riepilogo-link-documentazione)

---

## 1. Concetti chiave

Prima del codice, i concetti che tornano ovunque.

### 1.1 Embedding (rappresentazione vettoriale del testo)
Un **embedding** è un vettore di numeri (qui 768 numeri) che rappresenta il *significato* di
una frase. Un modello di NLP è addestrato in modo che frasi con significato simile abbiano
vettori "vicini" nello spazio. Esempio: `"tecniche di cottura"` e `"utilizzare tecniche di
cottura"` avranno vettori quasi identici; `"tecniche di cottura"` e `"contabilità"` molto
distanti.

Perché ci serve: dobbiamo confrontare le competenze di un CV (testo libero, scritto in mille
modi diversi) con le competenze del benchmark (etichette ESCO). Un confronto *lessicale*
(stringa uguale) fallirebbe; il confronto *semantico* via embedding coglie l'equivalenza di
significato.

Modello usato: **`paraphrase-multilingual-mpnet-base-v2`** (multilingue, ottimo in italiano).
[Scheda modello](https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2).

### 1.2 Cosine similarity (quanto due vettori sono simili)
Per misurare quanto due embedding sono "vicini" si usa la **similarità del coseno**: il
coseno dell'angolo fra i due vettori. Vale da -1 (opposti) a 1 (identici).

Formula: `cos(a,b) = (a · b) / (|a| · |b|)` dove `a · b` è il *prodotto scalare*.

Trucco del progetto: se i vettori sono **normalizzati** (lunghezza = 1, opzione
`normalize_embeddings=True`), allora `|a| = |b| = 1` e la formula si riduce al solo prodotto
scalare `a · b`. Per questo nel codice basta una moltiplicazione di matrici (`@` in NumPy)
per ottenere tutte le similarità in un colpo solo. [Spiegazione](https://en.wikipedia.org/wiki/Cosine_similarity).

### 1.3 Matching lessicale (rapidfuzz)
A volte il significato non basta: `"Magazziniere"` e `"magazzino"` condividono la radice ma
il modello multilingue può sbagliarne il ranking. Il **fuzzy matching** confronta le stringhe
a livello di caratteri (quante modifiche servono per trasformare una nell'altra). Usiamo
`rapidfuzz.fuzz.WRatio`, che restituisce 0–100. [Doc rapidfuzz](https://rapidfuzz.github.io/RapidFuzz/).

### 1.4 Match ibrido (semantico + lessicale)
La scelta vincente del progetto: combinare i due segnali.
`punteggio = ALPHA · semantico + (1-ALPHA) · lessicale` con `ALPHA = 0.5`. Il semantico coglie
i sinonimi, il lessicale coglie le radici condivise; insieme sono molto più robusti.

### 1.5 ESCO e CP2021 (i due benchmark)
- **ESCO**: classificazione UE di occupazioni e competenze. Ogni occupazione ha competenze
  *essenziali* e *opzionali*. Multilingue, scaricabile. [Sito](https://esco.ec.europa.eu/).
- **CP2021** (ISTAT): classificazione italiana delle professioni. Le competenze NON sono nel
  file: vengono da una **API INAPP**. [ISTAT CP2021](https://www.istat.it/it/archivio/18132) ·
  [INAPP professioni](https://www.inapp.gov.it/professioni/).

### 1.6 Deterministico vs LLM
Il **gap** (quali competenze mancano) è *deterministico*: stesso input → stesso output,
nessuna "fantasia". Solo il **report narrativo** finale usa un LLM. Questa separazione è una
scelta di affidabilità: le affermazioni sulle competenze sono difendibili perché basate su
tassonomie ufficiali, non generate da un modello.

---

## 2. Le librerie usate

| Libreria | A cosa serve qui | Documentazione |
|---|---|---|
| **FastAPI** | Framework per esporre l'API REST (i 2 endpoint) | https://fastapi.tiangolo.com/ |
| **Uvicorn** | Server ASGI che esegue FastAPI | https://www.uvicorn.org/ |
| **Pydantic** | Validazione + serializzazione dei modelli dati (il "contratto" JSON) | https://docs.pydantic.dev/ |
| **SQLAlchemy** | Accesso al database Postgres (query, engine) | https://docs.sqlalchemy.org/ |
| **psycopg2** | Driver Postgres usato da SQLAlchemy | https://www.psycopg.org/docs/ |
| **sentence-transformers** | Genera gli embedding semantici | https://www.sbert.net/ |
| **Hugging Face** | Hub da cui si scarica il modello | https://huggingface.co/docs |
| **rapidfuzz** | Similarità lessicale (fuzzy matching) | https://rapidfuzz.github.io/RapidFuzz/ |
| **NumPy** | Algebra vettoriale (prodotti scalari, argmax) | https://numpy.org/doc/ |
| **pandas** | Lettura CSV/Excel e dei risultati SQL nella pipeline | https://pandas.pydata.org/docs/ |
| **openpyxl** | Backend che permette a pandas di leggere `.xlsx` | https://openpyxl.readthedocs.io/ |
| **requests** | Chiamata HTTP all'estrattore di CV | https://requests.readthedocs.io/ |
| **openai** (SDK) | Client per l'LLM (Groq via API OpenAI-compatibile) | https://github.com/openai/openai-python |
| **python-dotenv** | Carica le variabili da `.env` | https://saurabh-kumar.com/python-dotenv/ |
| Stdlib: `functools`, `json`, `re`, `pathlib`, `csv`, `urllib`, `hashlib`, `os`, `time` | utility varie | https://docs.python.org/3/library/ |

---

## 3. Architettura: le due fasi

**Fase A — costruzione del benchmark (offline, periodica).** Gli script in `scripts/` leggono
gli annunci reali (`offerte_lavoro`), estraggono le categorie di lavoro, le mappano su ESCO e
CP2021, e scrivono la tabella finale `job_benchmark` (una riga per categoria). Nessun LLM,
riproducibile.

**Fase B — analisi di un lavoratore (online, per richiesta).** Il servizio `app/` riceve un
CV (PDF) o un id lavoratore, ne ricava le competenze, le confronta con il benchmark del lavoro
target e restituisce il gap + un report LLM.

```
FASE A (scripts/):  offerte_lavoro ─► job_category ─► [ESCO + CP2021] ─► job_benchmark
FASE B (app/):      CV/worker ─► competenze ─► confronto vs job_benchmark ─► gap + report
```

---

## 4. Parte A — il servizio API (`app/`)

Pacchetto Python (`app/__init__.py` lo rende importabile). Sei moduli. Li spiego nell'ordine
in cui conviene leggerli.

### 4.1 `app/config.py` — configurazione e risorse condivise

**Scopo.** Centralizza la lettura della configurazione (da `.env`) e crea le risorse "pesanti"
(connessione DB, modello di embedding) **una sola volta**.

**Concetti e librerie:**

- **`python-dotenv`** → `load_dotenv(ROOT / ".env")` legge il file `.env` e mette le variabili
  in `os.environ`. Così i segreti (password, chiavi) non sono nel codice.
  [Doc](https://saurabh-kumar.com/python-dotenv/).
- **`pathlib.Path`** → `ROOT = Path(__file__).resolve().parent.parent` calcola il percorso
  della cartella radice in modo indipendente dal sistema operativo. `__file__` è il path del
  modulo corrente; `.resolve()` lo rende assoluto; due `.parent` salgono da `app/config.py`
  alla radice. [Doc pathlib](https://docs.python.org/3/library/pathlib.html).
- **`os.getenv("X", default)`** → legge una variabile d'ambiente con un valore di fallback.
- **`functools.lru_cache(maxsize=1)`** → è il punto chiave. Decora le funzioni `engine()`,
  `external_engine()`, `model()`. "LRU cache" = memorizza il risultato della prima chiamata e
  lo riusa per tutte le successive. Con `maxsize=1` significa: *calcola una volta, poi
  restituisci sempre lo stesso oggetto* (pattern "singleton"). È fondamentale per `model()`:
  caricare il modello mpnet costa ~400MB e diversi secondi; senza cache lo ricaricheremmo a
  ogni richiesta. [Doc lru_cache](https://docs.python.org/3/library/functools.html#functools.lru_cache).

```python
@lru_cache(maxsize=1)
def model():
    from sentence_transformers import SentenceTransformer   # import "lazy": vedi sotto
    return SentenceTransformer(EMBEDDING_MODEL)
```

- **Import "lazy"** (import dentro la funzione invece che in cima al file): `SentenceTransformer`
  importa `torch`, che è pesante. Mettendolo dentro `model()`, il semplice `import config` (per
  esempio in un test) non carica torch finché non serve davvero un embedding.
- **SQLAlchemy `create_engine(url)`** → crea un "engine", cioè un *pool di connessioni* verso
  Postgres. Non apre subito una connessione: la apre al primo uso. Due engine distinti:
  `engine()` (DB locale del benchmark) e `external_engine()` (DB esterno `workint-clone` con
  `workers` e `offerte_lavoro`). [Doc engine](https://docs.sqlalchemy.org/en/20/core/engines.html).

**Variabili importanti definite qui:** `COVER_THRESHOLD` (soglia 0.62 per dire "competenza
coperta"), `EXTRACTOR_URL`/`EXTRACTOR_PASSWORD`/`EXTRACTOR_VERIFY` (estrattore CV),
`LLM_PROVIDER`/`LLM_API_KEY`/`LLM_MODEL`/`LLM_ENABLED`, `CORS_ORIGINS`, `WORKERS_TABLE`.

Nota su `EXTRACTOR_VERIFY`: l'host dell'estrattore usa un certificato *self-signed*; la
variabile permette di disattivare la verifica TLS (`verify=False`) o puntare a un CA bundle.

---

### 4.2 `app/models.py` — il contratto dati (Pydantic)

**Scopo.** Definisce la *forma* dei dati: cosa entra e cosa esce dall'API. Sono classi
**Pydantic** (`BaseModel`): FastAPI le usa per (a) validare automaticamente l'input, (b)
serializzare l'output in JSON, (c) generare la documentazione Swagger.
[Doc Pydantic models](https://docs.pydantic.dev/latest/concepts/models/).

**Concetto: validazione dichiarativa.** Dichiari i tipi (`str`, `int`, `list[str]`,
`Optional[float]`) e Pydantic garantisce che i dati li rispettino, sollevando errori chiari
altrimenti. `Field(description=...)` aggiunge documentazione che appare in Swagger.

**Le classi:**

- `WorkerProfile` → profilo interno del lavoratore. Solo due campi usati: `skills` (lista di
  competenze) e `role` (titolo, usato come fallback per il lavoro target). *Nota didattica:*
  in passato aveva anche `experience/education/languages`, rimossi perché calcolati ma mai
  usati a valle ("dead code").
- `SkillMatch` → una competenza del benchmark *coperta*: `skill` (etichetta benchmark),
  `matched_with` (la competenza del CV che l'ha coperta), `score` (similarità).
- `BenchmarkGap` → il gap rispetto a UNA tassonomia: `n_total`, `n_covered`, `coverage_pct`,
  `covered` (lista di `SkillMatch`), `missing` (lista di etichette mancanti).
- `Report` → il report LLM strutturato: `strengths`, `gaps`, `formation` (lista di
  suggerimenti). Strutturato apposta perché il frontend possa stilizzare ogni sezione.
- `GapResult` → la risposta completa dell'API: `category_id`, `job_category`,
  `target_confidence` (None se match esatto; un numero < 1 se "indovinato" → il FE chiede
  conferma), `n_worker_skills`, `esco` e `cp2021` (due `BenchmarkGap`), `report` (None se LLM
  spento).

---

### 4.3 `app/gap.py` — il motore del gap (cuore deterministico)

Il file più importante. Calcola il gap fra le competenze del lavoratore e il benchmark, e
risolve il lavoro target. Vediamo per blocchi.

**(a) Import e costanti.**
- `numpy as np` per l'algebra vettoriale; `rapidfuzz.fuzz` per il lessicale;
  `sqlalchemy.text` per scrivere SQL grezzo in modo sicuro (parametri legati con `:nome`).
- `RESOLVE_ALPHA = 0.5` (peso semantico/lessicale), `RESOLVE_MIN_SCORE = 0.55` (sotto questa
  soglia il lavoro target è "non trovato").
- `_SYNONYMS`: lista di coppie `(radice_italiana, etichetta_benchmark)`. Serve perché il
  benchmark (costruito da annunci, spesso in inglese) contiene "Software Developer" ma un
  lavoratore scrive "Sviluppatore". Una mappa di sinonimi risolve i casi più comuni che il
  matcher sbaglierebbe (es. "sviluppator" → "Software Developer").

**(b) `_category_index()` — indice cache delle categorie.**
```python
@lru_cache(maxsize=1)
def _category_index():
    rows = engine().connect().execute(text("SELECT category_id, job_category FROM job_benchmark ...")).all()
    ...
    emb = model().encode(labels, normalize_embeddings=True)
    return ids, labels, np.asarray(emb)
```
Carica una volta tutte le categorie del benchmark e ne calcola gli embedding. Grazie a
`lru_cache` questo lavoro (encoding di ~300 etichette) avviene al primo uso e poi è gratis.
`model().encode(...)` è la chiamata di sentence-transformers che trasforma testo → vettori.
[Doc encode](https://www.sbert.net/docs/package_reference/SentenceTransformer.html#sentence_transformers.SentenceTransformer.encode).

**(c) `resolve_category(job_text)` — dal titolo libero alla categoria benchmark.**
Logica a due stadi:
1. *Pass sinonimi*: se il testo contiene una radice nota (`_SYNONYMS`), mappa direttamente
   all'etichetta target (confidence 1.0).
2. *Pass ibrido*: altrimenti calcola `sem` (coseno via prodotto scalare `emb @ q`) e `lex`
   (rapidfuzz WRatio /100) su tutte le categorie, le combina con `ALPHA`, prende l'`argmax`.
   Se il punteggio è sotto `RESOLVE_MIN_SCORE` ritorna `(None, None, score)` → "non trovato".

`emb @ q` è il prodotto matrice-vettore di NumPy: `emb` ha forma (N_categorie, 768), `q` è
(768,), il risultato è (N_categorie,) con la similarità di `q` verso ogni categoria. Funziona
come coseno perché i vettori sono normalizzati (vedi §1.2). [Doc np matmul](https://numpy.org/doc/stable/reference/generated/numpy.matmul.html).

**(d) `_labels(jsonb_value)` — estrae le etichette dal JSONB.**
Le competenze nel DB sono salvate come JSON (`[{uri,label,type}, ...]`). psycopg2 può
restituirlo già come lista Python o come stringa: la funzione gestisce entrambi i casi e
ritorna solo le `label`.

**(e) `_load_benchmark(category_id, job_category)` — recupera la riga di benchmark.**
- Se è dato `category_id` → query diretta per id.
- Se è dato `job_category` → prima prova un match *esatto* (case-insensitive); se non esiste,
  chiama `resolve_category` (fuzzy). Aggiunge `_target_confidence` al dizionario risultato.
- `text(select + where)` con parametri legati (`:v`) → query parametrizzata, sicura contro
  SQL injection. `.mappings().first()` restituisce la prima riga come dizionario.
  [Doc SQLAlchemy text()](https://docs.sqlalchemy.org/en/20/core/sqlelement.html#sqlalchemy.sql.expression.text).

**(f) `_gap(...)` — il calcolo vero del gap (per una tassonomia).**
Riceve la matrice di similarità `sims` di forma (N_competenze_benchmark, N_competenze_worker).
Per ogni competenza del benchmark:
```python
j = int(np.argmax(sims[i]))     # la competenza del CV più simile
score = float(sims[i][j])
if score >= COVER_THRESHOLD:     # 0.62
    covered.append(SkillMatch(skill=..., matched_with=worker_skills[j], score=...))
else:
    missing.append(skill)
```
`np.argmax(sims[i])` trova *l'indice* del valore massimo nella riga i → la competenza del CV
che meglio "copre" quella del benchmark. Se la migliore copertura supera la soglia, è
"coperta", altrimenti "mancante". `coverage_pct` = coperte/totali · 100.
[Doc argmax](https://numpy.org/doc/stable/reference/generated/numpy.argmax.html).

**(g) `analyze(...)` — orchestrazione.**
1. Carica il benchmark (`_load_benchmark`).
2. Costruisce le liste etichette ESCO (essenziali+opzionali) e CP2021.
3. Calcola gli embedding di tutte le competenze (worker + benchmark) e la matrice di
   similarità `sims_all = b @ w.T` (forma N_benchmark × N_worker) in **una sola
   moltiplicazione di matrici** — efficiente.
4. La spezza nelle due sezioni (ESCO / CP2021) e chiama `_gap` su ciascuna.
5. Chiama `generate_report` (LLM) e assembla `GapResult`.

Nota: l'import di `generate_report` è *dentro* la funzione per evitare import circolari
(gap ↔ llm) e per non caricare l'SDK OpenAI se non serve.

---

### 4.4 `app/sources.py` — adattatori di input (i due flussi)

**Scopo.** Trasformare le due sorgenti (CV-PDF e tabella `workers`) in un `WorkerProfile`
comune. È lo strato che "normalizza" input diversi in una forma unica.

**Flusso 1 — estrattore CV:**
- `_SKILL_KEYS`, `_ROLE_KEYS`: liste di chiavi possibili nell'output dell'estrattore (es.
  `competenze_tecniche`, `competenze_soft`). Il mapper è *tollerante*: prova più chiavi.
- `_as_skill_list(v)`: normalizza un valore in lista di competenze pulite. Gestisce: liste di
  stringhe, liste di dict (estrae `name/label/...`), o una stringa con elenco puntato. Con
  `re.sub` rimuove i marcatori di lista (`- `, `* `) e l'enfasi markdown (`**`).
  [Doc re](https://docs.python.org/3/library/re.html).
- `profile_from_extracted(data)`: applica le chiavi sopra e costruisce il `WorkerProfile`.
  `dict.fromkeys(skills)` è un trucco per **deduplicare mantenendo l'ordine** (i dict Python
  3.7+ conservano l'ordine d'inserimento).
- `call_extractor(file_bytes, filename)`: fa la **POST HTTP** all'estrattore con `requests`.
  - `files={"file": (filename, file_bytes, "application/pdf")}` invia un `multipart/form-data`
    (upload di file). [Doc requests file upload](https://requests.readthedocs.io/en/latest/user/quickstart/#post-a-multipart-encoded-file).
  - header `x-access-password` solo se la password è impostata.
  - `verify=EXTRACTOR_VERIFY` gestisce il certificato self-signed.
  - `timeout=120` perché l'estrattore fa OCR e può essere lento.
  - solleva `ExtractorError` su errori di rete o status ≠ 200.

**Flusso 2 — tabella `workers`:**
- `_WORKER_COLS`: mappa nomi logici → colonne reali (`worker_personal_skills`,
  `worker_preferred_jobs`, ...). Sovrascrivibili via env (`WORKERS_COL_*`). Le colonne PII
  (nome, email, telefono) **non vengono mai lette** (privacy/GDPR).
- `load_worker(worker_id)`:
  1. Legge da `information_schema.columns` quali colonne esistono (controllo difensivo).
  2. Se mancano le colonne attese solleva `WorkersSchemaUnknown`.
  3. Seleziona solo le colonne presenti, recupera la riga, costruisce il `WorkerProfile`.
  4. Ritorna `(profile, target_job)` dove il target è il lavoro preferito (o il ruolo).
- Eccezioni dedicate (`WorkerNotFound`, `WorkersSchemaUnknown`) per dare al chiamante codici
  HTTP precisi.

**Concetto: `information_schema`.** È uno schema standard SQL che descrive il database stesso
(quali tabelle/colonne esistono). Interrogarlo prima di leggere rende il codice robusto a
schemi diversi. [Postgres information_schema](https://www.postgresql.org/docs/current/information-schema.html).

---

### 4.5 `app/llm.py` — generazione del report narrativo

**Scopo.** Produce il `Report` (punti di forza, lacune, formazione) usando un LLM. Disegnato
per essere **agnostico al provider**: Groq oggi, OpenAI domani, senza cambiare codice.

**Concetti e librerie:**
- **SDK `openai`** usato anche per **Groq**: Groq espone un'API *OpenAI-compatibile*, quindi
  basta cambiare `base_url`. `_BASE_URLS` mappa il provider all'URL (None = OpenAI default).
  [openai-python](https://github.com/openai/openai-python) · [Groq OpenAI compat](https://console.groq.com/docs/openai).
- `_client()` con `lru_cache` → crea il client una volta sola.
- **`from __future__ import annotations`** + `TYPE_CHECKING`: trucco per usare i tipi
  (`GapResult`, `Report`) negli annotation senza importarli davvero a runtime → evita import
  circolari (llm ↔ models/gap). [Doc](https://docs.python.org/3/library/typing.html#typing.TYPE_CHECKING).
- **Prompt**: una stringa che chiede al modello di rispondere *solo* con JSON
  (`strengths`, `gaps`, `formation`). `response_format={"type":"json_object"}` chiede output
  JSON. `temperature=0.4` = poca creatività (più stabile). `max_tokens=600` = lunghezza max.
  [Doc chat completions](https://platform.openai.com/docs/api-reference/chat/create).
- **Robustezza dell'output** (importante): gli LLM piccoli a volte *non rispettano* il formato
  (es. restituiscono `formation` come lista di oggetti `{nome, durata}` invece di stringhe, o
  `strengths` come dict). Le funzioni `_to_str` e `_to_str_list` *coercono* qualsiasi forma
  (dict/list/str) in stringa/lista-di-stringhe, così Pydantic non solleva errori. È un esempio
  reale di "difensività": non fidarsi mai ciecamente dell'output di un LLM.
- `re.sub(r"^```...", ...)` rimuove eventuali "fence" markdown attorno al JSON.

Se `LLM_API_KEY` non è impostata, `generate_report` ritorna `None` → l'API funziona comunque
(il campo `report` sarà `null`).

---

### 4.6 `app/main.py` — l'applicazione FastAPI (i 2 endpoint)

**Scopo.** Definisce l'app web e i due endpoint. È il "bordo" del sistema.

**Concetti e librerie:**
- **FastAPI** (`app = FastAPI(...)`): crea l'applicazione. I decoratori `@app.post(...)`,
  `@app.get(...)` registrano le funzioni come endpoint. `response_model=GapResult` dice a
  FastAPI di validare/serializzare l'output secondo quel modello e di documentarlo in Swagger.
  [Doc first steps](https://fastapi.tiangolo.com/tutorial/first-steps/).
- **CORS** (`CORSMiddleware`): permette al frontend Angular (su un altro dominio) di chiamare
  l'API dal browser. Senza CORS il browser bloccherebbe le richieste cross-origin.
  [Doc CORS](https://fastapi.tiangolo.com/tutorial/cors/).
- **Tipi dei parametri**:
  - `file: UploadFile = File(...)` → upload di file multipart (richiede `python-multipart`).
    [Doc file upload](https://fastapi.tiangolo.com/tutorial/request-files/).
  - `target_category_id: Optional[int] = Query(None)` → parametro di query string opzionale.
    [Doc query params](https://fastapi.tiangolo.com/tutorial/query-params/).
  - `worker_id: int` nel path → parametro di percorso. FastAPI converte e valida il tipo.
- **`HTTPException`**: per restituire codici di errore puliti (404 target non trovato, 422 nessuna
  competenza, 502 estrattore fallito, 501 schema workers sconosciuto). Le eccezioni del motore
  (es. `TargetNotFound`) vengono tradotte qui in HTTP. [Doc errori](https://fastapi.tiangolo.com/tutorial/handling-errors/).
- `_run(...)`: piccola funzione che incapsula la chiamata a `analyze` e traduce
  `TargetNotFound` → HTTP 404. Evita ripetizioni fra i due endpoint.

**Flusso `analyze-cv`**: legge il PDF → `call_extractor` → `profile_from_extracted` → `_run`.
**Flusso `analyze-worker`**: `load_worker` → `_run` (con il lavoro target del lavoratore).

**`GET /health`**: endpoint banale per i controlli di "liveness" (load balancer, demo warm-up).

---

## 5. Parte B — la pipeline offline (`scripts/`)

Questi script costruiscono il benchmark. Si eseguono nell'ordine indicato nel README. Usano
**pandas** (lettura dati) e **SQLAlchemy** (DB). Nota: hanno il proprio `db.py` (separato da
`app/config.py`) perché sono un contesto distinto dall'API.

### 5.1 `scripts/db.py` — utility condivise della pipeline
- Carica `.env`, espone `local_engine()` / `external_engine()` (come in config.py) e le
  costanti della finestra di snapshot (`POSTINGS_TABLE`, `DATE_COLUMN`, `DATE_FROM`,
  `MIN_POSTINGS`, ...).
- `safe_identifier(name)`: valida con regex che un nome di tabella/colonna sia un identificatore
  SQL legittimo. Serve perché alcuni nomi (tabella postings) sono interpolati nelle query e non
  possono essere parametri legati; la validazione previene injection. [regex](https://docs.python.org/3/library/re.html#re.fullmatch).

### 5.2 `scripts/init_db.py` — crea lo schema
- Legge `sql/schema.sql` e lo esegue con `conn.exec_driver_sql(schema)` (psycopg2 esegue più
  statement insieme). Usa `CREATE TABLE IF NOT EXISTS` → idempotente, sicuro da rieseguire.

### 5.3 `scripts/load_esco.py` — carica ESCO
- Legge tre CSV (occupazioni, competenze, relazioni) con `pandas.read_csv`.
  [Doc read_csv](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html).
- `_col(df, *names)`: prende la prima colonna esistente fra più nomi possibili (tollerante a
  variazioni dello schema ESCO).
- Normalizza i nomi colonna verso il nostro schema, fa `TRUNCATE` e ricarica
  (`DataFrame.to_sql(..., if_exists="append")`). Tutto taggato con `ESCO_VERSION`.
  [Doc to_sql](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.to_sql.html).
- Difensivo: tiene solo le relazioni i cui estremi (occupazione/competenza) esistono davvero.

### 5.4 `scripts/load_cp2021.py` — carica CP2021
- Legge il foglio `quinto_digit` dell'Excel (813 professioni) con `pandas.read_excel`
  (richiede **openpyxl**). [Doc read_excel](https://pandas.pydata.org/docs/reference/api/pandas.read_excel.html).
- Legge anche il foglio 6° digit ("voci professionali"): titoli specifici usati come
  *etichette alternative* (come le altLabels ESCO) per migliorare il matching. Deriva il
  `cod_5` (5 livelli) dal codice 6 livelli con `str.split(".").str[:5].str.join(".")`.
- Popola `cp2021_profession` e `cp2021_label`.

### 5.5 `scripts/mirror_categories.py` — snapshot delle categorie
- Interroga `offerte_lavoro` sul DB esterno entro la finestra temporale (`DATE_FROM`...),
  raggruppa per `job_category` e conta gli annunci (`pandas.read_sql`).
  [Doc read_sql](https://pandas.pydata.org/docs/reference/api/pandas.read_sql.html).
- Marca `in_benchmark = posting_count >= MIN_POSTINGS` (costruiamo benchmark solo per le
  categorie con abbastanza annunci). Registra la finestra usata → riproducibilità.

### 5.6 `scripts/classify_categories.py` — categoria → occupazione ESCO (match ibrido)
Lo script più "intelligente". Spiegato passo passo:
1. Carica occupazioni ESCO con `preferred_label_it` + `alt_labels_it`.
2. **Appiattisce** in una lista (etichetta → occupazione): preferita + ogni altLabel (split su
   `\n`). Indicizzare *tutte* le etichette è cruciale per il recall: i termini generici che
   una categoria usa spesso stanno nelle altLabels, non nell'etichetta preferita.
3. Calcola gli embedding di tutte le etichette e di tutte le categorie; la matrice semantica è
   `sem = cat_emb @ lab_emb.T`.
4. Calcola la matrice lessicale con `rapidfuzz.process.cdist(..., scorer=fuzz.WRatio,
   workers=-1)` — `cdist` confronta tutte le coppie in C, molto veloce; `workers=-1` usa tutti
   i core. [Doc cdist](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html#cdist).
5. `combined = ALPHA*sem + (1-ALPHA)*lex`.
6. Per ogni categoria: ordina le etichette per punteggio (`np.argsort(-combined[i])`), tiene la
   **migliore etichetta per occupazione distinta** → top-5 candidati. Salva tutti i candidati
   in `candidates_considered` (JSONB) per audit, e segna `needs_review` se il top < `MIN_SCORE`
   (0.70).
7. Scrive `job_occupation_map`.

*Perché ibrido + altLabels:* la storia del progetto mostra che il solo modello leggero
sbagliava ("Magazziniere"→"smaltatore"); modello forte + lessicale + altLabels ha risolto.

### 5.7 `scripts/classify_cp2021.py` — categoria → professione CP2021
Stessa logica del 5.6 ma verso `cp2021_label` (nome_5 + voci professionali); scrive
`job_cp2021_map`.

### 5.8 `scripts/fetch_cp2021_skills.py` — competenze CP2021 dall'API INAPP
- Per ogni `cod_5` mappato, chiama l'API INAPP `survey.php?codice=...&idDataset=N` con
  `urllib.request` (stdlib HTTP). [Doc urllib.request](https://docs.python.org/3/library/urllib.request.html).
- Gli `idDataset` sono sezioni O*NET (1=compiti, 2=conoscenze, 4/5=skill, 6=attività).
- `_iter_dims(data)` gestisce le due forme JSON che l'API restituisce (dict di dimensioni o
  lista) e produce `(dim_code, label, importanza, complessita)`.
- Inserisce in `cp2021_profession_skill` con `ON CONFLICT DO NOTHING` (idempotente).
  `time.sleep(0.05)` fra le chiamate = cortesia verso l'API.

### 5.9 `scripts/export_review.py` / `import_review.py` — revisione umana
- `export_review.py`: esporta in CSV i mapping categoria→ESCO con i top-5 candidati e un
  flag `needs_review`, ordinati per priorità. Usa il modulo **csv** della stdlib (encoding
  `utf-8-sig` per aprire bene in Excel). [Doc csv](https://docs.python.org/3/library/csv.html).
- `import_review.py`: rilegge il CSV corretto a mano (colonna `pick` 1-5 o `correct_uri`) e
  aggiorna `job_occupation_map` (metodo `manual`, `reviewed=true`). È l'anello "human-in-the-loop".

### 5.10 `scripts/materialize_benchmark.py` — costruisce `job_benchmark`
- Esegue **una INSERT...SELECT in puro SQL** che unisce `job_occupation_map` con
  `esco_occupation_skill` e aggrega le competenze in JSON con `jsonb_agg(jsonb_build_object(...))`.
  Fare l'aggregazione nel DB è molto più efficiente che in Python.
  [Doc jsonb funcs](https://www.postgresql.org/docs/current/functions-json.html).
- Poi una UPDATE riempie la sezione CP2021: una CTE `WITH ranked AS (... row_number() OVER
  (PARTITION BY cod_5 ORDER BY importanza DESC) ...)` prende le top-N competenze per professione.
  `row_number()` è una *window function*. [Doc window functions](https://www.postgresql.org/docs/current/tutorial-window.html).
- Risultato: una riga per categoria con competenze ESCO essenziali/opzionali + competenze CP2021.

---

## 6. Il database (`sql/schema.sql`)

Tabelle principali:
- `job_category` — categorie distinte dagli annunci (+ conteggio, flag `in_benchmark`).
- `esco_occupation`, `esco_skill`, `esco_occupation_skill` — snapshot ESCO (occupazioni,
  competenze, relazioni essenziali/opzionali).
- `cp2021_profession`, `cp2021_label`, `cp2021_profession_skill` — dati CP2021/INAPP.
- `job_occupation_map`, `job_cp2021_map` — i due mapping (con audit `candidates_considered`).
- **`job_benchmark`** — la tabella finale letta dall'API (una riga per categoria).

**Concetto: JSONB.** Postgres permette colonne **JSONB** (JSON binario, indicizzabile): le liste
di competenze sono salvate così invece che in tabelle separate, perché si leggono/scrivono come
un blocco unico. [Doc JSONB](https://www.postgresql.org/docs/current/datatype-json.html).

**Concetto: chiavi esterne (`REFERENCES`).** Garantiscono integrità referenziale (non puoi
mappare una categoria a un'occupazione inesistente).

---

## 7. Approfondimenti trasversali

### 7.1 Perché `@` (matmul) invece di un ciclo
Calcolare le similarità con due cicli annidati sarebbe lentissimo in Python. NumPy delega la
moltiplicazione di matrici a codice C/BLAS ottimizzato: `b @ w.T` calcola *tutte* le coppie
benchmark×worker in una chiamata. È il motivo per cui si usano matrici e non liste.

### 7.2 Embedding normalizzati = coseno gratis
`normalize_embeddings=True` rende ogni vettore di lunghezza 1. Allora il prodotto scalare *è*
il coseno. Senza normalizzazione dovremmo dividere per le norme ogni volta.

### 7.3 `lru_cache` come singleton
Usato per modello, engine, indice categorie, client LLM. Pattern ricorrente: "calcola una
volta, riusa sempre". Evita di ricaricare risorse costose ad ogni richiesta.

### 7.4 Import "lazy" e `TYPE_CHECKING`
Import pesanti (torch, openai) dentro le funzioni, e tipi solo-annotazione sotto
`TYPE_CHECKING`: riduce tempo di avvio e rompe i cicli di import.

### 7.5 Determinismo per affidabilità
Il gap è riproducibile; l'LLM interviene solo per la *narrazione*. Le competenze provengono da
tassonomie ufficiali (ESCO/CP2021) → le affermazioni del report sono difendibili.

### 7.6 Difensività verso input esterni
Tre esempi reali nel codice: (a) `_as_skill_list` accetta liste/dict/stringhe;
(b) `call_extractor` gestisce timeout/SSL/status; (c) `llm.py` coerce qualsiasi forma JSON.
Regola: non fidarsi mai del formato di dati esterni (estrattore, LLM, DB esterno).

---

## 8. Riepilogo link documentazione

**Framework & API**
- FastAPI — https://fastapi.tiangolo.com/
- Uvicorn — https://www.uvicorn.org/
- Pydantic — https://docs.pydantic.dev/
- Starlette (sotto FastAPI) — https://www.starlette.io/

**Dati & DB**
- SQLAlchemy 2.0 — https://docs.sqlalchemy.org/en/20/
- psycopg2 — https://www.psycopg.org/docs/
- PostgreSQL JSON/JSONB — https://www.postgresql.org/docs/current/datatype-json.html
- PostgreSQL window functions — https://www.postgresql.org/docs/current/tutorial-window.html
- pandas — https://pandas.pydata.org/docs/
- openpyxl — https://openpyxl.readthedocs.io/

**NLP / matching**
- sentence-transformers (SBERT) — https://www.sbert.net/
- Modello mpnet multilingue — https://huggingface.co/sentence-transformers/paraphrase-multilingual-mpnet-base-v2
- rapidfuzz — https://rapidfuzz.github.io/RapidFuzz/
- NumPy — https://numpy.org/doc/
- Cosine similarity — https://en.wikipedia.org/wiki/Cosine_similarity

**LLM**
- openai-python SDK — https://github.com/openai/openai-python
- Groq (OpenAI-compatible) — https://console.groq.com/docs/openai

**HTTP & utility**
- requests — https://requests.readthedocs.io/
- python-dotenv — https://saurabh-kumar.com/python-dotenv/
- Python stdlib — https://docs.python.org/3/library/

**Tassonomie**
- ESCO — https://esco.ec.europa.eu/
- ISTAT CP2021 — https://www.istat.it/it/archivio/18132
- INAPP professioni — https://www.inapp.gov.it/professioni/
