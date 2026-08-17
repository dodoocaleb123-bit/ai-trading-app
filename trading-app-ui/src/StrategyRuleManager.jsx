import React, { useState } from 'react';

export default function StrategyManager() {
  const [ruleText, setRuleText] = useState('');
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!ruleText.trim()) return;

    setLoading(true);
    setStatus('');

    try {
      const response = await fetch('http://localhost:8000/add-rule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule_content: ruleText }),
      });
      const data = await response.json();
      
      if (response.ok) {
        setStatus('✅ Rule successfully injected into AI memory!');
        setRuleText('');
      } else {
        setStatus(`❌ Error: ${data.detail || 'Failed to save rule'}`);
      }
    } catch (err) {
      setStatus('❌ Network error connecting to backend.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 bg-slate-800 rounded-xl shadow-lg text-white max-w-xl mx-auto my-6 border border-slate-700">
      <h3 className="text-xl font-bold mb-2 flex items-center gap-2">
        <span>🧠</span> Train AI Strategy Rules
      </h3>
      <p className="text-sm text-slate-400 mb-4">
        Teach your AI sentinel custom trading principles or constraints. The background scanner and chat auditor will immediately enforce these rules.
      </p>
      
      <form onSubmit={handleSubmit} className="space-y-4">
        <textarea
          className="w-full p-3 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 focus:outline-none focus:border-blue-500 placeholder-slate-500"
          rows="3"
          placeholder="e.g., Avoid trading EUR/USD during major US economic news releases or high volatility..."
          value={ruleText}
          onChange={(e) => setRuleText(e.target.value)}
        />
        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 rounded-lg font-semibold text-sm transition shadow-md"
        >
          {loading ? 'Injecting into Memory...' : 'Inject Rule into AI Memory'}
        </button>
      </form>
      
      {status && (
        <p className="text-xs mt-3 text-center font-medium text-slate-300">
          {status}
        </p>
      )}
    </div>
  );
}