// src/App.js — TalentIQ Talent Matching SPA
import React, { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useIsAuthenticated, useMsal } from "@azure/msal-react";
import { InteractionRequiredAuthError, InteractionStatus } from "@azure/msal-browser";
import { foundryLoginRequest } from "./authConfig";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import ChartView, { canChart } from "./ChartView";
import {
  trackUserQuery,
  trackApiCallStart,
  trackQueryResponseTime,
  trackWorkflowEvent,
  trackError,
  trackEvent,
} from "./telemetry";
import "./App.css";

const API_BASE = process.env.REACT_APP_API_BASE ?? "";
const AF_BACKEND_URL = process.env.REACT_APP_AF_BACKEND_URL ?? "/af";
const AGENT_NAME = process.env.REACT_APP_AGENT_NAME ?? "talentiq-agent";

const BACKENDS = [
  { id: "graph-search", label: "Graph Search (Talent Graph)" },
];

// ——— Helpers ————————————————————————————————————————————————

function renderMarkdown(text) {
  if (!text) return null;
  const parts = [];
  const linkRegex = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let lastIndex = 0;
  let match;
  while ((match = linkRegex.exec(text)) !== null) {
    if (match.index > lastIndex) parts.push(text.slice(lastIndex, match.index));
    parts.push(
      <a key={match.index} href={match[2]} target="_blank" rel="noopener noreferrer"
        style={{ color: "#93c5fd", textDecoration: "underline" }}>{match[1]}</a>
    );
    lastIndex = linkRegex.lastIndex;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts;
}

function CollapsibleCategory({ label, defaultOpen = false, children }) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div className="question-category">
      <button className="category-toggle" onClick={() => setIsOpen(o => !o)}>
        <label className="sidebar-label">{label}</label>
        <span className={`category-chevron ${isOpen ? "open" : ""}`}>&#9660;</span>
      </button>
      <div className={`category-items ${isOpen ? "open" : ""}`}>{children}</div>
    </div>
  );
}

