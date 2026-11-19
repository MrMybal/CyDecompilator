# Unreal integration reference

CyDecompilator is a standalone Python/CyUI application, not an Unreal plugin.
Its current native bridge and business registry are described in [CyMCPSDK.md](CyMCPSDK.md).
The optional reconstruction workflows generate Unreal project artifacts; they do
not install an assistant or an SDK inside the generated project automatically.

For a separate Unreal plugin integration, consult the current
[CyUEMCPSDK](https://github.com/MrMybal/CyUEMCPSDK) source guides. Its module,
thread, editor and packaging requirements must be verified against the actual
plugin and engine version. This application does not ship the old Python Core
companion or its wheel. Existing project assets remain persistent project changes.
