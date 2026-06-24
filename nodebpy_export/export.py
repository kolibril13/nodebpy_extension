# SPDX-License-Identifier: GPL-3.0-or-later
"""Export settings + the Export-to-Code / Run-Code operators.

The tuning options and the code buffer live in a :class:`NodebpyExportSettings`
PropertyGroup stored on the Scene, so the panel edits real, persistent
properties. The generated code is shown in a Blender 5.2 ``layout.textbox``
right in the panel; you can edit it or paste your own and run it with the
**Run Code** button — no trip to the Scripting workspace needed.

``nodebpy`` is imported lazily inside the operators so the extension still
registers cleanly before the dependency is installed.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
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
    """Persistent export options and code buffer, stored on the Scene."""

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
    apply_to_object: BoolProperty(
        name="Apply to Active Object",
        description=(
            "After running, add the new geometry node tree as a Geometry Nodes "
            "modifier on the active object"
        ),
        default=False,
    )
    code: StringProperty(
        name="Code",
        description="Exported nodebpy code — edit it, or paste your own and run it",
        default="",
    )


class NODEBPY_OT_export_to_code(Operator):
    """Generate nodebpy code for the current node tree into the panel's text box"""

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

        settings.code = code
        context.window_manager.clipboard = code
        self.report(
            {"INFO"},
            f"Exported '{tree.name}' ({len(code.splitlines())} lines) to the panel and clipboard",
        )
        return {"FINISHED"}


class NODEBPY_OT_run_code(Operator):
    """Run the nodebpy code from the panel's text box (rebuilds the node tree)"""

    bl_idname = "nodebpy_export.run_code"
    bl_label = "Run Code"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "nodebpy_export", None)
        return settings is not None and bool(settings.code.strip())

    def execute(self, context):
        code = context.scene.nodebpy_export.code
        before = {group.name for group in bpy.data.node_groups}
        namespace: dict = {"__name__": "__nodebpy_panel__"}
        try:
            exec(compile(code, "<nodebpy panel>", "exec"), namespace)  # noqa: S102
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.report({"ERROR"}, f"Run failed: {exc}")
            return {"CANCELLED"}

        tree = _created_tree(namespace, before)
        if tree is None:
            self.report({"INFO"}, "Ran code from the panel")
            return {"FINISHED"}

        settings = context.scene.nodebpy_export
        # When applying to an object, leave the editor unpinned so it follows
        # that object's (now active) modifier; otherwise pin to the tree so a
        # standalone group stays visible.
        applied_obj = (
            _apply_to_object(context, tree) if settings.apply_to_object else None
        )
        opened = _open_in_editor(context, tree, pin=applied_obj is None)

        parts = [f"{'opened' if opened else 'created'} '{tree.name}'"]
        if settings.apply_to_object:
            if applied_obj is not None:
                parts.append(f"applied to '{applied_obj.name}'")
            else:
                self.report(
                    {"WARNING"},
                    "Couldn't apply — needs a geometry tree and a compatible active object",
                )
        self.report({"INFO"}, "Ran code — " + ", ".join(parts))
        return {"FINISHED"}


def _created_tree(namespace: dict, before: set[str]):
    """The node tree a Run produced, or ``None``.

    Prefers the builder bound by nodebpy's ``with TreeBuilder(...) as tree:``
    form; otherwise falls back to the newest node group created by the run that
    is not nested inside another new group (i.e. the top-level tree).
    """
    builder = namespace.get("tree")
    candidate = getattr(builder, "tree", None)
    if isinstance(candidate, bpy.types.NodeTree):
        return candidate

    new_groups = [g for g in bpy.data.node_groups if g.name not in before]
    if not new_groups:
        return None
    nested = {
        sub.name
        for g in new_groups
        for n in g.nodes
        if (sub := getattr(n, "node_tree", None)) is not None
    }
    top_level = [g for g in new_groups if g.name not in nested]
    return (top_level or new_groups)[-1]


def _apply_to_object(context, tree):
    """Add ``tree`` as a Geometry Nodes modifier on the active object.

    Returns the object on success, or ``None`` when the tree isn't a geometry
    tree, there is no active object, or the object can't take a modifier.
    """
    if tree is None or tree.bl_idname != "GeometryNodeTree":
        return None
    obj = context.active_object
    if obj is None:
        return None
    try:
        modifier = obj.modifiers.new(name=tree.name, type="NODES")
    except (RuntimeError, TypeError):
        return None  # object type doesn't support modifiers (camera, empty, …)
    modifier.node_group = tree
    # Make it the active modifier so an unpinned geometry node editor shows it.
    try:
        obj.modifiers.active = modifier
    except (AttributeError, TypeError):
        pass
    return obj


def _open_in_editor(context, tree, *, pin: bool) -> bool:
    """Show ``tree`` in the current node editor, replacing whatever is open.

    Switches the editor to the matching tree type so it works even when nothing
    was open. When ``pin`` is True the editor is pinned to ``tree`` so a
    standalone group stays visible; when False it is unpinned so a Geometry
    Nodes editor follows the active object's active modifier instead.
    """
    if tree is None:
        return False
    space = context.space_data
    if space is None or space.type != "NODE_EDITOR":
        return False
    try:
        space.tree_type = tree.bl_idname
        space.pin = pin
        if pin:
            space.node_tree = tree
    except (AttributeError, TypeError):
        return False
    return True
