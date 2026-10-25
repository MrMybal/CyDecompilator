# Unreal reconstruction — integrated rules

Open **Unreal reconstruction** in CyDecompilator. Select the general methodology or **Halo CEA Xbox 360 / UE 5.8**, filter by category, and use **Copy reconstruction guide** to copy the displayed rules and reference hashes.

The portable `app/unreal_support/reconstruction-rules.json` catalog contains 26 rules (24 general methodology rules and two specific to Halo identity/vertex format), 11 categories and ten campaign profiles with source executable identities and model mappings. Topics include geometry/UVs, materials, animation, navigation, weapons, AI, vehicles, effects/audio, campaign and validation.

`unreal_rules` returns structured rules and profiles. `unreal_guide` adds a Markdown representation of the same data. Both accept `profile` (`generic` or `halo-cea-x360`), optional `category` from the returned category list, and `language` (`en` or `fr`). They use the shared Runtime in the native page, CLI and MCP, require no open project or elevated operation permission, and perform no process launch, network access, extraction or game import. The integrated agent can discover them; reading rules never counts as a successful reconstruction.

The catalog is self-contained even without the research module, game files or Unreal Engine. `modules/unreal-reconstruction` remains the separate implementation for extraction/import/build/execution. No assets or compiled game binaries are bundled with this knowledge integration. Existing maps and saves are preserved. Rules describe required checks and do not enforce them automatically.

Reference SHA-256 values identify the snapshots used to write the rules; they are not current build or gameplay certification. Halo support is title/edition/executable-specific. Full retail AI, original rigid-body physics and all Saber shader/effect controllers remain uncertified.

See the [French guide](UnrealReconstruction.fr.md) for a CLI example. Focused tests are in `tests/test_unreal.py`; integration receipts and EN/FR captures are saved in `data/reports/unreal-integration`.
