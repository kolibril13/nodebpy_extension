# nodebpy_extension

A standalone Blender extension that adds an **Export to Code** button to the
node editor's sidebar (the **N** panel). It turns any node tree — geometry,
shader or compositor — back into readable [`nodebpy`](https://github.com/BradyAJohnston/nodebpy)
Python code, using `nodebpy.export.to_python`.

See the underlying feature: <https://kolibril13.github.io/nodebpy/nodes-to-code.html>.

## Install

1. Download / build `nodebpy_export` as an extension (see *Building* below) and
   install it via **Edit → Preferences → Get Extensions → Install from Disk**,
   or drop the `nodebpy_export/` folder into your Blender extensions directory.
2. Open a Node Editor, press **N**, and switch to the **nodebpy** tab.
3. First run only: click the red **Install nodebpy** button. It pip-installs
   `nodebpy` (plus `networkx` and `ruff` for faster, formatted output) into the
   extension's site-packages — `bpy` is *not* installed, since Blender already
   provides it.

## Use

With a node tree open in the editor, click **Export to Code**. The generated
source is written to a Text datablock named `<tree>.py` (visible in Blender's
Text Editor) and copied to the clipboard.

Options exposed on the button:

- **Min Chain Length** — shortest run of nodes emitted as a `>>` pipeline.
- **Snapshot Positions** — capture and restore each node's authored location.
- **Keep Reroutes** — preserve reroute nodes instead of collapsing them.
- **Strict** — fail on unsupported nodes (off → emit placeholder comments).

## Layout

```
nodebpy_export/
  blender_manifest.toml   extension manifest (permissions = ["files"])
  __init__.py             N-panel + register/unregister
  export.py               the Export-to-Code operator (lazy-imports nodebpy)
  preferences.py          install/uninstall operators + the red install button
  addon_setup.py          background pip/uv installer (uv preferred, pip fallback)
```

## Building

From a checkout, with a recent Blender on your PATH:

```bash
blender --command extension build --source-dir nodebpy_export
```

This produces a `nodebpy_export-0.1.0.zip` ready to install or upload.

## Requirements

- Blender 5.2+ (its bundled Python satisfies `nodebpy`'s `requires-python`).
