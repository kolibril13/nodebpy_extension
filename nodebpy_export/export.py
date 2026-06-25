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

import ast
import inspect
import keyword
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup

# A node tree's bl_idname -> the group-node bl_idname that references it, so a
# created tree can be dropped into the open editor as a single group node.
_GROUP_NODE_IDNAME = {
    "GeometryNodeTree": "GeometryNodeGroup",
    "ShaderNodeTree": "ShaderNodeGroup",
    "CompositorNodeTree": "CompositorNodeGroup",
    "TextureNodeTree": "TextureNodeGroup",
}

_GROUP_BASE_FOR_TREE = {
    "GeometryNodeTree": "CustomGeometryGroup",
    "ShaderNodeTree": "CustomShaderGroup",
    "CompositorNodeTree": "CustomCompositorGroup",
}


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


def selected_node_tree(context):
    """The node tree referenced by the active selected group node, or ``None``."""
    tree = node_tree(context)
    if tree is None:
        return None

    active = getattr(tree.nodes, "active", None)
    selected = [node for node in tree.nodes if getattr(node, "select", False)]

    if active in selected:
        candidate = getattr(active, "node_tree", None)
        if isinstance(candidate, bpy.types.NodeTree):
            return candidate

    selected_trees = [
        candidate
        for node in selected
        if isinstance(candidate := getattr(node, "node_tree", None), bpy.types.NodeTree)
    ]
    if len(selected_trees) == 1:
        return selected_trees[0]
    return None


class NodebpyExportSettings(PropertyGroup):
    """Persistent export options and code buffer, stored on the Scene."""

    selected_tree_only: BoolProperty(
        name="Selected Node Tree Only",
        description=(
            "Export the node tree referenced by the active selected group node "
            "instead of the whole open editor tree"
        ),
        default=False,
    )
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
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "nodebpy_export", None) if scene is not None else None
        if settings is not None and settings.selected_tree_only:
            return selected_node_tree(context) is not None
        return node_tree(context) is not None

    def execute(self, context):
        settings = context.scene.nodebpy_export
        tree = selected_node_tree(context) if settings.selected_tree_only else node_tree(context)
        if tree is None:
            if settings.selected_tree_only:
                self.report(
                    {"ERROR"},
                    "Select a group node with a node tree, or disable Selected Node Tree Only",
                )
            else:
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

        try:
            code = _export_code(to_python, tree, settings)
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

    mode: EnumProperty(
        name="Import As",
        description="What to do with the tree the code produces",
        items=(
            (
                "TREE",
                "Tree",
                "Open the created tree in the editor (and optionally add it as "
                "a Geometry Nodes modifier)",
            ),
            (
                "GROUP",
                "Node Group",
                "Drop the created tree into the open editor as a single group "
                "node attached to the mouse cursor",
            ),
        ),
        default="TREE",
        options={"SKIP_SAVE"},
    )

    # Window-space mouse position captured at invoke, so GROUP mode can drop the
    # group node under the cursor regardless of which region the click came from.
    _mouse: tuple[int, int] | None = None

    @classmethod
    def poll(cls, context):
        settings = getattr(context.scene, "nodebpy_export", None)
        return settings is not None and bool(settings.code.strip())

    def invoke(self, context, event):
        self._mouse = (event.mouse_x, event.mouse_y)
        return self.execute(context)

    def execute(self, context):
        code = context.scene.nodebpy_export.code
        before = {group.name for group in bpy.data.node_groups}
        namespace: dict = {"__name__": "__nodebpy_panel__"}
        try:
            exec(compile(code, "<nodebpy panel>", "exec"), namespace)  # noqa: S102
        except Exception as exc:  # noqa: BLE001 - surface any failure in the UI
            self.report({"ERROR"}, f"Run failed: {exc}")
            return {"CANCELLED"}

        try:
            tree = _created_tree(namespace, before)
        except Exception as exc:  # noqa: BLE001 - group class creation can fail
            self.report({"ERROR"}, f"Run failed: {exc}")
            return {"CANCELLED"}
        if tree is None:
            self.report({"INFO"}, "Ran code from the panel")
            return {"FINISHED"}

        if self.mode == "GROUP":
            return self._import_as_group(context, tree)
        return self._import_as_tree(context, tree)

    def _import_as_tree(self, context, tree):
        # The user is declaring this top-level tree a standalone modifier tree,
        # so flag it accordingly — otherwise a geometry group built from Python
        # never appears in the modifier's node-group selector. Nested subgroups
        # are left untouched (see _created_tree, which returns only the root).
        if tree.bl_idname == "GeometryNodeTree":
            tree.is_modifier = True

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

    def _import_as_group(self, context, tree):
        """Drop ``tree`` into the open editor as a group node grabbed by the mouse.

        Mirrors how the Add menu inserts a node: place it at the cursor, then
        hand it to ``node.translate_attach_remove_on_cancel`` so it follows the
        mouse until the user clicks to drop it (or right-click/Esc to cancel,
        which removes it).
        """
        area = context.area
        space = context.space_data
        if space is None or space.type != "NODE_EDITOR" or area is None:
            self.report({"ERROR"}, "Run with the cursor in a Node Editor to drop a group")
            return {"CANCELLED"}

        target = getattr(space, "edit_tree", None)
        group_idname = _GROUP_NODE_IDNAME.get(tree.bl_idname)
        if target is None or group_idname is None or target.bl_idname != tree.bl_idname:
            self.report(
                {"ERROR"},
                f"Open a {tree.bl_idname} in the editor to drop this group",
            )
            return {"CANCELLED"}
        if target == tree:
            self.report({"ERROR"}, "Can't drop a group inside itself")
            return {"CANCELLED"}

        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        group = target.nodes.new(group_idname)
        group.node_tree = tree
        try:
            group.show_options = False
        except (AttributeError, TypeError):
            pass

        if region is not None and self._mouse is not None:
            # event.mouse_x/y are window-absolute; subtract the region origin to
            # get region-local coords, then map to view space and undo the UI
            # scale (node space = view space / ui_scale).
            view = region.view2d.region_to_view(
                self._mouse[0] - region.x, self._mouse[1] - region.y
            )
            ui_scale = context.preferences.system.ui_scale
            group.location = (view[0] / ui_scale, view[1] / ui_scale)

        for node in target.nodes:
            node.select = False
        group.select = True
        target.nodes.active = group

        if region is not None:
            with context.temp_override(area=area, region=region):
                try:
                    bpy.ops.node.translate_attach_remove_on_cancel("INVOKE_DEFAULT")
                except RuntimeError:
                    pass  # already placed at the cursor; just not grab-attached

        self.report({"INFO"}, f"Dropped '{tree.name}' as a node group")
        return {"FINISHED"}


