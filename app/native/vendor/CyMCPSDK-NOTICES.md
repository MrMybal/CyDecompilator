# Third-party components

CyMCPSDK source is MIT. These small, vendored components are MIT as well:

| Component | Version | SHA-256 of header | Notice |
|---|---|---|---|
| nlohmann/json | 3.12.0 | aaf127c04cb31c406e5b04a63f1ae89369fccde6d8fa7cdda1ed4f32dfc5de63 | third_party/nlohmann/LICENSE.MIT |
| cpp-httplib | 0.66.0 | 51ddd1482c67acb31f3064e48329aade14acc7dd0fab31ee5397193697ea1c35 | third_party/httplib/LICENSE |
| PicoSHA2 | 161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29 | b13c180161ffac8d0adc81e033e493c409457c4d1258ab9781ac80579ba3bdd8 | third_party/picosha2/LICENSE |

Upstreams: https://github.com/nlohmann/json, https://github.com/yhirose/cpp-httplib,
https://github.com/okdshin/PicoSHA2.

Windows networking and cryptography use system APIs. Linux/macOS HTTPS uses the
host's libcurl, under its own permissive curl license and TLS backend notices.
No Python runtime, model weights, inference engine, GPU runtime or driver
is shipped in the SDK. The optional ChatUI module uses the host's CyUI (MIT),
Dear ImGui (MIT), MD4C (MIT), Lexilla/Scintilla's permissive lexer libraries and
CyUI's embedded JetBrains Mono font (SIL OFL 1.1). The Windows example statically
links the selected CyUI modules, including DocumentIO with miniz inflate (MIT).
Its distribution includes their upstream notices.
CyUI source is supplied by the host and is not vendored into this repository.
The base SDK does not acquire any GUI dependency.
External providers, engines and downloaded packages retain
their own terms; their licenses are not changed by this project.

The optional static manual uses CyDoc 0.1.0 (MIT). Its reader, styles and image
module are distributed under Documentation/DocData, with CyDoc-MIT.txt.
The documentation toolchain uses marked 17.0.6, PrismJS 1.30.0 and esbuild 0.25.12
(MIT); their notices are in Documentation/DocData/notices. These generation tools
and Node.js do not run inside the native SDK or the exported reader.
