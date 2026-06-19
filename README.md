# Antigravity Local 3.0 🚀

Antigravity Local 3.0 è un assistente di codifica AI locale, modulare e open-source. A differenza dei classici bot conversazionali, è progettato per interagire direttamente con il tuo computer: legge e modifica i file, esegue comandi nel terminale, usa DuckDuckGo per fare ricerche e può persino delegare compiti a sub-agenti che lavorano in background, il tutto mantenendo i tuoi dati in locale usando modelli supportati da Ollama.

## ✨ Funzionalità principali
- **Architettura Multi-Agente**: Lancia sub-agenti per compiti lunghi o di ricerca in parallelo.
- **Esecuzione Comandi & Patching File**: Legge il workspace e propone modifiche tramite una visualizzazione chiara con diff prima dell'approvazione utente.
- **Supporto Modelli Avanzato**: Routing intelligente integrato tramite LLM minori e compatibilità con i migliori modelli di Ollama (anche quelli che mischiano tag `<think>` al JSON come i derivati DeepSeek).
- **Split-Pane UI**: Un'interfaccia React interattiva a schermo diviso con rendering di Markdown, codice formattato e diagrammi Mermaid.
- **Web Browsing & Ricerca**: Trova autonomamente informazioni fresche online se ne ha bisogno.
- **Planning Mode**: Genera un piano d'azione passo-passo che puoi rivedere prima di autorizzare l'esecuzione in blocco.

## 🛠 Prerequisiti
Per eseguire Antigravity Local sul tuo PC avrai bisogno di:
- **Node.js** e **npm** per il frontend React.
- **Python 3.10+** per il backend.
- **Ollama** installato ed in esecuzione con almeno i modelli desiderati (è consigliato usare un modello piccolo per il router, es. `qwen3:1.7b`, e un modello principale potente come `gpt-oss:20b` o derivati llama/mistral).

## 📥 Installazione e Avvio

Il progetto è composto da due blocchi: il backend (Python/FastAPI) e il frontend (React/Vite). Per avviare il sistema, devi accenderli entrambi.

### 1. Avvio del Backend
Apri un terminale e naviga nella cartella `backend`:
```bash
cd backend

# Crea e attiva un ambiente virtuale
python3 -m venv venv
source venv/bin/activate  # (su Windows: venv\Scripts\activate)

# Installa le dipendenze
pip install fastapi uvicorn ollama httpx html2text duckduckgo-search

# Avvia il server FastAPI (che starà in ascolto sulla porta 8000)
python main.py
```

### 2. Avvio del Frontend
In un *altro* terminale, naviga nella cartella `frontend`:
```bash
cd frontend

# Installa tutte le librerie grafiche
npm install

# Avvia il server di sviluppo React
npm run dev
```

## 🎮 Come si usa
Una volta che entrambi i servizi sono attivi:
1. Apri il browser all'indirizzo `http://localhost:5173/`.
2. In alto a destra, clicca l'icona a forma di **cartella 📁** e digita o seleziona il percorso del tuo *workspace* (la cartella dove l'AI potrà leggere e scrivere il codice).
3. Assicurati che in alto a sinistra ci sia il nome del modello che vuoi usare o lascia acceso il Router LLM intelligente.
4. Chiedigli qualsiasi cosa: *"Fai una ricerca web e dimmi come aggiornare Vite"*, oppure *"Apri il file src/App.tsx e aggiungi un bottone blu"*. Il sistema capirà in automatico quali "Tool" utilizzare.

*Buon coding asincrono e agentico!*
