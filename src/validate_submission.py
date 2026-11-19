#!/usr/bin/env python3
"""Strict independent validator for Santa 2026 submission files."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_puzzles(path: Path) -> tuple[list[str], dict[str, dict]]:
    order = []
    puzzles = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            puzzle_id = row["id"]
            order.append(puzzle_id)
            puzzles[puzzle_id] = {
                "starting_values": json.loads(row["starting_values"]),
                "targets": set(json.loads(row["targets"])),
                "value_limit": int(row["value_limit"]),
                "registers": int(row["registers"]),
            }
    return order, puzzles


def replay(puzzle_id: str, puzzle: dict, program: list) -> None:
    if len(program) > 4096:
        raise ValueError(f"{puzzle_id}: more than 4096 instructions")
    registers = [None] * puzzle["registers"]
    for index, value in enumerate(puzzle["starting_values"]):
        registers[index] = value
    covered = puzzle["targets"] & set(puzzle["starting_values"])

    for step, instruction in enumerate(program, 1):
        if not isinstance(instruction, list) or len(instruction) != 4:
            raise ValueError(f"{puzzle_id}: malformed instruction {step}")
        operator, left_index, right_index, destination = instruction
        if operator not in {"+", "-", "*", "/"}:
            raise ValueError(f"{puzzle_id}: invalid operator at instruction {step}")
        indices = (left_index, right_index, destination)
        if any(type(index) is not int for index in indices):
            raise ValueError(f"{puzzle_id}: non-integer register at instruction {step}")
        if any(not 0 <= index < puzzle["registers"] for index in indices):
            raise ValueError(f"{puzzle_id}: register out of range at instruction {step}")
        left, right = registers[left_index], registers[right_index]
        if left is None or right is None:
            raise ValueError(f"{puzzle_id}: undefined source at instruction {step}")

        if operator == "+":
            result = left + right
        elif operator == "-":
            if left <= right:
                raise ValueError(f"{puzzle_id}: illegal subtraction at instruction {step}")
            result = left - right
        elif operator == "*":
            result = left * right
        else:
            if right == 0 or left % right:
                raise ValueError(f"{puzzle_id}: illegal division at instruction {step}")
            result = left // right

        if result < 1 or result > puzzle["value_limit"]:
            raise ValueError(f"{puzzle_id}: illegal value at instruction {step}")
        registers[destination] = result
        if result in puzzle["targets"]:
            covered.add(result)

    missing = puzzle["targets"] - covered
    if missing:
        raise ValueError(f"{puzzle_id}: missing {len(missing)} targets")


def validate(puzzles_path: Path, submission_path: Path) -> dict:
    expected_order, puzzles = load_puzzles(puzzles_path)
    with submission_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["id", "program"]:
            raise ValueError(f"wrong columns: {reader.fieldnames}")
        rows = list(reader)

    ids = [row["id"] for row in rows]
    if len(ids) != len(expected_order):
        raise ValueError(f"expected {len(expected_order)} rows, found {len(ids)}")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate IDs")
    if set(ids) != set(expected_order):
        raise ValueError("submission IDs do not match puzzle IDs")

    total = 0
    maximum_instructions = 0
    maximum_cell_bytes = 0
    for row in rows:
        cell_bytes = len(row["program"].encode("utf-8"))
        if cell_bytes > 131072:
            raise ValueError(f"{row['id']}: program cell exceeds 128 KiB")
        program = json.loads(row["program"])
        replay(row["id"], puzzles[row["id"]], program)
        total += len(program)
        maximum_instructions = max(maximum_instructions, len(program))
        maximum_cell_bytes = max(maximum_cell_bytes, cell_bytes)

    return {
        "valid": True,
        "rows": len(rows),
        "score": total,
        "maximum_instructions": maximum_instructions,
        "maximum_program_cell_bytes": maximum_cell_bytes,
        "file_bytes": submission_path.stat().st_size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puzzles", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.puzzles, args.submission), indent=2))


if __name__ == "__main__":
    main()
