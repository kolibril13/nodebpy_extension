# SPDX-License-Identifier: GPL-3.0-or-later
"""Nodes to Code — Blender extension entry point.

Adds a *nodebpy* tab to the node editor's sidebar (the **N** panel) with an
**Export to Code** button, available for geometry, shader and compositor node
trees. The button calls ``nodebpy.export.to_python`` on the open tree and shows
the result in an editable text box; **Run Code** executes whatever is in the box
so you can rebuild trees without leaving the Node Editor. The ``nodebpy``
dependency is installed on demand from the same panel.
"""

from __future__ import annotations

import bpy
from bpy.props import PointerProperty

from . import addon_setup
from .export import (
    NODEBPY_OT_export_to_code,
    NODEBPY_OT_run_code,
    NodebpyExportSettings,
)
from .preferences import (
    NODEBPY_OT_install_modules,
    NODEBPY_OT_list_modules,
    NODEBPY_OT_uninstall_modules,
    NodebpyExportPreferences,
    draw_dependencies,
)


class NODEBPY_PT_export(bpy.types.Panel):
    """Sidebar panel hosting the export/run controls and dependency install."""

    bl_label = "Nodes to Code"
    bl_idname = "NODEBPY_PT_export"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "nodebpy"

    # No poll: bl_space_type already limits this to node editors, and we want
    # the panel available even when no node tree is open yet, so code can be
    # pasted and run to create one.

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences

        if addon_setup.installer.is_ready():
            settings = context.scene.nodebpy_export

            layout.operator(
                NODEBPY_OT_export_to_code.bl_idname,
                text="Export to Code",
                icon="CONSOLE",
            )
            col = layout.column(align=True)
            col.prop(settings, "min_chain_length")
            col.prop(settings, "snapshot_positions")
            col.prop(settings, "keep_reroutes")
            col.prop(settings, "strict")

            layout.separator()
            layout.label(text="Code")
            layout.textbox(
                settings,
                "code",
                placeholder="Export a tree above, or paste nodebpy code here…",
            )
            if context.active_object is not None:
                layout.prop(settings, "apply_to_object")
            row = layout.row(align=True)
            row.operator(
                NODEBPY_OT_run_code.bl_idname,
                text="Run → Tree",
                icon="PLAY",
            ).mode = "TREE"
            row.operator(
                NODEBPY_OT_run_code.bl_idname,
                text="Run → Node Group",
                icon="NODETREE",
            ).mode = "GROUP"
        else:
            box = layout.box()
            box.label(text="nodebpy is not installed yet.", icon="ERROR")
            box.label(text="Install it to enable export ↓")

        draw_dependencies(layout, prefs)


_CLASSES = (
    NodebpyExportSettings,
    NodebpyExportPreferences,
    NODEBPY_OT_export_to_code,
    NODEBPY_OT_run_code,
    NODEBPY_OT_install_modules,
    NODEBPY_OT_uninstall_modules,
    NODEBPY_OT_list_modules,
    NODEBPY_PT_export,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.nodebpy_export = PointerProperty(type=NodebpyExportSettings)


def unregister() -> None:
    if hasattr(bpy.types.Scene, "nodebpy_export"):
        del bpy.types.Scene.nodebpy_export
    for cls in reversed(_CLASSES):
        if hasattr(cls, "bl_rna"):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass
