from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import ollama
import asyncio
import uuid
import os
import json
import re
import difflib
import warnings
from typing import Optional, List, Dict, Any

warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── State ────────────────────────────────────────────────────────────────────
pending_tools: Dict[str, Any] = {}       # comandi/patch/plan in attesa
background_tasks: Dict[str, Any] = {}   # task asincroni
subagent_results: Dict[str, Any] = {}   # risultati subagenti

ROUTER_MODEL = "qwen3:1.7b"

# ─── Models ───────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]
    model: str = "qwen3:8b"
    workspace: Optional[str] = None
    use_router: bool = True

class ApproveRequest(BaseModel):
    session_id: str
    approved: bool
    user_note: Optional[str] = None  # nota opzionale per patch rifiutate

# ─── Tool definitions ─────────────────────────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Esegue un comando bash nel terminale locale. Richiede approvazione utente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string", "description": "Comando bash da eseguire"},
                    "background": {"type": "boolean", "description": "Se true, esegue in background e ritorna subito un task_id"}
                },
                "required": ["cmd"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "Elenca file e cartelle in un percorso. Usa '.' per la directory workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso cartella (es. '.' o 'src/')"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Legge il contenuto completo di un file di testo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso del file"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Crea o sovrascrive un file con il contenuto dato. Richiede approvazione utente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso del file da creare/sovrascrivere"},
                    "content": {"type": "string", "description": "Contenuto completo del file"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "patch_file",
            "description": "Modifica chirurgica: sostituisce una stringa esatta in un file. Richiede approvazione utente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Percorso del file"},
                    "old_content": {"type": "string", "description": "La stringa ESATTA da sostituire"},
                    "new_content": {"type": "string", "description": "La nuova stringa che la sostituisce"}
                },
                "required": ["path", "old_content", "new_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Cerca informazioni su internet tramite DuckDuckGo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Termini di ricerca"},
                    "max_results": {"type": "integer", "description": "Numero massimo di risultati (default 5)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": "Scarica e legge il contenuto testuale di una pagina web o documentazione.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL completo della pagina da leggere"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_artifact",
            "description": "Crea o aggiorna un documento/artefatto nel pannello laterale dell'interfaccia. Usalo per piani, analisi, documentazione, file code. Supporta Markdown con blocchi di codice e diagrammi Mermaid.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titolo dell'artefatto"},
                    "content": {"type": "string", "description": "Contenuto in Markdown"}
                },
                "required": ["title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Crea un piano di implementazione da mostrare all'utente per approvazione PRIMA di procedere con modifiche distruttive.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Titolo del piano"},
                    "description": {"type": "string", "description": "Spiegazione del problema e della soluzione"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista ordinata dei passi da eseguire"
                    }
                },
                "required": ["title", "description", "steps"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Lancia un agente secondario in background per completare un sotto-compito autonomamente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Descrizione completa del compito da delegare al subagente"},
                    "agent_id": {"type": "string", "description": "ID univoco per tracciare questo subagente (es. 'research-1')"},
                    "model": {"type": "string", "description": "Modello da usare per il subagente (default: il modello corrente)"}
                },
                "required": ["task", "agent_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "git_snapshot",
            "description": "Salva lo stato corrente del workspace con un commit Git (snapshot). Usa prima di modifiche importanti.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Messaggio descrittivo del commit"}
                },
                "required": ["message"]
            }
        }
    }
]

# ─── Helper: risolvi percorso relativo al workspace ───────────────────────────
def resolve_path(path: str, workspace: Optional[str]) -> str:
    if os.path.isabs(path):
        return path
    if workspace:
        return os.path.join(workspace, path)
    return path

# ─── Helper: estrai tool call da oggetto Ollama ───────────────────────────────
def extract_tool_info(tool_call):
    if hasattr(tool_call, "function"):
        return tool_call.function.name, getattr(tool_call.function, "arguments", {})
    if "function" in tool_call:
        return tool_call["function"]["name"], tool_call["function"].get("arguments", {})
    return tool_call.get("name"), tool_call.get("arguments", {})

# ─── Helper: converti msg Ollama in dict ─────────────────────────────────────
def msg_to_dict(msg_obj) -> dict:
    if hasattr(msg_obj, "model_dump"):
        d = msg_obj.model_dump()
    else:
        d = dict(msg_obj)
    # Serializza tool_calls se presenti
    if d.get("tool_calls"):
        serialized = []
        for tc in d["tool_calls"]:
            if hasattr(tc, "function"):
                serialized.append({
                    "function": {
                        "name": tc.function.name,
                        "arguments": dict(tc.function.arguments)
                    }
                })
            else:
                serialized.append(tc)
        d["tool_calls"] = serialized
    return d

