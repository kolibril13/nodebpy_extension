# SPDX-License-Identifier: GPL-3.0-or-later
"""Export settings + the Export-to-Code operator.

The tuning options live in a :class:`NodebpyExportSettings` PropertyGroup stored
on the Scene, so the panel edits real, persistent properties (rather than the
transient properties of an operator button, which do not reliably hold an edit
across panel redraws). The operator reads its options from that group.

``nodebpy`` is imported lazily inside ``execute`` so the extension still
registers cleanly before the dependency is installed.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty
from bpy.types import Operator, PropertyGroup


def node_tree(context):
    """The node tree currently open in a node-editor space, or ``None``.

    ``edit_tree`` follows the editor into nested groups, so the exported tree
    matches what the user is looking at; it falls back to the top-level
    ``node_tree``. Works for geometry, shader and compositor trees alike.
    """
    space = context.space_data
    if space is None or space.type != "NODE_EDITOR":
        return None
    return getattr(space, "edit_tree", None) or getattr(space, "node_tree", None)


class NodebpyExportSettings(PropertyGroup):
    """Persistent tuning options for the export, stored on the Scene."""

    min_chain_length: IntProperty(
        name="Min Chain Length",
        description="Shortest run of nodes emitted as a >> pipeline",
        default=3,
        min=2,
        soft_max=20,
    )
    snapshot_positions: BoolProperty(
        name="Snapshot Positions",
        description="Capture each node's authored location and restore it on rebuild",
        default=False,
    )
    keep_reroutes: BoolProperty(
        name="Keep Reroutes",
        description="Preserve reroute nodes instead of collapsing them into direct links",
        default=False,
    )
    strict: BoolProperty(
        name="Strict",
        description=(
            "Fail on nodes with no nodebpy equivalent; disable to emit "
            "placeholder comments and keep going"
        ),
        default=True,
    )


class NODEBPY_OT_export_to_code(Operator):
    """Generate nodebpy Python code that recreates the current node tree"""

    bl_idname = "nodebpy_export.to_code"
    bl_label = "Export to Code"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return node_tree(context) is not None

    def execute(self, context):
        tree = node_tree(context)
        if tree is None:
            self.report({"ERROR"}, "No node tree open in the editor")
            return {"CANCELLED"}

        try:
            from nodebpy.export import to_python
        except ImportError:
            self.report(
                {"ERROR"},
                "nodebpy is not installed — use the Install button in the panel",
            )
            return {"CANCELLED"}

        settings = context.scene.nodebpy_export
        try:
            code = to_python(
                tree,
                min_chain_length=settings.min_chain_length,
                snapshot_positions=settings.snapshot_positions,
                keep_reroutes=settings.keep_reroutes,
                strict=settings.strict,
            )
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.report({"ERROR"}, f"Export failed: {exc}")
            return {"CANCELLED"}

        text_name = f"{tree.name}.py"
        text = bpy.data.texts.get(text_name)
        if text is None:
            text = bpy.data.texts.new(text_name)
        text.from_string(code)

        context.window_manager.clipboard = code
        self.report(
            {"INFO"},
            f"Exported '{tree.name}' to text block '{text_name}' and clipboard",
        )
        return {"FINISHED"}
