#!/usr/bin/env python3
"""Fail if a pair direction the app offers needs a native tool the app doesn't ship.

Android: for every pair JAR in <pair-jars-dir> and each direction PairCatalog.java
surfaces for it (forwardMode, backwardMode), reads the .mode pipeline and checks that
each stage's tool has a NativePipeline.TOOL_LIBS mapping and that the mapped lib*.so is
in every ABI dir under <jnilibs-dir>. Otherwise that direction fails at runtime
("no native binary mapping" / "native binary not executable"), as sme-nob (hfst-proc)
and nob-nno (lt-merge) did through 1.0.12.

iOS (--ios): same walk over the directions ios/Translate/PairCatalog.swift offers,
checking each stage's tool against the names run_stage() in
ios/native/wrappers/apertium_core.cpp dispatches. Any other tool fails at runtime with
"unknown tool: <name>", as nob-nno (lt-merge) did through iOS 1.0.6.

Usage: check-pair-tools.py <pair-jars-dir> <jnilibs-dir>
       check-pair-tools.py --ios <pair-jars-dir>
Run by CI: release-android.yml's build job after install-natives-android.sh, and
release-ios.yml's pairs job once the JARs are fetched.
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

from _pair_catalog import load as load_catalog

REPO = Path(__file__).resolve().parent.parent
NATIVE_PIPELINE = REPO / "android/app/src/main/java/com/qvyshift/translate/NativePipeline.java"
SWIFT_CATALOG = REPO / "ios/Translate/PairCatalog.swift"
APERTIUM_CORE = REPO / "ios/native/wrappers/apertium_core.cpp"


def tool_libs() -> dict[str, str]:
    return dict(re.findall(r'TOOL_LIBS\.put\("([^"]+)",\s*"([^"]+)"\)',
                           NATIVE_PIPELINE.read_text()))


def ios_catalog() -> dict[str, dict]:
    """PairCatalog.swift → {pkg: {"forward": ..., "backward": ... | None}}."""
    pattern = (r'pkg: "(apertium-[a-z_]+-[a-z_]+)",\s*forwardMode: "([^"]+)",'
               r'\s*backwardMode: (?:"([^"]+)"|nil)')
    return {pkg: {"forward": fwd, "backward": bwd or None}
            for pkg, fwd, bwd in re.findall(pattern, SWIFT_CATALOG.read_text())}


def ios_tools() -> set[str]:
    return set(re.findall(r'tool == "([^"]+)"', APERTIUM_CORE.read_text()))


def mode_tools(jar: zipfile.ZipFile, mode: str) -> list[str] | None:
    """Tool name of each stage in <mode>.mode, or None if the JAR has no such mode."""
    names = [n for n in jar.namelist() if n.rsplit("/", 1)[-1] == f"{mode}.mode"]
    if not names:
        return None
    lines = [l.strip() for l in jar.read(names[0]).decode().splitlines()]
    line = next((l for l in lines if l and not l.startswith("#")), "")
    return [stage.split()[0] for stage in line.split("|") if stage.strip()]


def check_directions(pairs_dir: Path, catalog: dict[str, dict],
                     tool_problems) -> tuple[list[str], int]:
    """Problems from tool_problems(mode, tool) for each offered direction's tools."""
    problems, checked = [], 0
    for jar_path in sorted(pairs_dir.glob("apertium-*.jar")):
        entry = catalog.get(jar_path.stem)
        if entry is None:
            continue
        with zipfile.ZipFile(jar_path) as jar:
            for mode in filter(None, (entry["forward"], entry["backward"])):
                tools = mode_tools(jar, mode)
                if tools is None:
                    problems.append(f"{jar_path.stem}: no {mode}.mode in the JAR")
                    continue
                checked += 1
                for tool in dict.fromkeys(tools):
                    problems += tool_problems(mode, tool)
    return problems, checked


def report(problems: list[str], summary: str) -> int:
    for p in problems:
        print(f"::error::{p}")
    print(f"{summary}: {'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


def main_android(pairs_dir: Path, jnilibs: Path) -> int:
    libs = tool_libs()
    abis = sorted(d for d in jnilibs.iterdir() if d.is_dir())
    if not abis:
        print(f"no ABI dirs under {jnilibs}")
        return 1

    def tool_problems(mode: str, tool: str) -> list[str]:
        lib = libs.get(tool)
        if lib is None:
            return [f"{mode}: {tool} has no NativePipeline.TOOL_LIBS mapping"]
        return [f"{mode}: {tool} needs {abi.name}/{lib}, not installed"
                for abi in abis if not (abi / lib).is_file()]

    problems, checked = check_directions(pairs_dir, load_catalog(), tool_problems)
    return report(problems, f"checked {checked} directions across {len(abis)} ABIs")


def main_ios(pairs_dir: Path) -> int:
    tools = ios_tools()

    def tool_problems(mode: str, tool: str) -> list[str]:
        if tool in tools:
            return []
        return [f"{mode}: {tool} has no run_stage() case in ios/native/wrappers/apertium_core.cpp"]

    problems, checked = check_directions(pairs_dir, ios_catalog(), tool_problems)
    return report(problems, f"checked {checked} iOS directions")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--ios":
        sys.exit(main_ios(Path(sys.argv[2])))
    if len(sys.argv) == 3:
        sys.exit(main_android(Path(sys.argv[1]), Path(sys.argv[2])))
    sys.exit(__doc__)
