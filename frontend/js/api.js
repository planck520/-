(function () {
  const query = new URLSearchParams(window.location.search);
  const explicitBase = query.get("api") || window.localStorage.getItem("iot_api_base");
  const defaultBase = window.location.protocol === "file:" ? "http://127.0.0.1:5000" : window.location.origin;
  const API_BASE = (explicitBase || defaultBase).replace(/\/$/, "");

  async function request(path, options = {}) {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        payload = { raw: text };
      }
    }
    if (!response.ok) {
      const message = payload && payload.error ? payload.error : `HTTP ${response.status}`;
      throw new Error(message);
    }
    return payload;
  }

  function get(path) {
    return request(path);
  }

  function post(path, payload) {
    return request(path, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
  }

  async function streamChat(message, onToken, signal) {
    const response = await fetch(`${API_BASE}/api/v1/assistant/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, stream: true }),
      signal,
    });
    if (!response.ok || !response.body) {
      const text = await response.text();
      throw new Error(text || `HTTP ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((item) => item.startsWith("data:"));
        if (!line) continue;
        const raw = line.slice(5).trim();
        if (raw === "[DONE]") return;
        try {
          const parsed = JSON.parse(raw);
          onToken(parsed.token || "");
        } catch (error) {
          onToken(raw);
        }
      }
    }
  }

  window.IotApi = {
    base: API_BASE,
    get,
    post,
    streamChat,
  };
})();
