import { useState, useEffect, useRef, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Group, Panel, Separator } from 'react-resizable-panels';
import './index.css';

// ─── Types ───────────────────────────────────────────────────────────────────
interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  modelUsed?: string;
}

interface Artifact {
  id: string;
  title: string;
  content: string;
  updatedAt: Date;
}

interface ToolApproval {
  sessionId: string;
  type: 'run_command' | 'write_file' | 'patch_file';
  cmd?: string;
  path?: string;
  preview?: string;
  diff?: string;
  old_content?: string;
  new_content?: string;
}

interface PendingPlan {
  sessionId: string;
  title: string;
  description: string;
  steps: string[];
}

interface Subagent {
  id: string;
  task: string;
  status: 'running' | 'done' | 'error';
  result?: string;
}

// ─── App ─────────────────────────────────────────────────────────────────────
function App() {
  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Models & Router
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('qwen3:8b');
  const [useRouter, setUseRouter] = useState(true);
  const [lastModelUsed, setLastModelUsed] = useState<string | null>(null);

  // Workspace
  const [workspace, setWorkspace] = useState('');
  const [showFolderPicker, setShowFolderPicker] = useState(false);
  const [pickerPath, setPickerPath] = useState('/home/matteo');
  const [pickerFolders, setPickerFolders] = useState<any[]>([]);
  const [pickerParent, setPickerParent] = useState<string | null>(null);

  // Modals
  const [pendingApproval, setPendingApproval] = useState<ToolApproval | null>(null);
  const [pendingPlan, setPendingPlan] = useState<PendingPlan | null>(null);

  // Artifacts panel
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [activeArtifact, setActiveArtifact] = useState<Artifact | null>(null);
  const [showArtifacts, setShowArtifacts] = useState(false);

  // Subagents
  const [subagents, setSubagents] = useState<Subagent[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ─── Init ─────────────────────────────────────────────────────────────────
  useEffect(() => { fetchModels(); }, []);
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  // Poll subagents status
  useEffect(() => {
    if (subagents.filter(s => s.status === 'running').length === 0) return;
    const interval = setInterval(async () => {
      const updated = await Promise.all(subagents.map(async (s) => {
        if (s.status !== 'running') return s;
        try {
          const res = await fetch(`http://localhost:8000/api/subagent/${s.id}`);
          const data = await res.json();
          if (data.status === 'done' || data.status === 'error') {
            addSystemMessage(`🤖 Subagente '${s.id}' completato:\n${data.result || data.error || ''}`);
            return { ...s, status: data.status as any, result: data.result };
          }
        } catch {}
        return s;
      }));
      setSubagents(updated);
    }, 3000);
    return () => clearInterval(interval);
  }, [subagents]);

  // ─── Helpers ───────────────────────────────────────────────────────────────
  const addSystemMessage = (content: string) => {
    setMessages(prev => [...prev, { id: Date.now().toString(), role: 'system', content }]);
  };

  const fetchModels = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/models');
      const data = await res.json();
      if (data.models?.length > 0) {
        setModels(data.models);
        setSelectedModel(data.models[0]);
      }
    } catch (e) { console.error(e); }
  };

  const fetchFolders = async (path: string) => {
    try {
      const res = await fetch(`http://localhost:8000/api/folders?path=${encodeURIComponent(path)}`);
      const data = await res.json();
      if (!data.error) {
        setPickerPath(data.current);
        setPickerFolders(data.folders || []);
        setPickerParent(data.parent);
      }
    } catch (e) { console.error(e); }
  };

  const upsertArtifact = (title: string, content: string) => {
    const id = title.toLowerCase().replace(/\s+/g, '-');
    const artifact: Artifact = { id, title, content, updatedAt: new Date() };
    setArtifacts(prev => {
      const existing = prev.findIndex(a => a.id === id);
      if (existing >= 0) {
        const updated = [...prev];
        updated[existing] = artifact;
        return updated;
      }
      return [...prev, artifact];
    });
    setActiveArtifact(artifact);
    setShowArtifacts(true);
  };

  // ─── Send message ──────────────────────────────────────────────────────────
  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const userMessage: Message = { id: Date.now().toString(), role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsLoading(true);

    try {
      const chatHistory = [...messages, userMessage]
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role, content: m.content }));

      const res = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatHistory,
          model: selectedModel,
          workspace: workspace.trim() || undefined,
          use_router: useRouter
        })
      });
      const data = await res.json();
      handleApiResponse(data);
    } catch (e) {
      addSystemMessage('❌ Errore di connessione al backend.');
      setIsLoading(false);
    }
  };

  const handleApiResponse = (data: any) => {
    // Aggiorna badge modello usato
    if (data.model_used) setLastModelUsed(data.model_used);

    // Salva artefatti nuovi/aggiornati
    if (data.artifacts?.length > 0) {
      data.artifacts.forEach((a: any) => upsertArtifact(a.title, a.content));
    }

    if (data.status === 'success') {
      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        role: 'assistant',
        content: data.reply,
        modelUsed: data.model_used
      }]);
      setIsLoading(false);
    } else if (data.status === 'pending_approval') {
      setPendingApproval({
        sessionId: data.session_id,
        type: data.tool,
        cmd: data.cmd,
        path: data.path,
        preview: data.preview,
        diff: data.diff,
        old_content: data.old_content,
        new_content: data.new_content
      });
    } else if (data.status === 'pending_plan') {
      setPendingPlan({
        sessionId: data.session_id,
        title: data.plan?.title || 'Piano',
        description: data.plan?.description || '',
        steps: data.plan?.steps || []
      });
    }
  };

  // ─── Loop Resume ───────────────────────────────────────────────────────────
  const resumeAgentLoop = async (newMsgContent: string) => {
    setIsLoading(true);
    const newMsg: Message = { id: Date.now().toString(), role: 'user', content: newMsgContent };
    
    setMessages(prev => {
      const updatedMessages = [...prev, newMsg];
      const chatHistory = updatedMessages
        .filter(m => m.role === 'user' || m.role === 'assistant')
        .map(m => ({ role: m.role, content: m.content }));
        
      fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: chatHistory,
          model: selectedModel,
          workspace: workspace.trim() || undefined,
          use_router: useRouter
        })
      })
      .then(res => res.json())
      .then(data => handleApiResponse(data))
      .catch(e => {
        addSystemMessage('❌ Errore di connessione al backend.');
        setIsLoading(false);
      });
      
      return updatedMessages;
    });
  };

  // ─── Approve tool ──────────────────────────────────────────────────────────
  const handleApproveTool = async (approved: boolean) => {
    if (!pendingApproval) return;
    const { sessionId, type, cmd, path } = pendingApproval;
    setPendingApproval(null);

    const label = type === 'run_command' ? `\`${cmd}\`` : `'${path}'`;
    addSystemMessage(approved ? `✅ Approvato: ${label}` : `❌ Rifiutato: ${label}`);

    try {
      const res = await fetch('http://localhost:8000/api/approve_tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, approved })
      });
      const data = await res.json();
      
      if (approved) {
        if (data.status === 'executed') {
          const output = data.output || data.reply || '';
          await resumeAgentLoop(`[L'utente ha approvato l'operazione. Output: ${output}]`);
        } else if (data.status === 'background') {
          await resumeAgentLoop(`[Task avviato in background. Task ID: ${data.task_id}]`);
        } else {
          await resumeAgentLoop(`[Errore durante l'esecuzione del tool: ${data.reply}]`);
        }
      } else {
        await resumeAgentLoop(`[Tool rifiutato dall'utente. Modifica il tuo piano.]`);
      }
    } catch (e) { 
      console.error(e); 
      setIsLoading(false); 
    }
  };

  // ─── Approve plan ──────────────────────────────────────────────────────────
  const handleApprovePlan = async (approved: boolean) => {
    if (!pendingPlan) return;
    const { sessionId } = pendingPlan;
    setPendingPlan(null);
    addSystemMessage(approved ? '✅ Piano approvato! Procedo con l\'implementazione...' : '❌ Piano rifiutato.');
    try {
      await fetch('http://localhost:8000/api/approve_tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, approved })
      });
      await resumeAgentLoop(approved ? "[Piano approvato. Esegui il primo step del piano.]" : "[Piano rifiutato. Chiedi all'utente istruzioni su come procedere.]");
    } catch (e) { 
      console.error(e); 
      setIsLoading(false); 
    }
  };

  // ─── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app-container">
      {/* Header */}
      <header className="header">
        <div className="header-left">
          <h1>🚀 Antigravity Local</h1>
          {lastModelUsed && (
            <span className="model-badge">⚡ {lastModelUsed}</span>
          )}
        </div>
        <div className="header-controls">
          {/* Router toggle */}
          <button
            className={`router-toggle ${useRouter ? 'active' : ''}`}
            onClick={() => setUseRouter(!useRouter)}
            title={useRouter ? 'Router AI: ON (click per disattivare)' : 'Router AI: OFF (click per attivare)'}
          >
            🧠 Router {useRouter ? 'ON' : 'OFF'}
          </button>
          {/* Workspace */}
          <div className="workspace-container">
            <input
              type="text"
              className="workspace-input"
              placeholder="Workspace..."
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
            />
            <button className="icon-btn" onClick={() => { setShowFolderPicker(true); fetchFolders(pickerPath); }} title="Sfoglia">📁</button>
          </div>
          {/* Model selector (manuale, visibile quando router è OFF) */}
          {!useRouter && (
            <select className="model-selector" value={selectedModel} onChange={(e) => setSelectedModel(e.target.value)}>
              {models.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
          {/* Artifacts button */}
          <button
            className={`icon-btn ${showArtifacts ? 'active' : ''}`}
            onClick={() => setShowArtifacts(!showArtifacts)}
            title="Pannello Artefatti"
          >
            📄 {artifacts.length > 0 && <span className="badge">{artifacts.length}</span>}
          </button>
        </div>
      </header>

      {/* Main split-pane layout */}
      <Group direction="horizontal" className="main-content">
        {/* Chat Panel */}
        <Panel defaultSize={showArtifacts ? 50 : 100} minSize={30}>
          <div className="chat-panel">
            <main className="chat-container">
              {messages.length === 0 && (
                <div className="welcome-screen">
                  <div className="welcome-icon">🚀</div>
                  <h2>Antigravity Local 3.0</h2>
                  <p>Agente autonomo con Web Search, Subagenti, Planning Mode e molto altro.</p>
                  <div className="feature-chips">
                    <span>🧠 Router LLM</span>
                    <span>🌐 Web Search</span>
                    <span>🤖 Subagenti</span>
                    <span>📄 Artefatti</span>
                    <span>📝 Planning</span>
                    <span>🔧 Patching</span>
                  </div>
                </div>
              )}
              {messages.map(msg => (
                <div key={msg.id} className={`message ${msg.role}`}>
                  {msg.role === 'assistant' ? (
                    <>
                      {msg.modelUsed && <div className="msg-model-tag">⚡ {msg.modelUsed}</div>}
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </>
                  ) : msg.role === 'system' ? (
                    <em>{msg.content}</em>
                  ) : (
                    <span>{msg.content}</span>
                  )}
                </div>
              ))}
              {isLoading && !pendingApproval && !pendingPlan && (
                <div className="message assistant typing-indicator"><span /><span /><span /></div>
              )}
              <div ref={messagesEndRef} />
            </main>

            {/* Subagents bar */}
            {subagents.length > 0 && (
              <div className="subagents-bar">
                {subagents.map(s => (
                  <div key={s.id} className={`subagent-chip ${s.status}`}>
                    {s.status === 'running' ? '⏳' : s.status === 'done' ? '✅' : '❌'} {s.id}
                  </div>
                ))}
              </div>
            )}

            {/* Input area */}
            <div className="input-area">
              <input
                type="text"
                className="chat-input"
                placeholder="Chiedimi qualsiasi cosa..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                disabled={isLoading}
              />
              <button className="send-button" onClick={handleSend} disabled={isLoading || !!pendingApproval || !!pendingPlan}>
                {isLoading ? '...' : 'Invia'}
              </button>
            </div>
          </div>
        </Panel>

        {/* Resize handle */}
        {showArtifacts && (
          <Separator className="resize-handle">
            <div className="resize-handle-bar" />
          </Separator>
        )}

        {/* Artifacts Panel */}
        {showArtifacts && (
          <Panel defaultSize={50} minSize={25}>
            <div className="artifact-panel">
              <div className="artifact-header">
                <span className="artifact-header-title">📄 Artefatti</span>
                <div className="artifact-tabs">
                  {artifacts.map(a => (
                    <button
                      key={a.id}
                      className={`artifact-tab ${activeArtifact?.id === a.id ? 'active' : ''}`}
                      onClick={() => setActiveArtifact(a)}
                    >
                      {a.title}
                    </button>
                  ))}
                  {artifacts.length === 0 && <span className="no-artifact">Nessun artefatto ancora</span>}
                </div>
                <button className="icon-btn" onClick={() => setShowArtifacts(false)}>✕</button>
              </div>
              <div className="artifact-content">
                {activeArtifact ? (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{activeArtifact.content}</ReactMarkdown>
                ) : (
                  <div className="no-artifact-msg">
                    <p>Gli artefatti appariranno qui quando l'agente creerà documenti, piani o analisi.</p>
                  </div>
                )}
              </div>
            </div>
          </Panel>
        )}
      </Group>

      {/* ─── Modal: Folder Picker ─── */}
      {showFolderPicker && (
        <div className="modal-overlay">
          <div className="modal-content folder-picker-modal">
            <div className="modal-header"><h2>📁 Seleziona Cartella</h2></div>
            <div className="folder-picker-path">{pickerPath}</div>
            <div className="folder-list">
              {pickerParent && (
                <div className="folder-item" onClick={() => fetchFolders(pickerParent)}>
                  <span className="folder-icon">⬆️</span> ..
                </div>
              )}
              {pickerFolders.map(f => (
                <div key={f.path} className="folder-item" onClick={() => fetchFolders(f.path)}>
                  <span className="folder-icon">📁</span> {f.name}
                </div>
              ))}
              {pickerFolders.length === 0 && <div style={{ padding: '12px', color: 'var(--text-secondary)' }}>Nessuna sottocartella</div>}
            </div>
            <div className="modal-actions">
              <button className="btn btn-reject" onClick={() => setShowFolderPicker(false)}>Annulla</button>
              <button className="btn btn-approve" onClick={() => { setWorkspace(pickerPath); setShowFolderPicker(false); }}>Imposta Workspace</button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Modal: Command/File Approval ─── */}
      {pendingApproval && (
        <div className="modal-overlay">
          <div className="modal-content approval-modal">
            <div className="modal-header">
              <span style={{ fontSize: '1.5rem' }}>
                {pendingApproval.type === 'run_command' ? '⚡' : pendingApproval.type === 'write_file' ? '✍️' : '🔧'}
              </span>
              <h2>
                {pendingApproval.type === 'run_command' ? 'Esegui Comando' :
                 pendingApproval.type === 'write_file' ? 'Scrivi File' : 'Modifica File'}
              </h2>
            </div>
            {pendingApproval.type === 'run_command' && (
              <>
                <p className="modal-desc">L'agente vuole eseguire:</p>
                <div className="command-preview">{pendingApproval.cmd}</div>
              </>
            )}
            {pendingApproval.type === 'write_file' && (
              <>
                <p className="modal-desc">L'agente vuole creare/sovrascrivere <code>{pendingApproval.path}</code>:</p>
                <div className="command-preview" style={{ maxHeight: '200px', overflowY: 'auto', whiteSpace: 'pre-wrap', fontSize: '0.8rem' }}>
                  {pendingApproval.preview}{(pendingApproval.preview?.length || 0) >= 500 ? '\n...(troncato)' : ''}
                </div>
              </>
            )}
            {pendingApproval.type === 'patch_file' && (
              <>
                <p className="modal-desc">L'agente vuole modificare <code>{pendingApproval.path}</code>:</p>
                <div className="diff-preview">
                  {pendingApproval.diff?.split('\n').map((line, i) => (
                    <div key={i} className={`diff-line ${line.startsWith('+') ? 'add' : line.startsWith('-') ? 'remove' : ''}`}>
                      {line}
                    </div>
                  ))}
                </div>
              </>
            )}
            <div className="modal-actions">
              <button className="btn btn-reject" onClick={() => handleApproveTool(false)}>Rifiuta</button>
              <button className="btn btn-approve" onClick={() => handleApproveTool(true)}>✅ Approva</button>
            </div>
          </div>
        </div>
      )}

      {/* ─── Modal: Planning Mode ─── */}
      {pendingPlan && (
        <div className="modal-overlay">
          <div className="modal-content plan-modal">
            <div className="modal-header">
              <span style={{ fontSize: '1.5rem' }}>📋</span>
              <h2>{pendingPlan.title}</h2>
            </div>
            <p className="modal-desc">{pendingPlan.description}</p>
            <div className="plan-steps">
              {pendingPlan.steps.map((step, i) => (
                <div key={i} className="plan-step">
                  <span className="plan-step-num">{i + 1}</span>
                  <span>{step}</span>
                </div>
              ))}
            </div>
            <div className="modal-actions">
              <button className="btn btn-reject" onClick={() => handleApprovePlan(false)}>❌ Rifiuta</button>
              <button className="btn btn-approve" onClick={() => handleApprovePlan(true)}>✅ Approva Piano</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
