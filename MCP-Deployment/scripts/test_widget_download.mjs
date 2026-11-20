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
                   "verification-card", "verification-inputs", "verification-heading", "verification-answer",
                   "verification-positions", "verification-status",
                   "verification-submit", "pick-input", "pick-confirm",
                   "pick-tile", "refresh-verification", "resume-agent",
                   "live-toggle", "handoff-take", "handoff-return",
                   "handoff-state", "handoff-scroll", "handoff-up", "handoff-down"]) {
  elements.set(name, {
    textContent: "", value: "",
    hidden: name === "verification-card",
    disabled: ["download", "verification-submit"].includes(name),
    style: { display: "none" },
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {}, naturalWidth: 1200, naturalHeight: 800,
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
      const name = message.params.name;
      const payload = name.endsWith("browser_handoff_begin")
        ? {active:true, control_token:"test-capability-value", target_id:"gui-tab"}
        : name.endsWith("browser_handoff_end")
          ? {ok:true, returned_to_ai:true}
          : {ok:true};
      context.window.onMessage({
        source: parent, data: { jsonrpc: "2.0", id: message.id,
          result: { content: [{ type: "text", text: JSON.stringify(payload) }] } },
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
  addEventListener() {},
};
context = vm.createContext({
  window, document,
  requestAnimationFrame(callback) { callback(); },
  setTimeout() { return 1; },
  clearTimeout() {},
  setInterval() { return 1; },
  clearInterval() {},
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
    result: { protocolVersion: "2026-01-26", hostCapabilities: { downloadFile: {}, serverTools: {} },
      hostContext: { toolInfo: { tool: { name: "hackbrowser__browser_screenshot" } } } },
  },
});
const png = Buffer.from("89504e470d0a1a0a", "hex");
window.onMessage({
  source: parent,
  data: {
    jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: { content: [
      { type: "text", text: JSON.stringify({ bytes: png.length, mime_type: "image/png", target_id: "gui-tab" }) },
      { type: "image", mimeType: "image/png", data: png.toString("base64") },
    ] },
  },
});
assert.equal(elements.get("download").disabled, false);
// A screenshot has a target ID but does not imply a CAPTCHA or paused workflow.
assert.equal(elements.get("verification-card").hidden, true,
  "normal page must not display the CAPTCHA card");
assert.equal(elements.get("resume-agent").hidden, true,
  "normal page must not show a fake verification-resume button");
assert.equal(elements.get("verification-inputs").hidden, true,
  "normal page must keep CAPTCHA form hidden");
// When a workflow is paused without an active CAPTCHA, show only the
// resume control and explanatory status, not the challenge form.
window.onMessage({
  source: parent, data: { jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: { content: [
      {type: "text", text: JSON.stringify({
        bytes: png.length, mime_type: "image/png", target_id: "gui-tab",
        paused_workflow: {workflow_id: "demo-paused"},
      })},
      {type: "image", mimeType: "image/png", data: png.toString("base64")},
    ]},
  },
});
assert.equal(elements.get("verification-card").hidden, false);
assert.equal(elements.get("verification-inputs").hidden, true);
assert.equal(elements.get("resume-agent").hidden, false);
assert.match(elements.get("verification-heading").textContent, /일시정지/);
// An ordinary capture after the pause has cleared hides resume again.
window.onMessage({
  source: parent, data: { jsonrpc: "2.0",
    method: "ui/notifications/tool-result",
    params: { content: [
      {type: "text", text: JSON.stringify({
        bytes: png.length, mime_type: "image/png", target_id: "gui-tab",
      })},
      {type: "image", mimeType: "image/png", data: png.toString("base64")},
    ]},
  },
});
assert.equal(elements.get("verification-card").hidden, true);
assert.equal(elements.get("resume-agent").hidden, true);
await elements.get("download").click();
const request = sent.find(message => message.method === "ui/download-file");
assert.ok(request, "host download request not issued");
assert.equal(request.params.contents[0].type, "resource");
assert.equal(request.params.contents[0].resource.uri, "file:///hackbrowser-screenshot.png");
assert.equal(request.params.contents[0].resource.mimeType, "image/png");
assert.equal(request.params.contents[0].resource.blob, png.toString("base64"));
assert.equal(elements.get("download").disabled, false);
assert.match(elements.get("status").textContent, /요청을 전달했습니다/);

// A user explicitly takes over the GUI, sends one click, and returns control.
assert.equal(elements.get("handoff-take").disabled, false);
await elements.get("handoff-take").click();
assert.equal(elements.get("handoff-return").hidden, false);
assert.ok(sent.some(message => message.method === "tools/call" &&
  message.params.name === "hackbrowser__browser_handoff_begin"));
await elements.get("preview").click({clientX: 100, clientY: 100});
const handoffClick = sent.find(message => message.method === "tools/call" &&
  message.params.name === "hackbrowser__browser_handoff_input");
assert.ok(handoffClick, "manual click tool not invoked");
assert.equal(handoffClick.params.arguments.target_id, "gui-tab");
assert.equal(handoffClick.params.arguments.action, "click");
assert.equal(handoffClick.params.arguments.control_token, "test-capability-value");
await elements.get("handoff-return").click();
assert.equal(elements.get("handoff-return").hidden, true);
assert.ok(sent.some(message => message.method === "tools/call" &&
  message.params.name === "hackbrowser__browser_handoff_end"));

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
assert.equal(elements.get("verification-inputs").hidden, false);
assert.equal(elements.get("resume-agent").hidden, true);
elements.get("verification-answer").value = "1234";
elements.get("verification-answer").input();
elements.get("pick-input").click();
elements.get("preview").click({ clientX: 100, clientY: 100 });
elements.get("pick-confirm").click();
elements.get("preview").click({ clientX: 300, clientY: 200 });
assert.equal(elements.get("verification-submit").disabled, false);
await elements.get("verification-submit").click();
const request2 = sent.find(message => message.method === "tools/call" &&
  message.params.name === "hackbrowser__browser_submit_verification");
assert.equal(request2.params.name, "hackbrowser__browser_submit_verification");
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
const normalizedMissing = vm.runInContext(
  'friendlyToolError(new Error("MCP Resource not found")).message', context);
assert.match(normalizedMissing, /HackBrowser/);
assert.match(normalizedMissing, /새로고침/);
const toolError = vm.runInContext(
  'toolFailure({isError:true, content:[{type:"text",text:"MCP Resource not found"}]})',
  context);
assert.equal(toolError, "MCP Resource not found");
console.log("MCP Apps prefixed tool dispatch and stale-tool diagnostic: PASS");
console.log("MCP Apps manual CAPTCHA card tool submission: PASS");
console.log("MCP Apps host-mediated PNG download: PASS");
