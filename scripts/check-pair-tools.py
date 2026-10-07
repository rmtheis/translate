#!/usr/bin/env python3
"""Fail if a pair direction the app offers needs a native tool the APK doesn't ship.

For every pair JAR in <pair-jars-dir> and each direction PairCatalog.java surfaces
for it (forwardMode, backwardMode), reads the .mode pipeline and checks that each
stage's tool has a NativePipeline.TOOL_LIBS mapping and that the mapped lib*.so is
in every ABI dir under <jnilibs-dir>. Otherwise that direction fails at runtime
("no native binary mapping" / "native binary not executable"), as sme-nob (hfst-proc)
and nob-nno (lt-merge) did through 1.0.12.

Usage: check-pair-tools.py <pair-jars-dir> <jnilibs-dir>
Run by the CI build job after install-natives-android.sh.
"""
import re
import sys
import zipfile
from pathlib import Path

from _pair_catalog import load as load_catalog

NATIVE_PIPELINE = (Path(__file__).resolve().parent.parent
                   / "android/app/src/main/java/com/qvyshift/translate/NativePipeline.java")


def tool_libs() -> dict[str, str]:
    return dict(re.findall(r'TOOL_LIBS\.put\("([^"]+)",\s*"([^"]+)"\)',
                           NATIVE_PIPELINE.read_text()))


def mode_tools(jar: zipfile.ZipFile, mode: str) -> list[str] | None:
    """Tool name of each stage in <mode>.mode, or None if the JAR has no such mode."""
    names = [n for n in jar.namelist() if n.rsplit("/", 1)[-1] == f"{mode}.mode"]
    if not names:
        return None
    lines = [l.strip() for l in jar.read(names[0]).decode().splitlines()]
    line = next((l for l in lines if l and not l.startswith("#")), "")
    return [stage.split()[0] for stage in line.split("|") if stage.strip()]


def main(pairs_dir: Path, jnilibs: Path) -> int:
    catalog = load_catalog()
    libs = tool_libs()
    abis = sorted(d for d in jnilibs.iterdir() if d.is_dir())
    if not abis:
        print(f"no ABI dirs under {jnilibs}")
        return 1
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
                    lib = libs.get(tool)
                    if lib is None:
                        problems.append(f"{mode}: {tool} has no NativePipeline.TOOL_LIBS mapping")
                        continue
                    for abi in abis:
                        if not (abi / lib).is_file():
                            problems.append(f"{mode}: {tool} needs {abi.name}/{lib}, not installed")
    for p in problems:
        print(f"::error::{p}")
    print(f"checked {checked} directions across {len(abis)} ABIs: "
          f"{'OK' if not problems else f'{len(problems)} problem(s)'}")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
