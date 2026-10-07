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
"unknown tool: <name>", as nob-nno (lt-merge) did through iOS 1.0.6. It also parses each
stage's options against tool_options() there (the upstream CLIs' option tables) the way
parse_argv() does: an option the tool doesn't define, or one marked on_ios = false
(lt-proc -i, hfst-proc -C, ...), fails that direction at runtime.

Usage: check-pair-tools.py <pair-jars-dir> <jnilibs-dir>
       check-pair-tools.py --ios <pair-jars-dir>
Run by CI: release-android.yml's build job after install-natives-android.sh, and
release-ios.yml's pairs job once the JARs are fetched.
"""
from __future__ import annotations

import re
import shlex
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


def ios_options() -> dict[str, dict]:
    """tool_options() in apertium_core.cpp → {tool: {"short": {c: (has_arg, on_ios)},
    "long": {name: c}}}."""
    src = APERTIUM_CORE.read_text()
    body = src[src.index("tool_options() {"):src.index("return t;")]
    entry = re.compile(r"\{'(.)', (?:\"([^\"]+)\"|nullptr), (true|false)(?:, (true|false))?\}")

    def spec(text: str) -> dict:
        found = entry.findall(text)
        return {"short": {c: (arg == "true", on_ios != "false") for c, _, arg, on_ios in found},
                "long": {name: c for c, name, _, _ in found if name}}

    shared = {m[1]: spec(m[2]) for m in
              re.finditer(r"static const std::vector<OptSpec> (\w+)\{(.*?)\n  \};", body, re.S)}
    tools = {m[1]: shared[m[2]] for m in re.finditer(r'\{"([a-z-]+)", (\w+)\}', body)}
    tools.update({m[1]: spec(m[2]) for m in re.finditer(r'\{"([a-z-]+)", \{(.*?\})\}', body, re.S)})
    return tools


def option_problems(stage: list[str], spec: dict) -> list[str]:
    """parse_argv()'s and dispatch_stage()'s complaints about one stage's options."""
    tool, args, problems = stage[0], stage[1:], []

    def use(c: str, value: str | None = None) -> None:
        has_arg, on_ios = spec["short"][c]
        if not on_ios:
            problems.append(f"{tool}: option -{c} is not supported on iOS")
        elif has_arg and value is None:
            problems.append(f"{tool}: option -{c} needs a value")
        elif tool == "cg-proc" and c == "f" and value != "1":
            problems.append(f"{tool}: -f {value} is not supported on iOS")
        elif c in {"lt-proc": "NLM", "hfst-proc": "Nl", "hfst-apertium-proc": "Nl"}.get(tool, ""):
            if not re.match(r"\s*[+-]?0*[1-9]", value or ""):  # atoi(value) >= 1
                problems.append(f"{tool}: invalid count for -{c}: {value}")

    i = 0
    while i < len(args):
        t = args[i]
        if t == "--":
            break
        if t.startswith("--") and len(t) > 2:
            name, eq, value = t[2:].partition("=")
            names = [n for n in spec["long"] if n == name] or \
                    [n for n in spec["long"] if n.startswith(name)]
            if len(names) != 1:
                problems.append(f"{tool}: unknown option --{name}")
            else:
                c = spec["long"][names[0]]
                if spec["short"][c][0] and not eq:
                    i += 1
                    value = args[i] if i < len(args) else None
                use(c, value if spec["short"][c][0] else None)
        elif t.startswith("-") and len(t) > 1:
            for j, c in enumerate(t[1:], 1):
                if c not in spec["short"]:
                    problems.append(f"{tool}: unknown option -{c}")
                    break
                if spec["short"][c][0]:
                    value = t[j + 1:]
                    if not value:
                        i += 1
                        value = args[i] if i < len(args) else None
                    use(c, value)
                    break
                use(c)
        i += 1
    return problems


def mode_stages(jar: zipfile.ZipFile, mode: str) -> list[list[str]] | None:
    """Argument list of each stage in <mode>.mode, or None if the JAR has no such mode."""
    names = [n for n in jar.namelist() if n.rsplit("/", 1)[-1] == f"{mode}.mode"]
    if not names:
        return None
    lines = [l.strip() for l in jar.read(names[0]).decode().splitlines()]
    line = next((l for l in lines if l and not l.startswith("#")), "")
    return [shlex.split(stage) for stage in line.split("|") if stage.strip()]


def check_directions(pairs_dir: Path, catalog: dict[str, dict],
                     stage_problems) -> tuple[list[str], int]:
    """Problems from stage_problems(mode, argv) for each offered direction's stages."""
    problems, checked = [], 0
    for jar_path in sorted(pairs_dir.glob("apertium-*.jar")):
        entry = catalog.get(jar_path.stem)
        if entry is None:
            continue
        with zipfile.ZipFile(jar_path) as jar:
            for mode in filter(None, (entry["forward"], entry["backward"])):
                stages = mode_stages(jar, mode)
                if stages is None:
                    problems.append(f"{jar_path.stem}: no {mode}.mode in the JAR")
                    continue
                checked += 1
                for stage in stages:
                    problems += stage_problems(mode, stage)
    return list(dict.fromkeys(problems)), checked


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

    def tool_problems(mode: str, stage: list[str]) -> list[str]:
        tool = stage[0]
        lib = libs.get(tool)
        if lib is None:
            return [f"{mode}: {tool} has no NativePipeline.TOOL_LIBS mapping"]
        return [f"{mode}: {tool} needs {abi.name}/{lib}, not installed"
                for abi in abis if not (abi / lib).is_file()]

    problems, checked = check_directions(pairs_dir, load_catalog(), tool_problems)
    return report(problems, f"checked {checked} directions across {len(abis)} ABIs")


def main_ios(pairs_dir: Path) -> int:
    tools, options = ios_tools(), ios_options()

    def tool_problems(mode: str, stage: list[str]) -> list[str]:
        tool = stage[0]
        if tool not in tools or tool not in options:
            return [f"{mode}: {tool} has no run_stage() case in ios/native/wrappers/apertium_core.cpp"]
        # $1/$2 as apertium(1) and apertium_core.cpp's rewrite_stage() substitute them.
        argv = [tool] + ["-g" if t == "$1" else t for t in stage[1:] if t != "$2"]
        return [f"{mode}: {p}" for p in option_problems(argv, options[tool])]

    problems, checked = check_directions(pairs_dir, ios_catalog(), tool_problems)
    return report(problems, f"checked {checked} iOS directions (tools and options)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--ios":
        sys.exit(main_ios(Path(sys.argv[2])))
    if len(sys.argv) == 3:
        sys.exit(main_android(Path(sys.argv[1]), Path(sys.argv[2])))
    sys.exit(__doc__)
