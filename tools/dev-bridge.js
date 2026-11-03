(() => {
  const streams = new Map();
  const context = { pluginName: "astrbot_plugin_whale_home", locale: "zh-CN", isDark: true, demo: true };
  async function response(response) {
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || "Request failed");
    return body;
  }
  window.AstrBotPluginView = {
    ready: async () => context,
    getContext: () => context,
    onContext: () => () => {},
    apiGet: (endpoint, params = {}) =>
      fetch(`/api/${endpoint}?${new URLSearchParams(params)}`).then(response),
    apiPost: (endpoint, body) =>
      fetch(`/api/${endpoint}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }).then(response),
    upload: (endpoint, file) => {
      const form = new FormData();
      form.append("file", file);
      return fetch(`/api/${endpoint}`, { method: "POST", body: form }).then(response);
    },
    download: async (endpoint, params, filename) => {
      const result = await fetch(`/api/${endpoint}`);
      if (!result.ok) return response(result);
      const url = URL.createObjectURL(await result.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = filename || "whale-home.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      return { filename: link.download };
    },
    subscribeSSE: async (endpoint, handlers) => {
      const id = crypto.randomUUID();
      const stream = new EventSource(`/api/${endpoint}`);
      stream.onopen = () => handlers.onOpen?.();
      stream.onmessage = event =>
        handlers.onMessage?.({ raw: event.data, parsed: JSON.parse(event.data) });
      stream.onerror = () => handlers.onError?.();
      streams.set(id, stream);
      return id;
    },
    unsubscribeSSE: async id => {
      streams.get(id)?.close();
      streams.delete(id);
    },
  };
})();