def _export_code(to_python, tree, settings) -> str:
    kwargs = {
        "min_chain_length": settings.min_chain_length,
        "snapshot_positions": settings.snapshot_positions,
        "keep_reroutes": settings.keep_reroutes,
        "strict": settings.strict,
    }
    if not settings.selected_tree_only:
        return to_python(tree, **kwargs)

    try:
        params = inspect.signature(to_python).parameters
    except (TypeError, ValueError):
        params = {}
    if "top_level" in params:
        return to_python(tree, **kwargs, top_level="class")

    code = to_python(tree, **kwargs)
    return _tree_builder_code_to_group_class(code, tree)


def _tree_builder_code_to_group_class(code: str, tree) -> str:
    """Fallback for older nodebpy versions without ``top_level="class"``."""
    base = _GROUP_BASE_FOR_TREE.get(tree.bl_idname)
    if base is None:
        return code

    module = ast.parse(code)
    with_node = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.With) and _binds_tree_var(node)
        ),
        None,
    )
    if with_node is None or with_node.end_lineno is None:
        raise ValueError("Selected tree export needs a top-level TreeBuilder block")

    lines = code.splitlines()
    prefix = lines[: with_node.lineno - 1]
    body = lines[with_node.lineno : with_node.end_lineno]
    suffix = lines[with_node.end_lineno :]

    snapshot, suffix = _take_snapshot_block(suffix)
    class_lines = _group_class_lines(tree, base, body, snapshot)
    result = _ensure_group_base_import(prefix + class_lines + suffix, base)
    return "\n".join(result)


def _binds_tree_var(node: ast.With) -> bool:
    return any(
        isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == "tree"
        for item in node.items
    )


def _take_snapshot_block(lines: list[str]) -> tuple[list[str], list[str]]:
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines) and lines[index].startswith("# Restore authored"):
        return lines[index:], lines[: index]
    return [], lines


def _group_class_lines(
    tree, base: str, body_lines: list[str], snapshot_lines: list[str]
) -> list[str]:
    header = [
        f"class {_class_name(tree.name)}({base}):",
        f"    _name = {tree.name!r}",
    ]
    color = getattr(tree, "color_tag", "NONE")
    if color and color != "NONE":
        header.append(f"    _color_tag = {color!r}")
    header.extend(["", "    def _build_group(self, tree):"])

    body = [("    " + line) if line else "" for line in body_lines]
    if not body:
        body = ["        pass"]
    if snapshot_lines:
        body.extend(
            [""] + [("        " + line) if line else "" for line in snapshot_lines]
        )
    return ["", ""] + header + body


def _ensure_group_base_import(lines: list[str], base: str) -> list[str]:
    import_line = f"from nodebpy.builder import {base}"
    if any(
        line.startswith("from nodebpy.builder import") and base in line
        for line in lines
    ):
        return lines

    insert_at = 0
    while insert_at < len(lines) and (
        lines[insert_at].startswith("import ")
        or lines[insert_at].startswith("from ")
    ):
        insert_at += 1
    return lines[:insert_at] + [import_line] + lines[insert_at:]


def _class_name(name: str) -> str:
    cleaned = "".join(p[:1].upper() + p[1:] for p in re.split(r"\W+", name) if p)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"Group{cleaned}"
    if keyword.iskeyword(cleaned):
        cleaned += "_"
    return cleaned


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
    if isinstance(builder, bpy.types.NodeTree):
        return builder

    new_groups = [g for g in bpy.data.node_groups if g.name not in before]
    if not new_groups:
        return _created_group_class_tree(namespace)
    nested = {
        sub.name
        for g in new_groups
        for n in g.nodes
        if (sub := getattr(n, "node_tree", None)) is not None
    }
    top_level = [g for g in new_groups if g.name not in nested]
    return (top_level or new_groups)[-1]


def _created_group_class_tree(namespace: dict):
    module_name = namespace.get("__name__")
    for value in reversed(list(namespace.values())):
        if not isinstance(value, type):
            continue
        if getattr(value, "__module__", None) != module_name:
            continue
        if not callable(getattr(value, "create_group", None)):
            continue
        if not getattr(value, "_tree_idname", None) or not getattr(value, "_name", None):
            continue
        tree = value.create_group()
        if isinstance(tree, bpy.types.NodeTree):
            return tree
    return None


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
