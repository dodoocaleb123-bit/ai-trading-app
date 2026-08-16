const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'https://ai-trading-backend-7z9h.onrender.com';

export async function auditSignal(signalText) {
  const response = await fetch(`${API_BASE_URL}/chat-audit`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message: signalText }),
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }

  return await response.json();
}

export async function fetchHistory() {
  const response = await fetch(`${API_BASE_URL}/history`);
  
  if (!response.ok) {
    throw new Error(`API error: ${response.statusText}`);
  }

  return await response.json();
}