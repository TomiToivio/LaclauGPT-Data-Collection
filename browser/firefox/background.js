const DEFAULT_ENDPOINT = "http://127.0.0.1:8765/capture";

async function endpoint() {
  const stored = await browser.storage.local.get("captureEndpoint");
  return stored.captureEndpoint || DEFAULT_ENDPOINT;
}

async function sendCapture(payload) {
  const target = await endpoint();
  const response = await fetch(target, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error(`capture backend returned ${response.status}`);
  }
  return response.json().catch(() => ({ ok: true }));
}

async function captureActiveTab() {
  const tabs = await browser.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab?.id) throw new Error("no active tab");
  const payload = await browser.tabs.sendMessage(tab.id, { type: "capture-current-page" });
  return sendCapture(payload);
}

browser.browserAction.onClicked.addListener(() => {
  captureActiveTab().catch((error) => console.warn("LaclauGPT capture failed", error));
});

browser.runtime.onMessage.addListener((message) => {
  if (message?.type === "capture-payload" && message.payload) {
    return sendCapture(message.payload);
  }
  return undefined;
});
