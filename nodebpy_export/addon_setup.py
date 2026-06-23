# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependency installer for the Nodes-to-Code extension.

A single ``installer`` singleton wraps ``pip`` (preferring ``uv`` when one is
available) to manage the ``nodebpy`` dependency set inside the extension's
site-packages — the same location already on Blender's ``sys.path``. The
machinery is ported from jupyter-blender's ``Installer``, trimmed to the
install / uninstall / list operations this extension needs.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import pkgutil
import shutil
import subprocess
import sys
import threading
import traceback
from typing import Any, Callable, Optional


def _invoke_callback(callback: Optional[Callable], *args: Any) -> None:
    if callback is None:
        return
    try:
        callback(*args)
    except Exception as exc:  # noqa: BLE001
        logging.exception("Callback failed:", exc_info=exc)


class Executor:
    """Run a function or a subprocess in a daemon thread, with a line-by-line
    stdout callback and a finally callback."""

    def __init__(self) -> None:
        self._is_running = False
        self._return_value: Any = None
        self._exception: Optional[Exception] = None
        self._process: Optional[subprocess.Popen] = None
        self._exit_code = -1
        self._command_line = ""

    def exec_function(
        self,
        function: Callable[..., Any],
        *args: Any,
        line_callback: Optional[Callable[[str], None]] = None,
        finally_callback: Optional[Callable[["Executor"], Any]] = None,
    ) -> None:
        def _run_background() -> None:
            try:
                self._return_value = function(*args)
            except Exception as exception:  # noqa: BLE001
                self._exception = exception
                self.write_exception(exception, line_callback=line_callback)
            finally:
                self._is_running = False
                _invoke_callback(finally_callback, self)

        self._is_running = True
        self._return_value = None
        self._exception = None

        thread = threading.Thread(target=_run_background, daemon=True)
        thread.start()

    @staticmethod
    def write_exception(
        exception: Exception,
        line_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        if exception is None:
            return
        for line in (
            line
            for frame in traceback.format_exception(exception)
            for line in frame.splitlines()
        ):
            _invoke_callback(line_callback, line)

    def exec_command(
        self,
        *args: str,
        env: Optional[dict[str, str]] = None,
        line_callback: Optional[Callable[[str], None]] = None,
        finally_callback: Optional[Callable[["Executor"], Any]] = None,
    ) -> None:
        if self.is_running:
            raise ValueError(f"Process is running: pid={self._process.pid}")

        self._exit_code = -1
        self._command_line = " ".join(args)
        self._process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env
        )

        def _enqueue_output() -> None:
            encoding = sys.getdefaultencoding()
            assert self._process is not None
            input_text_io = self._process.stdout
            assert input_text_io is not None

            while self._process.poll() is None:
                for buffer in iter(input_text_io.readline, b""):
                    text = buffer.decode(encoding).rstrip()
                    _invoke_callback(line_callback, text)

            input_text_io.close()
            self._exit_code = self._process.poll()
            self._process = None

        self.exec_function(_enqueue_output, finally_callback=finally_callback)

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def exit_code(self) -> int:
        return self._exit_code


