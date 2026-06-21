#!/usr/bin/env python3

# Copyright (c) 2022-2026, The Isaac Lab Project Developers.
# All rights reserved.
#
# SPDX-License-Identifier: BSD-3-Clause

"""Patch a uv virtualenv activation script for Isaac Sim runtime loading.

Run this after installing dependencies into the uv environment, so the script can
resolve the torch-bundled libgomp path and preload it before Isaac Sim starts.
"""

from __future__ import annotations

import argparse
from pathlib import Path


BEGIN_MARKER = "# >>> Isaac Lab uv runtime fixes >>>"
END_MARKER = "# <<< Isaac Lab uv runtime fixes <<<"


def _repo_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name == "tools" and script_path.parent.parent.name == "scripts":
        return script_path.parents[2]
    return script_path.parent


def _find_torch_libgomp(env_path: Path) -> Path | None:
    matches = sorted((env_path / "lib").glob("python*/site-packages/torch/lib/libgomp*.so*"))
    return matches[-1] if matches else None


def _remove_existing_block(text: str) -> str:
    while True:
        begin = text.find(BEGIN_MARKER)
        if begin == -1:
            break

        end = text.find(END_MARKER, begin)
        if end == -1:
            raise RuntimeError(f"Found '{BEGIN_MARKER}' without matching '{END_MARKER}'.")

        end = text.find("\n", end)
        if end == -1:
            end = len(text)
        else:
            end += 1
        text = text[:begin].rstrip() + "\n" + text[end:].lstrip()

    legacy_begin = text.find("_isaaclab_prepend_ld_path () {")
    if legacy_begin != -1:
        legacy_end_marker = "unset _isaaclab_extscache _isaaclab_ext_dir _isaaclab_torch_gomp"
        legacy_end = text.find(legacy_end_marker, legacy_begin)
        if legacy_end != -1:
            legacy_end = text.find("\n", legacy_end)
            if legacy_end == -1:
                legacy_end = len(text)
            else:
                legacy_end += 1
            text = text[:legacy_begin].rstrip() + "\n" + text[legacy_end:].lstrip()

    return text.rstrip() + "\n"


def _runtime_block(isaaclab_path: Path, torch_libgomp: Path | None) -> str:
    torch_libgomp_value = str(torch_libgomp) if torch_libgomp is not None else ""
    return f"""
{BEGIN_MARKER}
_isaaclab_prepend_ld_path () {{
    [ -d "$1" ] || return 0
    case ":${{LD_LIBRARY_PATH:-}}:" in
        *":$1:"*) ;;
        *) LD_LIBRARY_PATH="$1${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}" ;;
    esac
}}

_isaaclab_newest_ext_dir () {{
    find "$_isaaclab_extscache" -maxdepth 2 -type d -path "$_isaaclab_extscache/$1" 2>/dev/null | sort -V | tail -n 1
}}

if [ -d "${{ISAAC_PATH:-}}/extscache" ]; then
    _isaaclab_extscache="${{ISAAC_PATH}}/extscache"
elif [ -d "${{ISAACLAB_PATH:-{isaaclab_path}}}/_isaac_sim/extscache" ]; then
    _isaaclab_extscache="${{ISAACLAB_PATH:-{isaaclab_path}}}/_isaac_sim/extscache"
elif [ -d "${{HOME}}/isaacsim/extscache" ]; then
    _isaaclab_extscache="${{HOME}}/isaacsim/extscache"
else
    _isaaclab_extscache=""
fi

if [ -n "$_isaaclab_extscache" ]; then
    for _isaaclab_ext_dir in \\
        "$(_isaaclab_newest_ext_dir "omni.usd.schema.audio-*/lib")" \\
        "$(_isaaclab_newest_ext_dir "omni.usd.libs-*/bin")" \\
        "$(_isaaclab_newest_ext_dir "omni.usd.core-*/bin")"
    do
        _isaaclab_prepend_ld_path "$_isaaclab_ext_dir"
    done
    export LD_LIBRARY_PATH
fi

_isaaclab_torch_gomp="{torch_libgomp_value}"
if [ -z "$_isaaclab_torch_gomp" ]; then
    _isaaclab_torch_gomp="$(find "${{VIRTUAL_ENV}}/lib" -path "*/site-packages/torch/lib/libgomp*.so*" -type f 2>/dev/null | sort -V | tail -n 1)"
fi
if [ -n "$_isaaclab_torch_gomp" ]; then
    case ":${{LD_PRELOAD:-}}:" in
        *":$_isaaclab_torch_gomp:"*) ;;
        *) export LD_PRELOAD="$_isaaclab_torch_gomp${{LD_PRELOAD:+:$LD_PRELOAD}}" ;;
    esac
fi

unset -f _isaaclab_prepend_ld_path _isaaclab_newest_ext_dir
unset _isaaclab_extscache _isaaclab_ext_dir _isaaclab_torch_gomp
{END_MARKER}
"""


def patch_activate(env_path: Path, isaaclab_path: Path) -> Path:
    activate_path = env_path / "bin" / "activate"
    if not activate_path.is_file():
        raise FileNotFoundError(f"Activation script not found: {activate_path}")

    text = activate_path.read_text()
    text = _remove_existing_block(text)

    torch_libgomp = _find_torch_libgomp(env_path)
    text = text.rstrip() + "\n" + _runtime_block(isaaclab_path, torch_libgomp).lstrip()
    activate_path.write_text(text)
    return activate_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch uv venv activate script for Isaac Lab runtime fixes.")
    parser.add_argument(
        "env_path",
        nargs="?",
        default=".venv",
        help="Path to the uv virtual environment. Defaults to '.venv'.",
    )
    parser.add_argument(
        "--isaaclab-path",
        default=str(_repo_root()),
        help="Isaac Lab repository path. Defaults to this script's repository root.",
    )
    args = parser.parse_args()

    env_path = Path(args.env_path).expanduser()
    if not env_path.is_absolute():
        env_path = Path.cwd() / env_path
    isaaclab_path = Path(args.isaaclab_path).expanduser().resolve()

    activate_path = patch_activate(env_path.resolve(), isaaclab_path)
    torch_libgomp = _find_torch_libgomp(env_path.resolve())
    print(f"[INFO] Patched uv activation script: {activate_path}")
    if torch_libgomp is None:
        print("[WARN] torch libgomp was not found yet. Re-run this script after installing torch.")
    else:
        print(f"[INFO] Using torch libgomp: {torch_libgomp}")


if __name__ == "__main__":
    main()
