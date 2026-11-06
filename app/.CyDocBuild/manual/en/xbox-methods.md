---
id: xbox-methods
title: Xbox rendering, input and timing
description: Diagnose a native project's controls, rendering, cadence and compatibility.
section: Console workflows
parent: xbox
order: 17
revision: 2
---

Use this guide after preparing or attaching a [native Xbox project](doc:xbox).
Choose the exact executable and build receipt before changing a profile. A matching
filename is insufficient: executable and GPU-plugin identities are checked by hash.

## Start the recorded build {#start-the-recorded-build}

1. In **Xbox native tools**, select the separate SDK and, if needed, an existing native
   GPU plugin. A plugin is optional; its capabilities depend on that particular build.
2. Create or attach the native project. Rebuild after changing sources or the plugin.
3. Choose **Fullscreen at launch** if appropriate, then **Launch native Xbox game**.
   Saved game settings can override the requested display mode.
4. Read the running task's output. Cancel that task to stop its game processes.

Attaching reuses the selected native project; it does not import its assets into a
second copy. Keep its original folder and SDK available.

## Cadence and animation {#cadence-and-animation}

Presentation rate, simulation ticks and animation interpolation are different concerns.
Unlocking presentation does not automatically update physics, AI or scripts more often.
When replacing a subsystem, compare a representative scene and player actions; check
arms, enemies, vehicles and cameras separately. A displayed frame counter does not
establish correct simulation speed or full-game compatibility.

## Keyboard, mouse and local players {#keyboard-mouse-and-local-players}

Check keyboard focus, pause and menu input before testing gameplay. Mouse movement
should be consumed once, and stale movement cleared after focus loss or pause. Native
menu interaction and gameplay input can use different guest paths.

The **Local campaign coop (Halo profile)** option reserves keyboard/mouse for player 1
and the first controller for player 2 on the supported profile. This is an experimental,
game-specific path. It does not add general split-screen support or a separately saved
second campaign to every Xbox game.

## Rendering and network limits {#rendering-and-network-limits}

A black image can involve resolves, HDR exposure or occlusion-query handling; changing
the rendering mode alone may not solve it. Compare the intended visible scene rather
than assuming that a successful GPU initialization means correct rendering. Occlusion
fallbacks can introduce artifacts, such as lights visible through walls.

The optional ray-tracing work does not reconstruct a complete material/light renderer
or provide a finished temporal denoiser. Its capture assumptions also limit use with
multiple views. Direct-IP transport does not by itself create synchronized campaign
sessions. Xbox Live is not supplied and competitive multiplayer is outside this workflow.

For operation parameters, see [`xbox_tools`](doc:op-xbox-tools),
[`xbox_build`](doc:op-xbox-build) and [`xbox_run`](doc:op-xbox-run).