function RunLogPanel({ runs, onClear }) {
  const panelEndRef = useRef(null);
  useEffect(() => {
    panelEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [runs]);
  return (
    <aside className="runlog-panel">
      <div className="runlog-panel-header">
        <span className="runlog-panel-title">Run Log</span>
        {runs.length > 0 && (
          <button className="btn-ghost btn-sm" onClick={onClear}>Clear</button>
        )}
      </div>
      <div className="runlog-panel-body">
        {runs.length === 0 && (
          <div className="runlog-empty">No runs yet</div>
        )}
        {runs.map((run, ri) => (
          <RunLogBlock key={ri} run={run} index={ri} total={runs.length} />
        ))}
        <div ref={panelEndRef} />
      </div>
    </aside>
  );
}

function RunLogBlock({ run, index, total }) {
  const [expanded, setExpanded] = useState(index === total - 1);
  const entries = run.entries || [];
  if (entries.length === 0) return null;
  return (
    <div className="run-log">
      <div className="run-log-header" onClick={() => setExpanded(e => !e)}>
        <span>{expanded ? "▼" : "▶"}</span>
        <span>Run {index + 1} ({entries.length})</span>
        {run.query && <span className="run-log-query" title={run.query}>{run.query}</span>}
      </div>
      {expanded && (
        <div className="run-log-entries">
          {entries.map((entry, i) => (
            <div key={i} className={`run-log-entry ${entry.kind || "orch"}`}>
              <span className="log-badge">
                {entry.kind === "query" ? "QUERY" : entry.kind === "result" ? "RESULT" : entry.kind === "error" ? "ERROR" : "ORCH"}
              </span>
              <span>{(entry.text || "").replace(/^\[(ORCH|QUERY|RESULT)\]\s*/i, "")}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Bubble({ role, text, elapsed }) {
  const isUser = role === "user";
  const [showChart, setShowChart] = useState(false);
  const chartable = !isUser && canChart(text);
  return (
    <>
      <div style={{ display: "flex", justifyContent: isUser ? "flex-end" : "flex-start", margin: "8px 0" }}>
        <div className={`bubble ${isUser ? "user" : "assistant"}`}>
          {isUser ? text : (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          )}
          <div className="bubble-footer">
            {chartable && (
              <button className="chart-toggle-btn" onClick={() => setShowChart(v => !v)}>
                {showChart ? "Hide Chart" : "\u{1F4CA} Show Chart"}
              </button>
            )}
            {!isUser && elapsed != null && (
              <span className="bubble-elapsed">{elapsed < 1000 ? `${elapsed}ms` : `${(elapsed / 1000).toFixed(1)}s`}</span>
            )}
          </div>
        </div>
      </div>
      {showChart && (
        <div className="chart-full-width">
          <ChartView text={text} />
        </div>
      )}
    </>
  );
}

function ApprovalDialog({ approvals, onSubmit, disabled }) {
  return (
    <div className="approval-dialog">
      <div className="approval-card">
        <h3>MCP Tool Approval Required</h3>
        {approvals.map((a, i) => (
          <div key={i} className="approval-item">
            <p><strong>Server:</strong> {a.server_label}</p>
            <p><strong>Tool:</strong> {a.tool_name}</p>
            <p className="approval-args"><strong>Arguments:</strong> {JSON.stringify(a.arguments, null, 2)}</p>
          </div>
        ))}
        <div className="approval-actions">
          <button className="btn-primary" disabled={disabled} onClick={() => onSubmit(true)}>Approve All</button>
          <button className="btn-ghost" disabled={disabled} onClick={() => onSubmit(false)}>Deny</button>
        </div>
      </div>
    </div>
  );
}

// ——— Quick questions ————————————————————————————————————————

const QUICK_QUESTION_CATEGORIES = [
  {
    // US-009: Multi-criteria search with impressiveness scoring
    // US-010: Additional filters on search results
    label: "Candidate Search",
    questions: [
      "Find Python developers in Spain",
      "Find 5 senior Java developers in Europe",
      "Find AI/ML experts in India with 8+ years experience",
      "Find .NET developers in Poland with Azure certifications",
    ],
  },
  {
    // US-012: Triage attributes (bench status, availability)
    label: "Bench & Availability",
    questions: [
      "Find bench employees with Java skills in Spain",
      "Show bench breakdown by delivery model",
    ],
  },
  {
    // US-020: Certification validity status
    // US-030: Expiring/expired certification reminders
    // US-015: Full-text resume search
    // US-014: Skill gaps and retraining suggestions
    // US-025: Drill down to employee certifications and competencies
    label: "Certifications & Skills",
    questions: [
      "Who has valid PMP certification?",
      "Show expiring certifications that need renewal",
      "Find employees with Kubernetes in their resume",
      "Which skills are not covered by any bench candidate in Germany?",
      "Show all certifications for carlos.garcia@dxc.com",
    ],
  },
  {
    // US-009: Search by language proficiency and location
    label: "Language & Location",
    questions: [
      "Find French speakers at B2 level or higher",
      "How many employees per country?",
    ],
  },
  {
    // US-024: My Team dashboard
    // US-027: Aggregated reports and statistics
    // US-028: Skills and certifications baseline for team
    label: "Team & Organization",
    questions: [
      "Show me Carmen's team members",
      "Employee count by service line",
      "Review skills and certifications for Carmen's team",
    ],
  },
  {
    // US-009: Impressiveness scoring
    // US-008: EQF/MECES mapping
    // US-023: Dashboard with certifications, skills, languages summary
    // US-026: CV freshness indicators
    label: "Scoring & Analytics",
    questions: [
      "Show impressiveness score distribution",
      "Who are the top 10 employees by impressiveness score?",
      "EQF level distribution across the workforce",
      "How many employees have CVs older than 1 year?",
      "Show certifications and skills summary across the workforce",
    ],
  },
  {
    // US-009: Search by client history
    // US-027: Client engagement reports
    label: "Client & History",
    questions: [
      "Find employees who worked for Telefónica",
      "Which clients have the most employee engagements?",
    ],
  },
];

// ——— Main App ———————————————————————————————————————————————

export default function App() {
  const { instance, accounts, inProgress } = useMsal();
  const isAuthenticated = useIsAuthenticated();
  const account = useMemo(
    () => instance.getActiveAccount() ?? accounts?.[0] ?? null,
    [instance, accounts]
  );

  const [error, setError] = useState(null);
  const [needsConsent, setNeedsConsent] = useState(false);
  const [accessToken, setAccessToken] = useState(null);

  // Backend selector
  const [selectedBackend, setSelectedBackend] = useState("graph-search");

  // Chat state
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [messages, setMessages] = useState([]);
  const [previousResponseId, setPreviousResponseId] = useState(null);
  const [afSessionId, setAfSessionId] = useState(null);

  // Persistent run log state (survives across queries)
  const [runLogRuns, setRunLogRuns] = useState([]);
  const currentRunRef = useRef({ entries: [], query: "" });

  // Chat history state
  const [threads, setThreads] = useState([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState(null);

  // MCP approval state
  const [pendingApprovals, setPendingApprovals] = useState(null);
  const [pendingApprovalResponseId, setPendingApprovalResponseId] = useState(null);

  // OAuth consent state
  const [oauthConsentLink, setOauthConsentLink] = useState(null);
  const [oauthResponseId, setOauthResponseId] = useState(null);

  // Guards against double-click / rapid re-invocation (refs update synchronously)
  const sendingRef = useRef(false);
  const submittingApprovalRef = useRef(false);

  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, chatLoading]);

  // ——— Auth ————————————————————————————————————————————————

  const login = () => {
    setError(null);
    instance.loginRedirect(foundryLoginRequest);
  };

  const logout = () => {
    setAccessToken(null);
    setMessages([]);
    instance.logoutRedirect({ account });
  };

  const getToken = useCallback(async () => {
    if (!account) return null;
    try {
      const res = await instance.acquireTokenSilent({ ...foundryLoginRequest, account });
      setAccessToken(res.accessToken);
      setNeedsConsent(false);
      return res.accessToken;
    } catch (e) {
      if (e instanceof InteractionRequiredAuthError) {
        setNeedsConsent(true);
        return null;
      }
      setError(e?.message || String(e));
      return null;
    }
  }, [account, instance]);

  const consentAndGetToken = () => {
    instance.acquireTokenRedirect({ ...foundryLoginRequest, account });
  };

  useEffect(() => {
    if (isAuthenticated && account && inProgress === InteractionStatus.None) {
      getToken();
    }
  }, [isAuthenticated, account, inProgress, getToken]);

  // ——— Chat API ————————————————————————————————————————————

  const handleChatResponse = (data) => {
    if (data.status === "oauth_consent_required") {
      setOauthConsentLink(data.consent_link);
      setOauthResponseId(data.response_id);
      setMessages(m => [...m, {
        role: "assistant",
        text: "MCP tool requires authentication. Please click the link below to authorize, then click 'Continue'."
      }]);
    } else if (data.status === "approval_required") {
      setPendingApprovals(data.approval_requests);
      setPendingApprovalResponseId(data.response_id);
    } else {
      // status === "ok"
      setPreviousResponseId(data.response_id);
      setMessages(m => [...m, { role: "assistant", text: data.output_text || "(no response)" }]);
    }
  };

  const callChatApi = async (body, token) => {
    if (selectedBackend === "agent-framework") {
      return callAfBackendApi(body, setMessages);
    }
    if (selectedBackend === "graph-search") {
      return callGraphBackendApi(body, setMessages);
    }
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData?.detail || `HTTP ${res.status}`);
    }
    return res.json();
  };

  const callAfBackendApi = async (body, setMessagesFn) => {
    // AF backend streams intermediate agent messages via SSE
    const afBody = { input: body.message || "", stream: true };
    if (afSessionId) {
      afBody.session_id = afSessionId;
    }
    const res = await fetch(`${AF_BACKEND_URL}/responses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(afBody),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData?.error?.message || errData?.detail || `HTTP ${res.status}`);
    }

    // Parse SSE stream
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let lastResponseId = null;
    let collectedTexts = [];

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Process complete SSE events
      const lines = buffer.split("\n");
      buffer = lines.pop(); // keep incomplete last line
      let eventType = null;
      for (const line of lines) {
        if (line.startsWith("event: ")) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith("data: ") && eventType) {
          try {
            const data = JSON.parse(line.slice(6));
            if (eventType === "message" && data.text) {
              const speaker = data.speaker || "assistant";
              collectedTexts.push(data.text);
              lastResponseId = data.id || lastResponseId;
              // Stream each message to UI immediately
              setMessagesFn(m => {
                // Replace the last assistant message if same speaker, or add new
                const last = m[m.length - 1];
                if (last && last.role === "assistant" && last.speaker === speaker) {
                  return [...m.slice(0, -1), { role: "assistant", speaker, text: data.text }];
                }
                return [...m, { role: "assistant", speaker, text: data.text }];
              });
            } else if (eventType === "handoff") {
              setMessagesFn(m => [...m, {
                role: "assistant",
                speaker: "system",
                text: `*Routing to ${data.target}...*`,
              }]);
            } else if (eventType === "done") {
              if (data.session_id) setAfSessionId(data.session_id);
              lastResponseId = data.id || lastResponseId;
            } else if (eventType === "error") {
              throw new Error(data.message || "Workflow error");
            }
          } catch (e) {
            if (e.message !== "Workflow error" && !e.message?.startsWith("Workflow")) {
              // JSON parse error — skip
            } else {
              throw e;
            }
          }
          eventType = null;
        }
      }
    }

    const outputText = collectedTexts.join("\n\n") || "(no response)";
    return { status: "ok", output_text: outputText, response_id: lastResponseId };
  };

  const callGraphBackendApi = async (body, setMessagesFn) => {
    const graphBody = { input: body.message || "" };
    if (afSessionId) graphBody.session_id = afSessionId;

    trackUserQuery(graphBody.input, "graph-search");
    const apiTracker = trackApiCallStart("/graph/responses");

    const res = await fetch(`${AF_BACKEND_URL}/graph/responses`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(graphBody),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData?.error?.message || errData?.detail || `HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResult = null;
    const startTime = Date.now();

    // Start a new run for this query
    const queryText = graphBody.input || "";
    currentRunRef.current = { entries: [], query: queryText };

    const pushLogEntry = (entry) => {
      currentRunRef.current.entries.push(entry);
      // Deep copy entries to ensure React detects the change
      const snapshot = { query: currentRunRef.current.query, entries: [...currentRunRef.current.entries] };
      setRunLogRuns(prev => {
        const updated = [...prev];
        // Update or append the current run
        if (updated.length > 0 && updated[updated.length - 1].query === queryText) {
          updated[updated.length - 1] = snapshot;
        } else {
          updated.push(snapshot);
        }
        return updated;
      });
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const data = JSON.parse(line);
          const msg = data.response_message;
          if (!msg) continue;

          if (msg.type === "done") {
            finalResult = msg.result;
            apiTracker.complete(200);
            trackQueryResponseTime(graphBody.input, "graph-search", Date.now() - startTime, true);
          } else if (msg.type === "error") {
            pushLogEntry({ kind: "error", text: msg.message || "Error" });
            trackError(new Error(msg.message || "Graph workflow error"), { backend: "graph-search" });
            apiTracker.fail(new Error(msg.message));
            throw new Error(msg.message || "Graph workflow error");

          } else if (msg.type === "OrchestratorEvent" || msg.type === "MagenticOrchestratorMessageEvent") {
            const delta = (msg.delta || "").trim();
            if (delta) {
              pushLogEntry({ kind: "orch", text: delta });
              trackWorkflowEvent("orchestrator", { message: delta.substring(0, 200) });
            }

          } else if (msg.type === "AgentEvent" || msg.type === "MagenticAgentMessageEvent") {
            const delta = (msg.delta || "").trim();
            if (delta) {
              const kind = delta.startsWith("[QUERY]") ? "query" : delta.startsWith("[RESULT]") ? "result" : "orch";
              pushLogEntry({ kind, text: delta });
              trackWorkflowEvent(kind === "query" ? "cypher_query" : kind === "result" ? "query_result" : "agent", { message: delta.substring(0, 200) });
            }

          } else if (msg.type === "WorkflowOutputEvent" || msg.type === "WorkflowFinalResultEvent") {
            let text = msg.delta || msg.result || "";
            text = text.replace(/^Workflow output event:\s*/i, "").trim();
            if (text) {
              const elapsed = Date.now() - startTime;
              setMessagesFn(m => {
                const last = m[m.length - 1];
                if (last && last.role === "assistant" && last.speaker === "graph") {
                  return [...m.slice(0, -1), { role: "assistant", speaker: "graph", text, elapsed }];
                }
                return [...m, { role: "assistant", speaker: "graph", text, elapsed }];
              });
            }
          }
        } catch (e) {
          if (e.message?.includes("workflow error")) throw e;
        }
      }
    }

    return { status: "ok", output_text: finalResult || "(no response)", response_id: null };
  };

  const sendMessage = async (text) => {
    const msg = text || chatInput.trim();
    if (!msg || chatLoading || sendingRef.current) return;
    sendingRef.current = true;

    setError(null);
    setChatInput("");
    setChatLoading(true);
    setMessages(m => [...m, { role: "user", text: msg }]);

    let token = accessToken;
    if (selectedBackend !== "agent-framework" && selectedBackend !== "graph-search") {
      if (!token) token = await getToken();
      if (!token) { setChatLoading(false); sendingRef.current = false; return; }
    }

    try {
      const body = {
        agent_name: AGENT_NAME,
        message: msg,
      };
      if (previousResponseId) {
        body.previous_response_id = previousResponseId;
      }
      const data = await callChatApi(body, token);
      // AF backend streams messages directly to UI — skip handleChatResponse to avoid duplicates
      if (selectedBackend === "agent-framework" || selectedBackend === "graph-search") {
        if (data.response_id) setPreviousResponseId(data.response_id);
      } else {
        handleChatResponse(data);
      }
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setChatLoading(false);
      sendingRef.current = false;
    }
  };

  const handleApprovalSubmit = async (approve) => {
    if (submittingApprovalRef.current) return;
    if (!pendingApprovals || !pendingApprovalResponseId) return;
    submittingApprovalRef.current = true;

    let token = accessToken;
    if (!token) token = await getToken();
    if (!token) return;

    setChatLoading(true);
    try {
      const data = await callChatApi({
        agent_name: AGENT_NAME,
        previous_response_id: pendingApprovalResponseId,
        approvals: pendingApprovals.map(a => ({
          approval_request_id: a.id,
          approve,
        })),
      }, token);

      setPendingApprovals(null);
      setPendingApprovalResponseId(null);
      handleChatResponse(data);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setChatLoading(false);
      submittingApprovalRef.current = false;
    }
  };

  const handleOAuthContinue = async () => {
    if (!oauthResponseId) return;

    let token = accessToken;
    if (!token) token = await getToken();
    if (!token) return;

    setChatLoading(true);
    setOauthConsentLink(null);
    try {
      const data = await callChatApi({
        agent_name: AGENT_NAME,
        previous_response_id: oauthResponseId,
        action: "continue",
      }, token);

      setOauthResponseId(null);
      handleChatResponse(data);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setChatLoading(false);
    }
  };

  const clearChat = () => {
    setMessages([]);
    setPreviousResponseId(null);
    setPendingApprovals(null);
    setPendingApprovalResponseId(null);
    setOauthConsentLink(null);
    setOauthResponseId(null);
    setActiveThreadId(null);
    setAfSessionId(null);
  };

  const handleBackendChange = (e) => {
    setSelectedBackend(e.target.value);
    clearChat();
  };

  // ——— Chat History ————————————————————————————————————————

  const loadThreads = useCallback(async () => {
    let token = accessToken;
    if (!token) token = await getToken();
    if (!token) return;

    setThreadsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/threads?limit=20`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setThreads(data.threads || []);
      }
    } catch {
      // silently ignore — history is non-critical
    } finally {
      setThreadsLoading(false);
    }
  }, [accessToken, getToken]);

  const loadThread = async (threadId) => {
    let token = accessToken;
    if (!token) token = await getToken();
    if (!token) return;

    setChatLoading(true);
    try {
      const res = await fetch(`${API_BASE}/threads/${threadId}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setMessages(data.messages || []);
        setPreviousResponseId(data.last_response_id || null);
        setActiveThreadId(data.id);
        setPendingApprovals(null);
        setPendingApprovalResponseId(null);
        setOauthConsentLink(null);
        setOauthResponseId(null);
      }
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setChatLoading(false);
    }
  };

  // Load threads when authenticated
  useEffect(() => {
    if (isAuthenticated && accessToken) {
      loadThreads();
    }
  }, [isAuthenticated, accessToken, loadThreads]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  // ——— Render ———————————————————————————————————————————————

  if (!isAuthenticated) {
    return (
      <div className="login-container">
        <div className="login-card">
          <div className="login-icon">&#128161;</div>
          <h1>TalentIQ</h1>
          <p>AI-powered talent matching platform. Find candidates, match demands, and analyze bench resources.</p>
          <button className="btn-primary" onClick={login}>Sign in with Microsoft</button>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      {/* ——— Sidebar ——————————————————————————————————————— */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <span className="sidebar-icon">&#128161;</span>
          <span className="sidebar-title">TalentIQ</span>
        </div>

        <div className="sidebar-section sidebar-questions">
          {QUICK_QUESTION_CATEGORIES.map((cat, ci) => (
            <CollapsibleCategory key={ci} label={cat.label} defaultOpen={ci === 0}>
              {cat.questions.map((q, qi) => (
                <button key={qi} className="quick-btn" disabled={chatLoading}
                  onClick={() => sendMessage(q)}>
                  {q}
                </button>
              ))}
            </CollapsibleCategory>
          ))}
        </div>

        {/* ——— Chat History ——————————————————————————————— */}
        <div className="sidebar-section sidebar-history">
          <CollapsibleCategory label="Chat History" defaultOpen={false}>
            <button className="quick-btn history-refresh" disabled={threadsLoading}
              onClick={loadThreads}>
              {threadsLoading ? "Loading…" : "↻ Refresh"}
            </button>
            <button className="quick-btn history-new" disabled={chatLoading}
              onClick={clearChat}>
              + New Chat
            </button>
            {threads.length === 0 && !threadsLoading && (
              <p className="history-empty">No conversations yet</p>
            )}
            {threads.map((t) => (
              <button
                key={t.id}
                className={`quick-btn history-item ${activeThreadId === t.id ? "active" : ""}`}
                disabled={chatLoading}
                onClick={() => loadThread(t.id)}
                title={t.preview}
              >
                <span className="history-preview">{t.preview || "(no preview)"}</span>
                {t.created_at && (
                  <span className="history-date">
                    {new Date(t.created_at).toLocaleDateString()}
                  </span>
                )}
              </button>
            ))}
          </CollapsibleCategory>
        </div>

        <div className="sidebar-footer">
          <div className="user-info">
            <span className="user-avatar">
              {(account?.name || account?.username || "U")[0].toUpperCase()}
            </span>
            <span className="user-name">{account?.name || account?.username}</span>
          </div>
          <button className="btn-logout" onClick={logout}>Sign out</button>
        </div>
      </aside>

      {/* ——— Main content ————————————————————————————————— */}
      <main className="main-content">
        {error && (
          <div className="error-bar">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="error-close">&times;</button>
          </div>
        )}

        {needsConsent && (
          <div className="consent-bar">
            <span>Additional consent required for Foundry access.</span>
            <button className="btn-primary btn-sm" onClick={consentAndGetToken}>Grant consent</button>
          </div>
        )}

        {/* ——— Chat ——————————————————————————————————————— */}
        <div className="chat-container">
          <div className="chat-header">
            <h2>TalentIQ Assistant</h2>
            <div className="chat-header-actions">
              <select
                className="backend-select"
                value={selectedBackend}
                onChange={handleBackendChange}
                disabled={chatLoading}
              >
                {BACKENDS.map(b => (
                  <option key={b.id} value={b.id}>{b.label}</option>
                ))}
              </select>
              <button className="btn-ghost" onClick={clearChat}>Clear chat</button>
            </div>
          </div>

          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="chat-empty">
                <div className="chat-empty-icon">&#128161;</div>
                <h3>Ask me about talent</h3>
                <p>I can find candidates by skill and location, match demands, analyze bench resources, and more.</p>
              </div>
            )}

            {messages.filter(m => m.speaker !== "run-log").map((m, i) =>
              <Bubble key={i} role={m.role} text={m.text} elapsed={m.elapsed} />
            )}

            {/* OAuth consent link */}
            {oauthConsentLink && (
              <div className="oauth-bar">
                <a href={oauthConsentLink} target="_blank" rel="noopener noreferrer" className="btn-primary btn-sm">
                  Authorize MCP Tool
                </a>
                <button className="btn-primary btn-sm" onClick={handleOAuthContinue}>
                  Continue after authorization
                </button>
              </div>
            )}

            {chatLoading && (
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
            )}

            <div ref={chatEndRef} />
          </div>

          {/* MCP approval overlay */}
          {pendingApprovals && (
            <ApprovalDialog approvals={pendingApprovals} onSubmit={handleApprovalSubmit} disabled={chatLoading} />
          )}

          <div className="chat-input-bar">
            <div className="chat-input-row">
              <textarea
                className="chat-input"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about candidates, demands, bench..."
                rows={1}
                disabled={chatLoading}
              />
              <button className="btn-send" onClick={() => sendMessage()}
                disabled={chatLoading || !chatInput.trim()}>
                &#10148;
              </button>
            </div>
          </div>
        </div>
      </main>

      {/* ——— Right-side Run Log Panel ———————————————————— */}
      {selectedBackend === "graph-search" && (
        <RunLogPanel runs={runLogRuns} onClear={() => setRunLogRuns([])} />
      )}
    </div>
  );
}
