# HackBrowser public beta — demo checklist

This is a **reproducible walkthrough**, not a recording or a performance
benchmark. It is designed to be screen-recorded later for the GitHub README.

## Preparation

1. Install the [standalone browser](../standalone/README.md) locally, or
   connect to an already authenticated full HackBrowser MCP installation.
2. Open a fresh empty GUI tab and connect an MCP client.
3. Use a public, non-sensitive site such as Wikipedia. Avoid logging in,
   buying items, collecting personal data or triggering CAPTCHAs.

## Demo prompt

> Open https://en.wikipedia.org/wiki/Gundam. Show me a brief page observation
> with element references. Click a safe article link using only a reference,
> confirm that navigation happened, and show a screenshot of the result.

## Intended tool sequence

1. `browser_tabs` — select the intended tab ID
2. `browser_navigate` — navigate to the public page
3. `browser_wait_for` — wait for a distinctive page element
4. **`browser_observe`** — get `snapshot_id` and elements `e1`, `e2` …
5. **`browser_act`** — select a safe link using the matching `ref`
6. `browser_page_text` — confirm the title and URL changed
7. `browser_screenshot` — show the browser image in the MCP Apps card

The assistant should **not** treat `browser_act.ok` as proof of navigation;
it must read the actual destination afterward. If an element has expired or
is no longer visible, re-observe rather than replaying the same click.

## Recording guidance

Record 20–45 seconds with the user prompt, AI tool actions and the screenshot
card visible. Show the actual tool responses and no fabricated timings. Blur
tokens, account names, session URLs, personal details and browser profiles.

Place the *verified* demo GIF or MP4 in `assets/` and link it from README only
after the recording is successfully captured. Do not present mocks as live runs.

## What is verified?

The previous v1.0.20 release was exercised against Wikipedia, GitHub and
Naver Shopping for basic navigation, clicks, tabs and workflow steps.
`browser_observe` and `browser_act` are new and require fresh live validation
on a published build. Standalone Docker has not yet been tested on every host.
