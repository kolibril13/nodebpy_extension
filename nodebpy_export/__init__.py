# SPDX-License-Identifier: GPL-3.0-or-later
"""Nodes to Code — Blender extension entry point.

Adds a *nodebpy* tab to the node editor's sidebar (the **N** panel) with an
**Export to Code** button, available for geometry, shader and compositor node
trees. The button calls ``nodebpy.export.to_python`` on the open tree; the
``nodebpy`` dependency is installed on demand from the same panel.
"""

from __future__ import annotations

import bpy

from . import addon_setup
from .export import NODEBPY_OT_export_to_code, node_tree
from .preferences import (
    NODEBPY_OT_install_modules,
    NODEBPY_OT_list_modules,
    NODEBPY_OT_uninstall_modules,
    NodebpyExportPreferences,
    draw_dependencies,
)


class NODEBPY_PT_export(bpy.types.Panel):
    """Sidebar panel hosting the export button and dependency controls."""

    bl_label = "Nodes to Code"
    bl_idname = "NODEBPY_PT_export"
    bl_space_type = "NODE_EDITOR"
    bl_region_type = "UI"
    bl_category = "nodebpy"

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return node_tree(context) is not None

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        prefs = context.preferences.addons[__package__].preferences

        if addon_setup.installer.is_ready():
            op = layout.operator(
                NODEBPY_OT_export_to_code.bl_idname,
                text="Export to Code",
                icon="CONSOLE",
            )
            col = layout.column(align=True)
            col.prop(op, "min_chain_length")
            col.prop(op, "snapshot_positions")
            col.prop(op, "keep_reroutes")
            col.prop(op, "strict")
        else:
            box = layout.box()
            box.label(text="nodebpy is not installed yet.", icon="ERROR")
            box.label(text="Install it to enable export ↓")

        draw_dependencies(layout, prefs)


_CLASSES = (
    NodebpyExportPreferences,
    NODEBPY_OT_export_to_code,
    NODEBPY_OT_install_modules,
    NODEBPY_OT_uninstall_modules,
    NODEBPY_OT_list_modules,
    NODEBPY_PT_export,
)


def register() -> None:
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_CLASSES):
        if hasattr(cls, "bl_rna"):
            try:
                bpy.utils.unregister_class(cls)
            except RuntimeError:
                pass
