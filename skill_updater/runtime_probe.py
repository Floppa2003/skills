"""Bounded Python behavior controls for the ub-mode tool bundle."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from mutator.edn import loads


FUNCTION = """def {name}({arg}):
    if {arg} > 0:
        result = {arg} + 1
    else:
        result = {arg} - 1
    return result
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    root = parser.parse_args().root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / "tests").mkdir()
    (root / "tests/__init__.py").touch()
    source = root / "pricing.py"
    source.write_text(FUNCTION.format(name="first_adjust", arg="value") + "\n" +
                      FUNCTION.format(name="second_adjust", arg="amount"))
    (root / "unique.py").write_text(FUNCTION.format(name="adjust", arg="value"))
    (root / "tests/test_strong.py").write_text(
        "import unittest\nfrom pricing import first_adjust, second_adjust\n"
        "class Strong(unittest.TestCase):\n"
        "    def test_values(self):\n"
        "        for function in (first_adjust, second_adjust):\n"
        "            for value, expected in ((-2,-3),(-1,-2),(0,-1),(1,2),(2,3)):\n"
        "                self.assertEqual(function(value), expected)\n")
    (root / "tests/test_weak.py").write_text(
        "import unittest\nfrom pricing import first_adjust, second_adjust\n"
        "class Weak(unittest.TestCase):\n"
        "    def test_types(self):\n"
        "        for function in (first_adjust, second_adjust):\n"
        "            self.assertIsInstance(function(2), int)\n")
    env_root = Path(sys.prefix)
    (root / ".venv").symlink_to(env_root, target_is_directory=True)
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    environment = os.environ | {"PYTHONDONTWRITEBYTECODE": "1"}

    def run(tool: str, *args: str, expected=0) -> None:
        result = subprocess.run([str(env_root / "bin" / tool), *args], cwd=root,
                                env=environment, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=60)
        (root / f"{tool}-{len(list(root.glob('*.log')))}.log").write_text(result.stdout)
        if result.returncode != expected:
            raise RuntimeError(f"{tool}: expected exit={expected} actual={result.returncode}: {result.stdout[-6000:]}")

    run("crapper", "--threshold", "10", "pricing.py")
    entries = loads((root / ".metrics/crap.edn").read_text())["entries"]
    assert {entry["name"] for entry in entries} == {"first_adjust", "second_adjust"}, entries
    assert all(entry["coverage"] == 100 and entry["crap"] < 10 for entry in entries), entries
    run("dryer", "--threshold", "0.8", "unique.py")
    assert loads((root / ".metrics/dry.edn").read_text())["candidates"] == []
    run("dryer", "--threshold", "0.8", "pricing.py")
    duplicates = loads((root / ".metrics/dry.edn").read_text())["candidates"]
    assert len(duplicates) == 1 and duplicates[0]["score"] == 1.0, duplicates

    def forms() -> list[dict]:
        files = sorted((root / ".metrics/mutate").glob("*.edn"))
        assert files, "mutation snapshot is missing"
        return [form for path in files for form in loads(path.read_text())["forms"]]

    common = ("--use-existing-coverage", "--mutate-all", "--max-workers", "2", "--test-command")
    run("mutator", *common, f"{env_root / 'bin/python'} -m unittest tests.test_weak", "pricing.py", expected=3)
    weak = forms()
    weak_count = sum(form["survived"] for form in weak)
    assert weak_count > 0 and sum(form["killed"] for form in weak) == 0, weak
    run("mutator", *common, f"{env_root / 'bin/python'} -m unittest tests.test_strong", "pricing.py")
    strong = forms()
    assert {form["id"] for form in strong} == {"defn/first_adjust", "defn/second_adjust"}, strong
    killed = sum(form["killed"] for form in strong)
    assert killed == weak_count, strong
    assert all(form["survived"] == 0 and form["uncovered"] == 0 for form in strong), strong
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original, "probe source was modified"
    assert not list((root / "target/mutation-workers").glob("**/worker-*")), "mutation workers leaked"
    print(json.dumps({"result": "PASS", "crap": [entry["crap"] for entry in entries],
                      "duplicate_pairs": len(duplicates), "weak_survivors": weak_count,
                      "strong_killed": killed, "source_preserved": True}))


if __name__ == "__main__":
    main()