# ─── Feature 0: Router LLM ───────────────────────────────────────────────────
async def route_request(user_message: str, available_models: List[str], workspace: Optional[str]) -> Dict[str, str]:
    """Usa il modello piccolo per scegliere il modello giusto e arricchire il prompt."""
    # Verifica se il router model è disponibile
    try:
        models_info = ollama.list()
        available = [m.model for m in models_info.models]
        if ROUTER_MODEL not in available:
            # Router non disponibile, usa il primo modello disponibile
            return {"model": available_models[0] if available_models else "qwen3:8b", "enriched_prompt": user_message}
    except:
        return {"model": available_models[0] if available_models else "qwen3:8b", "enriched_prompt": user_message}

    workspace_ctx = f" Il workspace è: {workspace}." if workspace else ""
    router_prompt = f"""Sei un router intelligente per un AI coding assistant.
Analizza il messaggio dell'utente e scegli il modello migliore tra: {json.dumps(available_models)}.
Regole:
- Compiti di CODICE, debugging, scrittura file → scegli modello con "coder" nel nome o il più grande
- Compiti TESTUALI, spiegazioni, chat → scegli il modello più piccolo/veloce
- Se solo un modello disponibile → usalo

Rispondi SOLO con un JSON valido, nessun testo fuori dal JSON:
{{"model": "<nome_modello>", "enriched_prompt": "<prompt migliorato con contesto tecnico aggiunto se serve, altrimenti uguale all'originale>"}}

Messaggio utente: "{user_message}"{workspace_ctx}"""

    try:
        response = ollama.chat(
            model=ROUTER_MODEL,
            messages=[{"role": "user", "content": router_prompt}],
            options={"temperature": 0.1}
        )
        content = response.message.content
        # Estrai JSON dal contenuto (gestisce eventuali tag <think>)
        json_match = re.search(r'\{[^{}]+\}', content, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            if result.get("model") in available_models:
                return result
    except Exception as e:
        pass

    return {"model": available_models[0] if available_models else "qwen3:8b", "enriched_prompt": user_message}

# ─── Feature 3: Web Search ────────────────────────────────────────────────────
async def do_search_web(query: str, max_results: int = 5) -> str:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "Nessun risultato trovato."
        formatted = []
        for i, r in enumerate(results, 1):
            formatted.append(f"**{i}. {r.get('title', 'N/A')}**\nURL: {r.get('href', '')}\n{r.get('body', '')}")
        return "\n\n---\n\n".join(formatted)
    except Exception as e:
        return f"Errore nella ricerca: {str(e)}"

async def do_read_url(url: str) -> str:
    try:
        import httpx
        import html2text
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        text = h.handle(html)
        return text[:10000]  # tronca a 10k caratteri
    except Exception as e:
        return f"Errore lettura URL: {str(e)}"

# ─── Feature 1: Subagenti ─────────────────────────────────────────────────────
async def run_subagent_task(agent_id: str, task: str, model: str, workspace: Optional[str]):
    """Esegue un subagente in background."""
    subagent_results[agent_id] = {"status": "running", "result": None, "log": []}
    system = (
        f"Sei un subagente di Antigravity. Il tuo compito specifico è: {task}\n"
        f"Svolgi il compito in modo autonomo usando i tool disponibili. "
        f"Quando hai finito, rispondi con un riassunto completo dei risultati."
    )
    if workspace:
        system += f"\nWorkspace: {workspace}"

    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    max_turns = 15
    for _ in range(max_turns):
        try:
            response = ollama.chat(model=model, messages=messages, tools=TOOLS)
            msg_obj = response.message
            tool_calls = msg_obj.tool_calls
            messages.append(msg_to_dict(msg_obj))

            if not tool_calls:
                content = msg_obj.content or ""
                subagent_results[agent_id] = {"status": "done", "result": content, "log": messages}
                return

            for tc in tool_calls:
                tool_name, args = extract_tool_info(tc)
                output = await execute_readonly_tool(tool_name, args, workspace)
                if output is not None:
                    messages.append({"role": "tool", "content": output, "name": tool_name})
                    subagent_results[agent_id]["log"].append(f"[{tool_name}]: {output[:200]}...")
        except Exception as e:
            subagent_results[agent_id] = {"status": "error", "result": str(e), "log": []}
            return

    subagent_results[agent_id] = {"status": "done", "result": "Subagente ha raggiunto il limite di turni.", "log": messages}

# ─── Helper: esegui tool read-only (shared tra agent e subagent) ──────────────
async def execute_readonly_tool(tool_name: str, args: dict, workspace: Optional[str]) -> Optional[str]:
    """Esegue un tool read-only e ritorna l'output. Ritorna None se il tool richiede approvazione."""
    if tool_name == "list_dir":
        path = args.get("path", ".")
        target = resolve_path(path, workspace)
        try:
            items = os.listdir(target)
            files = [f"📁 {i}" if os.path.isdir(os.path.join(target, i)) else f"📄 {i}" for i in sorted(items)]
            return "\n".join(files) if files else "Cartella vuota"
        except Exception as e:
            return f"Errore: {str(e)}"

    elif tool_name == "read_file":
        path = args.get("path")
        target = resolve_path(path, workspace)
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return content[:20000]  # max 20k chars
        except Exception as e:
            return f"Errore: {str(e)}"

    elif tool_name == "search_web":
        return await do_search_web(args.get("query", ""), args.get("max_results", 5))

    elif tool_name == "read_url":
        return await do_read_url(args.get("url", ""))

    elif tool_name == "create_artifact":
        # Questo è gestito dal frontend, qui restituiamo conferma
        return f"Artefatto '{args.get('title')}' creato nel pannello laterale."

    elif tool_name == "git_snapshot":
        message = args.get("message", "Antigravity snapshot")
        if workspace:
            try:
                proc = await asyncio.create_subprocess_shell(
                    f'git add -A && git commit -m "🤖 Antigravity: {message}"',
                    cwd=workspace,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                out, err = await proc.communicate()
                result = (out + err).decode()
                return f"Git snapshot creato: {result}"
            except Exception as e:
                return f"Errore git: {str(e)}"
        return "Errore: nessun workspace impostato per git snapshot."

    return None  # tool richiede approvazione

# ─── Main Chat Endpoint ───────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: ChatRequest):
    available_models = []
    try:
        models_info = ollama.list()
        available_models = [m.model for m in models_info.models]
    except:
        available_models = [request.model]

    # Feature 0: Router LLM
    chosen_model = request.model
    router_info = {"model": request.model, "enriched_prompt": None}
    if request.use_router and available_models and len(request.messages) > 0:
        last_user_msg = next((m["content"] for m in reversed(request.messages) if m["role"] == "user"), "")
        router_info = await route_request(last_user_msg, available_models, request.workspace)
        chosen_model = router_info.get("model", request.model)

    system_prompt = (
        "Sei Antigravity Local, un AI Software Engineer autonomo e potente.\n"
        "Hai accesso a strumenti per: esplorare file, leggere file, modificare file (write_file, patch_file), "
        "cercare su internet (search_web, read_url), creare documenti nel pannello laterale (create_artifact), "
        "eseguire comandi bash (run_command), lanciare subagenti (spawn_subagent), "
        "creare piani prima di modifiche importanti (create_plan), salvare snapshot git (git_snapshot).\n"
        "REGOLE FONDAMENTALI:\n"
        "- Per domande sul progetto: usa SEMPRE list_dir e read_file prima di rispondere.\n"
        "- Per modifiche importanti: usa create_plan per far approvare il piano prima.\n"
        "- Per compiti lunghi o paralleli: usa spawn_subagent.\n"
        "- NON dire mai 'non ho accesso' o 'non posso': usa i tuoi tool.\n"
        "- Usa create_artifact per documenti, analisi, piani lunghi (non nella chat).\n"
        "- Prima di write_file o patch_file su file esistenti: usa git_snapshot."
    )
    if request.workspace:
        system_prompt += f"\nWorkspace corrente: {request.workspace}. Usa path='.' con list_dir per esplorare."

    messages = [{"role": "system", "content": system_prompt}] + request.messages

    max_turns = 30
        artifacts = []  # artefatti creati durante la sessione

    for turn in range(max_turns):
        try:
            response = ollama.chat(model=chosen_model, messages=messages, tools=TOOLS)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore Ollama ({chosen_model}): {str(e)}")

        msg_obj = response.message
        content = msg_obj.content or ""
        
        # NOTE: Antigravity Local uses both native tool calling and simulated tool calling
        tool_calls = []
        
        if getattr(msg_obj, "tool_calls", None):
            tool_calls = msg_obj.tool_calls
        else:
            # Fallback: parse simulated JSON arrays
            content_clean = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
            
            json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content_clean, re.DOTALL)
            if json_match:
                json_text = json_match.group(1)
            else:
                array_match = re.search(r'(\[.*\])', content_clean, re.DOTALL)
                json_text = array_match.group(1) if array_match else content_clean
                
            try:
                parsed = json.loads(json_text)
                if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict) and "name" in parsed[0]:
                    tool_calls = parsed
            except:
                pass

        if not tool_calls:
            # Se la risposta è ancora vuota o composta solo da think tag
            if not content_clean:
                content_clean = "[Il modello ha generato una risposta vuota o ha solo ragionato senza produrre output visibile]"
                
            return {
                "status": "success",
                "reply": content_clean,
                "model_used": chosen_model,
                "router_info": router_info,
                "artifacts": artifacts
            }

        messages.append(msg_to_dict(msg_obj))

        requires_approval = False
        approval_data = {}

        for tool_call in tool_calls:
            tool_name, args = extract_tool_info(tool_call)

            # Tool read-only → esegui subito
            readonly_output = await execute_readonly_tool(tool_name, args, request.workspace)
            if readonly_output is not None:
                messages.append({"role": "tool", "content": readonly_output, "name": tool_name})

                # Se è un artefatto, salvalo per il frontend
                if tool_name == "create_artifact":
                    artifacts.append({"title": args.get("title"), "content": args.get("content")})
                continue

            # Feature 1: Subagente
            if tool_name == "spawn_subagent":
                agent_id = args.get("agent_id", str(uuid.uuid4())[:8])
                subagent_model = args.get("model", chosen_model)
                task = args.get("task", "")
                asyncio.create_task(run_subagent_task(agent_id, task, subagent_model, request.workspace))
                output = f"Subagente '{agent_id}' avviato in background per: {task}\nUsa GET /api/subagent/{agent_id} per controllare lo stato."
                messages.append({"role": "tool", "content": output, "name": tool_name})
                continue

            # Feature 6: Plan → richiede approvazione
            if tool_name == "create_plan":
                session_id = str(uuid.uuid4())
                pending_tools[session_id] = {"type": "plan", "data": args}
                return {
                    "status": "pending_plan",
                    "session_id": session_id,
                    "plan": args,
                    "model_used": chosen_model,
                    "artifacts": artifacts
                }

            # Feature 4: Write/Patch file → richiede approvazione
            if tool_name in ["write_file", "patch_file"]:
                requires_approval = True
                approval_data = {"type": tool_name, "args": args, "model": chosen_model, "workspace": request.workspace}
                break

            # Feature 5: run_command
            if tool_name == "run_command":
                requires_approval = True
                approval_data = {"type": "run_command", "args": args, "model": chosen_model, "workspace": request.workspace}
                break

            # Tool non riconosciuto
            messages.append({
                "role": "tool",
                "content": f"Errore: tool '{tool_name}' non esiste. Tool disponibili: list_dir, read_file, write_file, patch_file, search_web, read_url, create_artifact, create_plan, spawn_subagent, run_command, git_snapshot",
                "name": tool_name
            })

        if requires_approval:
            session_id = str(uuid.uuid4())
            pending_tools[session_id] = approval_data
            resp = {
                "status": "pending_approval",
                "session_id": session_id,
                "tool": approval_data["type"],
                "model_used": chosen_model,
                "artifacts": artifacts
            }
            if approval_data["type"] == "run_command":
                resp["cmd"] = approval_data["args"].get("cmd")
            elif approval_data["type"] == "write_file":
                resp["path"] = approval_data["args"].get("path")
                resp["preview"] = approval_data["args"].get("content", "")[:500]
            elif approval_data["type"] == "patch_file":
                resp["path"] = approval_data["args"].get("path")
                resp["old_content"] = approval_data["args"].get("old_content")
                resp["new_content"] = approval_data["args"].get("new_content")
                # Genera diff leggibile
                old_lines = approval_data["args"].get("old_content", "").splitlines(keepends=True)
                new_lines = approval_data["args"].get("new_content", "").splitlines(keepends=True)
                resp["diff"] = "".join(difflib.unified_diff(old_lines, new_lines, fromfile="before", tofile="after"))
            return resp

    return {"status": "success", "reply": "L'agente ha completato tutti i passaggi disponibili (limite turni raggiunto).", "model_used": chosen_model, "artifacts": artifacts}