class Installer(Executor):
    """Install / uninstall the ``nodebpy`` dependency set into Blender's
    extension site-packages.

    Installs prefer ``uv`` (``uv pip install --python <blender-python>
    --target <site-packages>``), which resolves and downloads far faster than
    pip. A system ``uv`` on ``PATH`` is used when present, otherwise an
    importable ``uv`` whose binary actually exists; when neither is available
    the install falls back to plain ``pip``, which always ships with Blender's
    Python. Either way the wheels land in a location already on Blender's
    ``sys.path``.

    ``bpy`` is deliberately *not* a dependency — it is provided by the running
    Blender interpreter, and ``nodebpy`` only declares it as an optional extra.
    """

    # Top-level pip distributions. ``networkx`` speeds up the topological sort
    # and ``ruff`` tidies the generated source; both are optional in nodebpy,
    # so installing them up front gives the nicest output out of the box.
    dependencies: list[str] = [
        "nodebpy",
        "networkx",
        "ruff",
    ]

    # pip dist name == importable module name for all three, so no mapping is
    # needed here.

    def get_required_modules(self) -> dict[str, bool]:
        modules = {d: False for d in self.dependencies}
        installed_top_levels = {m.name for m in pkgutil.iter_modules()}
        for dist in modules:
            if dist in installed_top_levels:
                modules[dist] = True
        return modules

    def is_ready(self) -> bool:
        """Whether ``nodebpy`` itself is importable (the hard requirement)."""
        return "nodebpy" in {m.name for m in pkgutil.iter_modules()}

    @staticmethod
    def _site_packages_path() -> Optional[str]:
        return next((p for p in sys.path if p.endswith("site-packages")), None)

    @staticmethod
    def _importable_uv_has_binary() -> bool:
        """Whether an importable ``uv`` module can actually find its binary."""
        try:
            import uv  # noqa: PLC0415

            uv.find_uv_bin()
            return True
        except Exception:
            return False

    @classmethod
    def _uv_command(cls) -> Optional[list[str]]:
        """How to invoke uv, preferring a uv already on the system."""
        system_uv = shutil.which("uv")
        if system_uv:
            return [system_uv]
        if (
            importlib.util.find_spec("uv") is not None
            and cls._importable_uv_has_binary()
        ):
            return [sys.executable, "-m", "uv"]
        return None

    @classmethod
    def _describe_installer(cls) -> str:
        """Human-readable note for the log box about which installer is used."""
        system_uv = shutil.which("uv")
        if system_uv:
            return f"Using system uv: {system_uv}"
        if cls._uv_command() is not None:
            return f"Using bundled uv: {sys.executable} -m uv"
        return f"No usable uv found — falling back to pip: {sys.executable} -m pip"

    @staticmethod
    def _subprocess_env(site_packages_path: Optional[str]) -> Optional[dict[str, str]]:
        """Env that lets a fresh ``python -m uv`` / ``pip`` import packages
        installed into the extension's ``--target`` site-packages."""
        if not site_packages_path:
            return None
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            site_packages_path + os.pathsep + existing
            if existing
            else site_packages_path
        )
        return env

    def _run_command_chain(
        self,
        commands: list[list[str]],
        env: Optional[dict[str, str]],
        line_callback: Optional[Callable[[str], None]],
        finally_callback: Optional[Callable[["Executor"], Any]],
    ) -> None:
        """Run subprocess commands sequentially, aborting if one fails."""
        if not commands:
            _invoke_callback(finally_callback, self)
            return

        head, *tail = commands

        def _after(executor: "Executor") -> None:
            if executor.exit_code != 0:
                _invoke_callback(finally_callback, executor)
                return
            self._run_command_chain(tail, env, line_callback, finally_callback)

        self.exec_command(
            *head,
            env=env,
            line_callback=line_callback,
            finally_callback=_after,
        )

    def _install_commands(
        self,
        packages: list[str],
        target_option: list[str],
    ) -> list[list[str]]:
        """Command chain to install ``packages`` (uv when usable, else pip)."""
        uv = self._uv_command()
        if uv is not None:
            return [
                [
                    *uv,
                    "pip",
                    "install",
                    "--python",
                    sys.executable,
                    *target_option,
                    *packages,
                ]
            ]

        commands: list[list[str]] = []
        if importlib.util.find_spec("pip") is None:
            commands.append([sys.executable, "-m", "ensurepip"])
        commands.append(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                *target_option,
                "--disable-pip-version-check",
                "--no-input",
                *packages,
            ]
        )
        return commands

    def install_python_modules(
        self,
        line_callback: Optional[Callable[[str], None]] = None,
        finally_callback: Optional[Callable[["Executor"], Any]] = None,
    ) -> None:
        site_packages_path = self._site_packages_path()
        target_option = ["--target", site_packages_path] if site_packages_path else []

        missing = [
            name
            for name, installed in self.get_required_modules().items()
            if not installed
        ]
        if not missing:
            # Nothing missing — reinstall the full set so the log box still
            # gives feedback.
            missing = list(self.dependencies)

        _invoke_callback(line_callback, self._describe_installer())
        self._run_command_chain(
            self._install_commands(missing, target_option),
            self._subprocess_env(site_packages_path),
            line_callback,
            finally_callback,
        )

    def uninstall_python_modules(
        self,
        line_callback: Optional[Callable[[str], None]] = None,
        finally_callback: Optional[Callable[["Executor"], Any]] = None,
    ) -> None:
        installed = [
            name
            for name, is_installed in self.get_required_modules().items()
            if is_installed
        ]
        if not installed:
            _invoke_callback(line_callback, "No installed dependencies to remove.")
            _invoke_callback(finally_callback, self)
            return
        # pip uninstall has no --target; it removes whatever it finds on
        # sys.path, so PYTHONPATH must include the extension site-packages.
        _invoke_callback(
            line_callback, f"Uninstalling with pip: {sys.executable} -m pip"
        )
        self.exec_command(
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "--yes",
            *installed,
            env=self._subprocess_env(self._site_packages_path()),
            line_callback=line_callback,
            finally_callback=finally_callback,
        )

    def list_python_modules(
        self,
        line_callback: Optional[Callable[[str], None]] = None,
        finally_callback: Optional[Callable[["Executor"], Any]] = None,
    ) -> None:
        self.exec_command(
            sys.executable,
            "-m",
            "pip",
            "list",
            "-v",
            line_callback=line_callback,
            finally_callback=finally_callback,
        )


installer = Installer()
