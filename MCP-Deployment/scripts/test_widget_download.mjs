// Regression test for the MCP Apps host-mediated PNG button.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const html = fs.readFileSync(fileURLToPath(new URL("../services/hackbrowser/screenshot_widget.html", import.meta.url)), "utf8");
const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1];
assert.ok(script, "inline widget script missing");
assert.ok(!html.includes("URL.createObjectURL"), "obsolete iframe download code remains");
assert.ok(!html.includes("/captures/"), "obsolete public endpoint remains");

const listeners = new Map();
const elements = new Map();
for (const name of ["preview", "status", "download", "details",
                   "verification-card", "verification-answer",
                   "verification-positions", "verification-status",
                   "verification-submit", "pick-input", "pick-confirm",
                   "pick-tile", "refresh-verification", "resume-agent"]) {
  elements.set(name, {
    textContent: "", value: "",
    hidden: name === "verification-card",
    disabled: ["download", "verification-submit"].includes(name),
    style: { display: "none" },
    classList: { add() {}, remove() {} },
    getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 400 }; },
    addEventListener(event, handler) { this[event] = handler; },
  });
}
const sent = [];
let context;
const parent = {
  postMessage(message) {
    sent.push(message);
    if (message.method === "tools/call") {
      context.window.onMessage({
        source: parent, data: { jsonrpc: "2.0", id: message.id,
          result: { content: [{ type: "text", text: '{"ok":true}' }] } },
      });
    }
    if (message.method === "ui/download-file") {
      context.window.onMessage({
        source: parent, data: { jsonrpc: "2.0", id: message.id, result: {} },
      });
    }
  },
};
const window = {
  parent,
  addEventListener(name, callback) {
    if (name === "message") this.onMessage = callback;
    else listeners.set(name, callback);
  },
};
const document = {
  body: { scrollHeight: 360 },
  documentElement: { style: { setProperty() {} } },
  getElementById(name) { return elements.get(name); },
};
context = vm.createContext({
  window, document,
  requestAnimationFrame(callback) { callback(); },
  setTimeout() { return 1; },
  clearTimeout() {},
  atob,
  File: class File { constructor(bytes, name, options) {
    this.name = name; this.bytes = bytes; this.type = options.type;
  } },
  Uint8Array, Promise, Number, Math, Error,
});
vm.runInContext(script, context, { filename: "screenshot_widget.html" });
assert.equal(sent[0].method, "ui/initialize");
window.onMessage({
  source: parent,
  data: {
    jsonrpc: "2.0", id: 1,
    result: { protocolVersion: "2026-01-26", hostCapabilities: { downloadFile: {} } },
  },
});
const png = Buffer.from("89504e470d0a1a0a", "hex");
window.onMessage({
  source: parent,
  data: {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: { content: [
      { type: "text", text: JSON.stringify({ bytes: png.length, mime_type: "image/png" }) },
      { type: "image", mimeType: "image/png", data: png.toString("base64") },
    ] },
  },
});
assert.equal(elements.get("download").disabled, false);
await elements.get("download").click();
const request = sent.find(message => message.method === "ui/download-file");
assert.ok(request, "host download request not issued");
assert.equal(request.params.contents[0].type, "resource");
assert.equal(request.params.contents[0].resource.uri, "file:///hackbrowser-screenshot.png");
assert.equal(request.params.contents[0].resource.mimeType, "image/png");
assert.equal(request.params.contents[0].resource.blob, png.toString("base64"));
assert.equal(elements.get("download").disabled, false);
assert.match(elements.get("status").textContent, /요청을 전달했습니다/);

// A human reads the picture, chooses two positions, and explicitly submits.
window.onMessage({
  source: parent,
  data: {
    jsonrpc: "2.0", method: "ui/notifications/tool-result",
    params: { content: [
      { type: "text", text: JSON.stringify({
        bytes: png.length, mime_type: "image/png",
        verification: {
          required: true, id: "session-one-time", viewport: { width: 1200, height: 800 },
        },
      }) },
      { type: "image", mimeType: "image/png", data: png.toString("base64") },
    ] },
  },
});
assert.equal(elements.get("verification-card").hidden, false);
elements.get("verification-answer").value = "1234";
elements.get("verification-answer").input();
elements.get("pick-input").click();
elements.get("preview").click({ clientX: 100, clientY: 100 });
elements.get("pick-confirm").click();
elements.get("preview").click({ clientX: 300, clientY: 200 });
assert.equal(elements.get("verification-submit").disabled, false);
await elements.get("verification-submit").click();
const request2 = sent.find(message => message.method === "tools/call");
assert.equal(request2.params.name, "browser_submit_verification");
assert.equal(request2.params.arguments.verification_id, "session-one-time");
assert.equal(request2.params.arguments.answer, "1234");
assert.equal(request2.params.arguments.input_x, 200);
assert.equal(request2.params.arguments.input_y, 200);
assert.equal(request2.params.arguments.confirm_x, 600);
assert.equal(request2.params.arguments.confirm_y, 400);
assert.equal(elements.get("verification-answer").value, "");
assert.equal(elements.get("verification-submit").disabled, true);
assert.ok(html.includes("browser_verification_click"), "manual CAPTCHA tile click handler missing");
assert.ok(html.includes("browser_screenshot"), "manual CAPTCHA screenshot refresh missing");
assert.ok(html.includes("sendFollowUpMessage"), "resume-agent fallback missing");
console.log("MCP Apps manual CAPTCHA card tool submission: PASS");
console.log("MCP Apps host-mediated PNG download: PASS");