# ─── Approve Tool ─────────────────────────────────────────────────────────────
@app.post("/api/approve_tool")
async def approve_tool(request: ApproveRequest):
    if request.session_id not in pending_tools:
        raise HTTPException(status_code=404, detail="Sessione non trovata o già processata")

    session_data = pending_tools.pop(request.session_id)
    tool_type = session_data.get("type")
    workspace = session_data.get("workspace")

    if not request.approved:
        return {"status": "rejected", "reply": f"Operazione '{tool_type}' rifiutata."}

    # Esegui run_command
    if tool_type == "run_command":
        cmd = session_data["args"].get("cmd")
        run_bg = session_data["args"].get("background", False)
        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                cwd=workspace if workspace else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            if run_bg:
                task_id = str(uuid.uuid4())[:8]
                background_tasks[task_id] = {"cmd": cmd, "status": "running", "output": ""}
                asyncio.create_task(_bg_task_runner(task_id, process))
                return {"status": "background", "task_id": task_id, "reply": f"Comando avviato in background. Task ID: {task_id}"}
            else:
                stdout, stderr = await process.communicate()
                output = stdout.decode() + stderr.decode()
                return {"status": "executed", "cmd": cmd, "output": output or "Completato senza output."}
        except Exception as e:
            return {"status": "error", "reply": str(e)}

    # Esegui write_file
    elif tool_type == "write_file":
        path = session_data["args"].get("path")
        content = session_data["args"].get("content", "")
        target = resolve_path(path, workspace)
        try:
            os.makedirs(os.path.dirname(target) if os.path.dirname(target) else ".", exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write(content)
            return {"status": "executed", "reply": f"File '{path}' scritto con successo ({len(content)} caratteri)."}
        except Exception as e:
            return {"status": "error", "reply": str(e)}

    # Esegui patch_file
    elif tool_type == "patch_file":
        path = session_data["args"].get("path")
        old_content = session_data["args"].get("old_content", "")
        new_content = session_data["args"].get("new_content", "")
        target = resolve_path(path, workspace)
        try:
            with open(target, "r", encoding="utf-8") as f:
                file_content = f.read()
            if old_content not in file_content:
                return {"status": "error", "reply": f"Stringa da sostituire non trovata in '{path}'. Il file potrebbe essere cambiato."}
            patched = file_content.replace(old_content, new_content, 1)
            with open(target, "w", encoding="utf-8") as f:
                f.write(patched)
            return {"status": "executed", "reply": f"File '{path}' patchato con successo."}
        except Exception as e:
            return {"status": "error", "reply": str(e)}

    # Piano approvato
    elif tool_type == "plan":
        return {"status": "plan_approved", "reply": "Piano approvato! L'agente procederà con l'implementazione.", "plan": session_data.get("data")}

    return {"status": "error", "reply": "Tipo operazione sconosciuto."}


# ─── Background task helper ───────────────────────────────────────────────────
async def _bg_task_runner(task_id: str, process):
    stdout, stderr = await process.communicate()
    output = stdout.decode() + stderr.decode()
    background_tasks[task_id] = {"status": "done", "output": output or "Completato senza output.", "exit_code": process.returncode}

@app.get("/api/task/{task_id}")
async def get_task_status(task_id: str):
    if task_id not in background_tasks:
        raise HTTPException(status_code=404, detail="Task non trovato")
    return background_tasks[task_id]

# ─── Subagent status ──────────────────────────────────────────────────────────
@app.get("/api/subagent/{agent_id}")
async def get_subagent_status(agent_id: str):
    if agent_id not in subagent_results:
        return {"status": "not_found"}
    return subagent_results[agent_id]

@app.get("/api/subagents")
async def list_subagents():
    return {k: {"status": v["status"]} for k, v in subagent_results.items()}

# ─── Folders, Models ──────────────────────────────────────────────────────────
@app.get("/api/folders")
async def get_folders(path: str = "/home/matteo"):
    try:
        if not os.path.isdir(path):
            return {"error": "Path non valido"}
        items = os.listdir(path)
        folders = []
        for item in items:
            if item.startswith("."):
                continue
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path):
                folders.append({"name": item, "path": full_path})
        folders.sort(key=lambda x: x["name"].lower())
        parent = os.path.dirname(path)
        if parent == path:
            parent = None
        return {"current": path, "parent": parent, "folders": folders}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/models")
async def get_models():
    try:
        models_info = ollama.list()
        return {"models": [m.model for m in models_info.models]}
    except Exception as e:
        return {"models": [], "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
