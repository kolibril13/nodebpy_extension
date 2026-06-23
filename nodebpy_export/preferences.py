# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependency operators, addon preferences and the shared dependency view.

The operators are thin wrappers around ``addon_setup.installer``; the
``draw_dependencies`` helper renders the install / uninstall / list controls
plus a collapsible log box, and is shared between the N-panel and the addon
preferences. The Install button turns red (``alert``) while ``nodebpy`` is
missing.
"""

from __future__ import annotations

import bpy

from . import addon_setup

# Lines streamed back from the installer subprocess for the log box.
# Carriage-return prefixed lines overwrite the previous entry — the same trick
# pip's progress bar relies on.
_LINES: list[str] = []


def _lines_append(line: str) -> None:
    if line.startswith("\r") and len(_LINES) > 0:
        del _LINES[-1]
        line = line[1:]
    _LINES.append(line)


# ============================================================ #
# Operators                                                    #
# ============================================================ #
class NODEBPY_OT_install_modules(bpy.types.Operator):
    """Install nodebpy and its helpers into Blender's site-packages"""

    bl_idname = "nodebpy_export.install_modules"
    bl_label = "Install nodebpy"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return not addon_setup.installer.is_running

    def execute(self, context: bpy.types.Context) -> set[str]:
        _LINES.clear()
        region = context.region
        addon_setup.installer.install_python_modules(
            line_callback=lambda line: _lines_append(line) or region.tag_redraw(),
            finally_callback=lambda e: region.tag_redraw(),
        )
        return {"FINISHED"}


class NODEBPY_OT_uninstall_modules(bpy.types.Operator):
    """Uninstall the Python dependencies installed by this addon"""

    bl_idname = "nodebpy_export.uninstall_modules"
    bl_label = "Uninstall"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return not addon_setup.installer.is_running

    def execute(self, context: bpy.types.Context) -> set[str]:
        _LINES.clear()
        region = context.region
        addon_setup.installer.uninstall_python_modules(
            line_callback=lambda line: _lines_append(line) or region.tag_redraw(),
            finally_callback=lambda e: region.tag_redraw(),
        )
        return {"FINISHED"}


class NODEBPY_OT_list_modules(bpy.types.Operator):
    """List all Python modules currently visible to Blender's interpreter"""

    bl_idname = "nodebpy_export.list_modules"
    bl_label = "List Modules"
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return not addon_setup.installer.is_running

    def execute(self, context: bpy.types.Context) -> set[str]:
        _LINES.clear()
        region = context.region
        addon_setup.installer.list_python_modules(
            line_callback=lambda line: _lines_append(line) or region.tag_redraw(),
            finally_callback=lambda e: region.tag_redraw(),
        )
        return {"FINISHED"}


# ============================================================ #
# Draw                                                         #
# ============================================================ #
def draw_dependencies(
    layout: bpy.types.UILayout, prefs: "NodebpyExportPreferences"
) -> None:
    modules = addon_setup.installer.get_required_modules()
    all_installed = all(modules.values())

    header, body = layout.panel(
        "nodebpy_export_dependencies", default_closed=all_installed
    )
    header.label(
        text="Dependencies",
        icon="CHECKMARK" if all_installed else "ERROR",
    )
    if body is None:
        return

    install_row = body.row()
    install_row.scale_y = 1.4
    install_row.alert = not all_installed  # the "cool red button" when missing
    install_row.operator(
        NODEBPY_OT_install_modules.bl_idname,
        icon="IMPORT",
        text="Install nodebpy" if not all_installed else "Reinstall nodebpy",
    )

    body.label(text="Required Python Modules:")
    flow = body.row(align=True).grid_flow(align=True)
    for name, is_installed in modules.items():
        flow.row().label(text=name, icon="CHECKMARK" if is_installed else "ERROR")

    row = body.row()
    row.operator(NODEBPY_OT_uninstall_modules.bl_idname, text="Uninstall")
    row.operator(NODEBPY_OT_list_modules.bl_idname, text="List Modules")

    # Logs (collapsible)
    col = body.column(align=False)
    log_row = col.row(align=True)
    log_row.prop(
        prefs,
        "show_logs",
        icon="TRIA_DOWN" if prefs.show_logs else "TRIA_RIGHT",
        icon_only=True,
        emboss=False,
    )
    log_row.label(text="Logs")
    exit_code = addon_setup.installer.exit_code
    if addon_setup.installer.is_running:
        log_row.label(text="Processing ...", icon="SORTTIME")
    elif exit_code >= 0:
        log_row.label(
            text=f"Done with code: {exit_code}",
            icon="CHECKMARK" if exit_code == 0 else "ERROR",
        )

    if prefs.show_logs:
        box = col.box().column(align=True)
        for line in _LINES:
            box.label(text=line)


# ============================================================ #
# Preferences                                                  #
# ============================================================ #
class NodebpyExportPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    show_logs: bpy.props.BoolProperty(default=False)

    def draw(self, context: bpy.types.Context) -> None:
        draw_dependencies(self.layout, self)
        self.layout.label(
            text="Export button: Node Editor > Sidebar (N) > nodebpy",
            icon="INFO",
        )
