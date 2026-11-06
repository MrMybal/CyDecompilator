---
id: observations
title: Compare output, network and graphical behavior
description: Record and compare output, file changes, network activity and graphical scenarios.
section: Investigate behavior
parent: investigation
order: 12
revision: 2
---

In **Investigation → Version behavior**, configure two versions and the same repeatable scenario. Set launch arguments, stdin, initial files, deadlines and the observation driver. Start only the application you intend to test; recorded behavior comes from launched processes and supported child processes.

```diagram
{"type": "flow", "title": "From scenario to conclusion", "nodes": [{"id": "step-0", "label": "1. Choose versions", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Define actions", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Run separately", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Capture evidence", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Compare", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Scope the claim", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Choose versions** — Record identities and prerequisites.
2. **Define actions** — Use the same inputs and checks.
3. **Run separately** — Bound time and process ownership.
4. **Capture evidence** — Outputs, files, screens, network.
5. **Compare** — Inspect differences and missing data.
6. **Scope the claim** — Only observed checks are established.


## Choose a driver {#choose-a-driver}

| Driver | Requirements and scope |
|---|---|
| Windows controls | Accessible UI Automation controls; private .NET Framework recorder |
| Chromium | Compatible Chrome/Edge executable, scenario URL and Node.js 22+ |
| Electron renderer | Application executable, Node.js 22+ and, if ambiguous, the exact renderer URL |

Build steps with the graphical scenario editor, or use advanced JSON. CSS selectors must identify one element in web drivers. For example, adapt these selectors and expected text to your own application:

```json
[
  {"action":"fill","selector":"#name","text":"Report"},
  {"action":"click","selector":"#go"},
  {"action":"assertText","selector":"#result","text":"Done","timeoutMs":5000},
  {"action":"snapshot"}
]
```

Windows selectors use objects such as an automationId instead of CSS. Available actions depend on the driver; password filling is refused. The scenario editor offers action, selector, text and delay fields, plus add/update/remove controls.

## Read the evidence {#read-the-evidence}

**Observed differences** compares enabled outputs, files, control states, HTTP/TCP observations and console messages. **Captured screens** loads hash-verified images for both versions at the chosen step. **Network recordings** displays request method/URL/status/MIME/size, initiator stacks where available and sampled process TCP connections. Observation near a step is temporal association, not proof that the step caused a request.

HTTP capture omits headers, cookies, bodies and WebSocket frames. TCP sampling can miss short connections and does not record UDP or packet contents. Electron activity before renderer attachment can be absent. PNG comparison is exact: animation, cursor and theme changes may differ without a functional regression.

## Bounds and conclusions {#bounds-and-conclusions}

Limits include 30 steps, 10 seconds per wait, 2,000 HTTP requests, 5,000 TCP observations, 500 console messages, 1,000 state elements and 8 native windows. PNG storage is bounded to 16 MiB per image and 128 MiB per scenario. Missing captures, failed steps, unfinished requests or reached limits make evidence incomplete. A matching report concerns its enabled criteria and recorded scenario only. Use [reconstruction](doc:reconstruction) to apply these comparisons to rebuilt outputs.
