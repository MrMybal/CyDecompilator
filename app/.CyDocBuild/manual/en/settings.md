---
id: settings
title: Preferences, updates and licenses
description: Adjust appearance, languages, providers, application updates and license notices.
section: Settings and reference
order: 18
revision: 2
---

Open [Options](doc:settings) to change interface settings. Language, theme, density and text size are local application preferences. Changing them does not modify analysis results or project source files.

## Language and appearance {#language-and-appearance}

The interface starts in English and offers English, French, German, Spanish, Italian, Portuguese, Russian, Simplified Chinese, Japanese and Korean. Select a language to apply it without restarting. The bundled manual is fully available in English and French; its language selector can override the interface choice. Other interface languages fall back to the English manual.

Themes include Mid grey, Light grey, Amber night, Violet and Navy. Density and text scaling alter layout; narrower windows move some panels into tabs. Resetting interface preferences does not remove models, source files, provider settings or analysis data. In the documentation's enlarged-image view, use wheel zoom, drag to pan and double-click fit.

## Configuration and updates {#configuration-and-updates}

Generation configurations save supported operation parameters, not private credential secrets. Review the chosen configuration before applying it to a different project. Installation storage settings distinguish the local installation from optional shared caches.

Application updates, engine updates and AI-provider/model settings are separate. Application updating stages and verifies an archive, checks runtime compatibility and retains rollback material. Keep **data/** and **runtime/** when updating application code. A release ZIP may require an existing compatible private runtime; inspect its release notes. Do not overwrite an installation with a mismatched Python/runtime bundle.

## License notices {#license-notices}

The Options license section lists the application and declared engines/dependencies with their original notices where available. CyUI's MIT notice is bundled locally even when its source repository is private. A link requiring repository access does not prevent reading the included notice. Translated interface labels are not translations of the legal texts, and a dependency's license does not replace the application's own license.

For missing libraries, incompatible updates or settings issues, see [installation](doc:installation), [storage](doc:storage) and [troubleshooting](doc:troubleshooting).
