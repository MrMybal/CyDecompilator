---
id: help-api
title: Native help-link API
description: Open a validated local chapter, section or annotated image from Python.
section: Reference / Integration
order: 91
kind: api
revision: 2
---

The application uses the Python `documentation` module to resolve local help links.
It reads the packaged route catalogue, accepts supported legacy chapter names and
refuses unknown destinations. Import it from an installed application's module path.

## Open a chapter {#open-a-chapter}

```python
from documentation import Documentation

help = Documentation()
help.open('projects', 'fr', anchor='edit-and-build')
```

`Documentation(root=None, opener=None)` uses the `Documentation` directory beside
`documentation.py` by default. An explicit `root` selects another complete installed
export. The optional `opener` has the `webbrowser.open(url, new=0)` contract; returning
false reports a browser-launch error.

## Public methods {#public-methods}

- [`Documentation.url`](doc:help-route-api) returns an encoded local URL without opening it.
- [`Documentation.open`](doc:open-help-api) validates the same destination and opens it.

Both methods accept the same page, language, section and media-view fields. English
is the default. French variants such as `fr-CA` select French; other interface languages
select English. Stable page and annotation identifiers are common to both editions.

## An annotated image {#an-annotated-image}

```python
url = help.url('start', 'en', media='workspace-screenshot',
               note='function-list', zoom=1.25)
```

The image is already distributed with the manual. A link does not import a new media
file or execute inspected application code. Browser policies can affect persistent
reading preferences for local files.
