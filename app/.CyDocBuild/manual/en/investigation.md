---
id: investigation
title: Connect a feature to code and evidence
description: Connect a visible feature to source locations, calls and observed evidence.
section: Investigate behavior
order: 11
revision: 2
---

Open [Investigation](doc:investigation) to connect a visible feature with candidate files, functions, resources, routes or calls. A static match is a candidate; an execution observation is separate evidence. The dossier records target hashes and source line/address locations so conclusions can be reviewed.

## JavaScript, Electron and web {#javascript-electron-and-web}

1. Select an application folder, ASAR archive, JS/TS/JSX/TSX file or HTML entry.
2. Install the TypeScript parser if requested and provide Node.js. Start application analysis; this parser does not execute the inspected modules.
3. Search for a visible string, HTML identifier, route, symbol, preload bridge or IPC channel.
4. Inspect related main/preload/renderer modules and local source-map evidence. Compare mappings with the actual file/line and content identity.
5. Import supported HAR observations or configure a runtime scenario to strengthen the investigation.

Source maps can be incomplete, stale or absent. An IPC channel name does not prove which handler ran. Indirect calls, dynamic route registration and computed module paths can remain unresolved. External services, credentials and unavailable backend code cannot be recovered from a frontend bundle alone.

## Native investigation {#native-investigation}

Select an analyzed native project and the function of interest. Supported Ghidra-backed dossiers expose types, instructions and high-pcode/value-use evidence. Match instruction locations to the intended module and preserve address-base information. A matching numeric address in another module is insufficient attribution. See [native analysis](doc:native) for exports, strings and calling conventions.

```diagram
{"type": "flow", "title": "From scenario to conclusion", "nodes": [{"id": "step-0", "label": "1. Choose versions", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Define actions", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Run separately", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Capture evidence", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Compare", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Scope the claim", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Choose versions** — Record identities and prerequisites.
2. **Define actions** — Use the same inputs and checks.
3. **Run separately** — Bound time and process ownership.
4. **Capture evidence** — Outputs, files, screens, network.
5. **Compare** — Inspect differences and missing data.
6. **Scope the claim** — Only observed checks are established.


## Build a defensible conclusion {#build-a-defensible-conclusion}

For each feature, keep the input identity, search term, candidate relationship, location, observed interaction and unknowns. Use [network and graphical observations](doc:observations) for the same scenario on two versions. The report should explain what was seen, how it supports the proposed relationship and what remains unobserved. Timing proximity, matching strings or matching screenshots alone do not prove a complete call chain or full behavior equivalence.
