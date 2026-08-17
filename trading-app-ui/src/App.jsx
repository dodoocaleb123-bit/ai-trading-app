import React, { useState, useEffect } from 'react';
import { Shield, History, BookOpen, Send, RefreshCw, Menu, X } from 'lucide-react';
import { auditSignal, fetchHistory as getHistoryFromApi } from './api';

export default function App() {
  const [activeTab, setActiveTab] = useState('audit'); // 'audit' | 'history' | 'rules'
  const [message, setMessage] = useState('');
  const [chatLogs, setChatLogs] = useState([]);
  const [selectedAudit, setSelectedAudit] = useState(null);
  const [historyLogs, setHistoryLogs] = useState([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [backendStatus, setBackendStatus] = useState('Checking...');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  // Strategy Rule Injection State
  const [ruleText, setRuleText] = useState('');
  const [ruleStatus, setRuleStatus] = useState('');
  const [ruleLoading, setRuleLoading] = useState(false);

  const API_URL = import.meta.env.VITE_API_BASE_URL || 'https://ai-trading-backend-7z9h.onrender.com';

  // Check backend connectivity on mount
  useEffect(() => {
    fetch(`${API_URL}/`)
      .then((res) => res.json())
      .then(() => setBackendStatus('Backend Connected'))
      .catch(() => setBackendStatus('Backend Disconnected'));
  }, [API_URL]);

  // Fetch Trade History using the externalized API module
  const handleFetchHistory = async () => {
    setLoadingHistory(true);
    try {
      const data = await getHistoryFromApi();
      if (data.status === 'success') {
        setHistoryLogs(data.history || []);
      }
    } catch (err) {
      console.error('Failed to fetch trade history:', err);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setMobileNavOpen(false); // Auto-close mobile menu on selection
    if (tab === 'history') {
      handleFetchHistory();
    }
  };

  const handleSendAudit = async (e) => {
    e.preventDefault();
    if (!message.trim()) return;

    const userMessage = { id: Date.now(), role: 'user', text: message };
    setChatLogs((prev) => [...prev, userMessage]);
    const currentInput = message;
    setMessage('');

    try {
      const data = await auditSignal(currentInput);

      const aiMessage = {
        id: Date.now() + 1,
        role: 'ai',
        audit: data,
        rawText: currentInput,
      };
      setChatLogs((prev) => [...prev, aiMessage]);
      setSelectedAudit(data);
    } catch (err) {
      console.error('Error running audit:', err);
    }
  };

  const handleAddRule = async (e) => {
    e.preventDefault();
    if (!ruleText.trim()) return;

    setRuleLoading(true);
    setRuleStatus('');

    try {
      const response = await fetch(`${API_URL}/add-rule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_content: ruleText }),
      });
      const data = await response.json();
      
      if (response.ok) {
        setRuleStatus('✅ Rule successfully injected into AI memory!');
        setRuleText('');
      } else {
        setRuleStatus(`❌ Error: ${data.detail || 'Failed to save rule'}`);
      }
    } catch (err) {
      setRuleStatus('❌ Network error connecting to backend.');
    } finally {
      setRuleLoading(false);
    }
  };

  return (
    <div className="flex flex-col md:flex-row h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">
      
      {/* Mobile Top Navigation Header */}
      <div className="md:hidden flex items-center justify-between p-4 bg-slate-900 border-b border-slate-800 z-50">
        <div className="flex items-center gap-3">
          <Shield className="w-6 h-6 text-indigo-500" />
          <h1 className="font-bold text-base text-white">Trading Guard AI</h1>
        </div>
        <button
          onClick={() => setMobileNavOpen(!mobileNavOpen)}
          className="p-2 text-slate-300 hover:text-white hover:bg-slate-800 rounded-lg transition"
          aria-label="Toggle menu"
        >
          {mobileNavOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Sidebar Navigation */}
      <aside
        className={`${
          mobileNavOpen ? 'block' : 'hidden'
        } md:block w-full md:w-64 bg-slate-900 border-b md:border-b-0 md:border-r border-slate-800 flex-shrink-0 flex flex-col p-4 z-40`}
      >
        <div className="hidden md:flex items-center gap-3 px-2 py-4 border-b border-slate-800 mb-6">
          <Shield className="w-7 h-7 text-indigo-500" />
          <h1 className="font-bold text-lg text-white">Trading Guard AI</h1>
        </div>

        <nav className="flex flex-col gap-2 flex-1">
          <button
            onClick={() => handleTabChange('audit')}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'audit'
                ? 'bg-indigo-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            }`}
          >
            <Shield className="w-4 h-4" />
            Live Trade Audit
          </button>

          <button
            onClick={() => handleTabChange('history')}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'history'
                ? 'bg-indigo-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            }`}
          >
            <History className="w-4 h-4" />
            Trade History
          </button>

          <button
            onClick={() => handleTabChange('rules')}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition ${
              activeTab === 'rules'
                ? 'bg-indigo-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            }`}
          >
            <BookOpen className="w-4 h-4" />
            Strategy Rules
          </button>
        </nav>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col bg-slate-950 overflow-hidden">
        {/* Sub-Header */}
        <header className="h-14 md:h-16 border-b border-slate-800 flex items-center justify-between px-4 md:px-6 bg-slate-900/50 flex-shrink-0">
          <h2 className="text-sm md:text-lg font-semibold text-white truncate">
            {activeTab === 'audit' && '# live-trade-audit'}
            {activeTab === 'history' && '# trade-history-logs'}
            {activeTab === 'rules' && '# strategy-rules-knowledgebase'}
          </h2>
          <span className="px-2.5 py-1 rounded-full text-[10px] md:text-xs font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800 whitespace-nowrap">
            {backendStatus}
          </span>
        </header>

        {/* Tab 1: Live Audit Chat View */}
        {activeTab === 'audit' && (
          <div className="flex-1 flex flex-col md:flex-row overflow-hidden">
            {/* Chat Area */}
            <div className="flex-1 flex flex-col min-h-0">
              <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
                {chatLogs.length === 0 ? (
                  <div className="text-center text-slate-500 my-auto pt-12 md:pt-20">
                    <p className="text-xs md:text-sm">
                      No trade audits yet. Enter a signal below to analyze against your strategy rules.
                    </p>
                  </div>
                ) : (
                  chatLogs.map((log) => (
                    <div
                      key={log.id}
                      onClick={() => log.audit && setSelectedAudit(log.audit)}
                      className={`p-4 rounded-xl border max-w-2xl cursor-pointer transition ${
                        log.role === 'user'
                          ? 'bg-slate-900 border-slate-800 ml-auto'
                          : 'bg-slate-900/80 border-indigo-900/50 hover:border-indigo-500'
                      }`}
                    >
                      {log.role === 'user' ? (
                        <p className="text-sm text-slate-200">{log.text}</p>
                      ) : (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold uppercase tracking-wider text-indigo-400">
                              Verdict: {log.audit.verdict}
                            </span>
                            <span className="text-xs text-slate-400">Confidence: {log.audit.confidence_score}%</span>
                          </div>
                          <p className="text-sm text-slate-300">{log.audit.summary}</p>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              {/* Chat Input */}
              <form onSubmit={handleSendAudit} className="p-3 md:p-4 border-t border-slate-800 bg-slate-900/40 flex gap-2 md:gap-3 flex-shrink-0">
                <input
                  type="text"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Type signal (e.g. Buy EURUSD at 1.0850, SL 1.0820, TP 1.0940)..."
                  className="flex-1 min-w-0 bg-slate-900 border border-slate-800 rounded-lg px-3 md:px-4 py-2 md:py-2.5 text-xs md:text-sm text-white focus:outline-none focus:border-indigo-500"
                />
                <button
                  type="submit"
                  className="bg-indigo-600 hover:bg-indigo-500 text-white px-3 md:px-5 py-2 md:py-2.5 rounded-lg text-xs md:text-sm font-semibold flex items-center gap-1.5 md:gap-2 transition flex-shrink-0"
                >
                  <Send className="w-3.5 h-3.5 md:w-4 md:h-4" />
                  <span>Send</span>
                </button>
              </form>
            </div>

            {/* Audit Inspector Panel */}
            <aside className="w-full md:w-80 border-t md:border-t-0 md:border-l border-slate-800 p-4 md:p-6 bg-slate-900/30 overflow-y-auto max-h-56 md:max-h-none flex-shrink-0">
              <h3 className="text-sm md:text-md font-bold text-white mb-3 md:mb-4">Audit Inspector</h3>
              {selectedAudit ? (
                <div className="space-y-3 md:space-y-4 text-xs md:text-sm">
                  <div className="p-3 bg-slate-900 rounded-lg border border-slate-800">
                    <span className="text-xs text-slate-400">Verdict</span>
                    <p className="font-bold text-indigo-400">{selectedAudit.verdict}</p>
                  </div>
                  <div className="p-3 bg-slate-900 rounded-lg border border-slate-800">
                    <span className="text-xs text-slate-400">Risk/Reward Ratio</span>
                    <p className="font-semibold text-white">{selectedAudit.risk_reward_ratio}</p>
                  </div>
                  <div>
                    <span className="text-xs text-slate-400 font-semibold uppercase">Summary</span>
                    <p className="text-slate-300 mt-1">{selectedAudit.summary}</p>
                  </div>
                  {selectedAudit.violations?.length > 0 && (
                    <div>
                      <span className="text-xs text-red-400 font-semibold uppercase">Violations</span>
                      <ul className="list-disc pl-4 mt-1 text-slate-300 space-y-1">
                        {selectedAudit.violations.map((v, idx) => (
                          <li key={idx}>{v}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {selectedAudit.improvements?.length > 0 && (
                    <div>
                      <span className="text-xs text-emerald-400 font-semibold uppercase">Improvements</span>
                      <ul className="list-disc pl-4 mt-1 text-slate-300 space-y-1">
                        {selectedAudit.improvements.map((imp, idx) => (
                          <li key={idx}>{imp}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-xs text-slate-500">Select an audit card from the chat to inspect details.</p>
              )}
            </aside>
          </div>
        )}

        {/* Tab 2: Trade History View */}
        {activeTab === 'history' && (
          <div className="flex-1 p-4 md:p-6 overflow-y-auto">
            <div className="flex justify-between items-center mb-4 md:mb-6">
              <h3 className="text-base md:text-lg font-bold text-white">Logged Signals & Audit History</h3>
              <button
                onClick={handleFetchHistory}
                className="flex items-center gap-1.5 md:gap-2 text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 px-2.5 md:px-3 py-1.5 md:py-2 rounded-lg transition"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loadingHistory ? 'animate-spin' : ''}`} />
                <span>Refresh History</span>
              </button>
            </div>

            {historyLogs.length === 0 ? (
              <p className="text-slate-500 text-xs md:text-sm">No historical trade records found in Supabase.</p>
            ) : (
              <div className="grid gap-3 md:gap-4">
                {historyLogs.map((log) => {
                  let auditData = {};
                  try {
                    auditData = typeof log.audit_report === 'string' ? JSON.parse(log.audit_report) : log.audit_report;
                  } catch (e) {
                    auditData = {};
                  }

                  return (
                    <div key={log.id} className="p-3 md:p-4 bg-slate-900 border border-slate-800 rounded-xl space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="font-bold text-indigo-400 text-xs md:text-sm">{log.asset_pair || 'CHAT_SIGNAL'}</span>
                        <span className="text-[10px] md:text-xs text-slate-500">{new Date(log.created_at).toLocaleString()}</span>
                      </div>
                      <p className="text-xs md:text-sm text-slate-300 font-mono bg-slate-950 p-2 rounded border border-slate-800/50 break-words">
                        {log.setup_notes}
                      </p>
                      {auditData.summary && (
                        <p className="text-xs text-slate-400">
                          <strong className="text-slate-200">AI Summary:</strong> {auditData.summary}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Strategy Rules View */}
        {activeTab === 'rules' && (
          <div className="flex-1 p-4 md:p-6 overflow-y-auto max-w-3xl">
            <h3 className="text-base md:text-lg font-bold text-white mb-2">Strategy Rules & Knowledge Base</h3>
            <p className="text-xs md:text-sm text-slate-400 mb-6">
              Teach your AI sentinel custom trading principles or constraints. The background scanner and chat auditor will immediately enforce these rules using vector embeddings.
            </p>

            {/* Strategy Rule Injection Form */}
            <form onSubmit={handleAddRule} className="space-y-4 mb-6">
              <textarea
                className="w-full p-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-indigo-500 placeholder-slate-500"
                rows="3"
                placeholder="e.g., Avoid trading EUR/USD during major US economic news releases or high volatility..."
                value={ruleText}
                onChange={(e) => setRuleText(e.target.value)}
              />
              <button
                type="submit"
                disabled={ruleLoading}
                className="w-full py-2.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 rounded-lg font-semibold text-sm transition shadow-md text-white"
              >
                {ruleLoading ? 'Injecting into Memory...' : 'Inject Rule into AI Memory'}
              </button>
            </form>

            {ruleStatus && (
              <p className="text-xs mb-6 text-center font-medium text-slate-300">
                {ruleStatus}
              </p>
            )}

            <div className="p-4 md:p-5 bg-slate-900 border border-slate-800 rounded-xl space-y-3">
              <h4 className="font-semibold text-indigo-400 text-xs md:text-sm">Active RAG Integration</h4>
              <p className="text-xs text-slate-300 leading-relaxed">
                Whenever a manual trade signal is entered or an automated 24/7 background scan triggers, the system matches signal text embeddings against your stored strategy vectors using cosine similarity search (<code className="text-indigo-300">match_strategy_rules</code>).
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}