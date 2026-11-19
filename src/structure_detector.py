#!/usr/bin/env python3
"""Extract structural signals from Santa 2026 calculator puzzles.

The module intentionally uses only the Python standard library so it can run
in a clean competition environment.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import gcd
from pathlib import Path
from typing import Iterable


FAMILIES = ("independent", "shared", "multiplicative", "mixed", "tiny")
SMALL_PRIMES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47)


def quantile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * p
    lo = math.floor(position)
    hi = math.ceil(position)
    if lo == hi:
        return float(ordered[lo])
    weight = position - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def safe_mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.mean(values) if values else 0.0


def safe_stdev(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.pstdev(values) if len(values) > 1 else 0.0


def binary_prefix_fraction(a: int, b: int) -> float:
    bits_a = a.bit_length()
    bits_b = b.bit_length()
    width = max(bits_a, bits_b)
    xor = a ^ b
    common = width if xor == 0 else width - xor.bit_length()
    return common / width


def negative_log10(value: float, cap: float = 20.0) -> float:
    """Turn very small structural ratios into a stable, readable scale."""
    if value <= 0.0:
        return cap
    return min(cap, -math.log10(value))


def load_puzzles(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    parsed = []
    for row in rows:
        item = dict(row)
        item["starting_values"] = json.loads(row["starting_values"])
        item["targets"] = json.loads(row["targets"])
        item["value_limit"] = int(row["value_limit"])
        item["registers"] = int(row["registers"])
        if "lower_bound" in row:
            item["lower_bound"] = int(row["lower_bound"])
        parsed.append(item)
    return parsed


def extract_features(puzzle: dict) -> dict[str, float]:
    starts = puzzle["starting_values"]
    targets = puzzle["targets"]
    target_set = set(targets)
    start_set = set(starts)
    n = len(targets)

    logs = [math.log2(value) for value in targets]
    bits = [value.bit_length() for value in targets]
    adjacent = list(zip(targets, targets[1:]))
    gaps = [b - a for a, b in adjacent]
    gap_ratios = [gap / b for gap, (_, b) in zip(gaps, adjacent)]
    adjacent_prefixes = [binary_prefix_fraction(a, b) for a, b in adjacent]

    pair_count = n * (n - 1) // 2
    divides = 0
    small_quotient = 0
    gcd_fractions = []
    pair_prefixes = []
    diff_is_start = 0
    sum_is_target = 0
    diff_is_target = 0
    product_is_target = 0
    quotient_is_target = 0

    for i, a in enumerate(targets):
        for b in targets[i + 1 :]:
            g = gcd(a, b)
            gcd_fractions.append(math.log2(g) / max(1.0, min(math.log2(a), math.log2(b))))
            pair_prefixes.append(binary_prefix_fraction(a, b))
            difference = b - a
            if difference in start_set:
                diff_is_start += 1
            if a + b in target_set:
                sum_is_target += 1
            if difference in target_set:
                diff_is_target += 1
            if a * b in target_set:
                product_is_target += 1
            if b % a == 0:
                quotient = b // a
                divides += 1
                if quotient <= 1024:
                    small_quotient += 1
                if quotient in target_set:
                    quotient_is_target += 1

    prime_coverages = [sum(value % prime == 0 for value in targets) / n for prime in SMALL_PRIMES]
    any_start_divides = sum(any(value % start == 0 for start in starts) for value in targets) / n
    target_gcd = 0
    for value in targets:
        target_gcd = gcd(target_gcd, value)

    close_thresholds = {
        "adjacent_close_1e3": 1e-3,
        "adjacent_close_1e6": 1e-6,
        "adjacent_close_1e9": 1e-9,
        "adjacent_close_1e12": 1e-12,
    }

    features: dict[str, float] = {
        "n_start": float(len(starts)),
        "n_targets": float(n),
        "lower_bound": float(len(target_set - start_set)),
        "min_log2": min(logs),
        "max_log2": max(logs),
        "span_log2": max(logs) - min(logs),
        "mean_log2": safe_mean(logs),
        "stdev_log2": safe_stdev(logs),
        "unique_bit_lengths": float(len(set(bits))),
        "headroom_log2": math.log2(puzzle["value_limit"] / max(targets)),
        "min_target_fraction": min(targets) / max(targets),
        "min_target_fraction_log10": negative_log10(min(targets) / max(targets)),
        "median_target_fraction": statistics.median(targets) / max(targets),
        "adjacent_gap_min": min(gap_ratios) if gap_ratios else 1.0,
        "adjacent_gap_q25": quantile(gap_ratios, 0.25) if gap_ratios else 1.0,
        "adjacent_gap_median": statistics.median(gap_ratios) if gap_ratios else 1.0,
        "adjacent_gap_min_log10": negative_log10(min(gap_ratios)) if gap_ratios else 0.0,
        "adjacent_gap_q25_log10": negative_log10(quantile(gap_ratios, 0.25)) if gap_ratios else 0.0,
        "adjacent_gap_stdev": safe_stdev(gap_ratios),
        "adjacent_prefix_max": max(adjacent_prefixes) if adjacent_prefixes else 0.0,
        "adjacent_prefix_mean": safe_mean(adjacent_prefixes),
        "pair_prefix_mean": safe_mean(pair_prefixes),
        "pair_gcd_mean": safe_mean(gcd_fractions),
        "pair_gcd_q75": quantile(gcd_fractions, 0.75),
        "pair_gcd_max": max(gcd_fractions) if gcd_fractions else 0.0,
        "divisibility_rate": divides / pair_count if pair_count else 0.0,
        "small_quotient_rate": small_quotient / pair_count if pair_count else 0.0,
        "diff_is_start_rate": diff_is_start / pair_count if pair_count else 0.0,
        "sum_relation_rate": sum_is_target / pair_count if pair_count else 0.0,
        "diff_relation_rate": diff_is_target / pair_count if pair_count else 0.0,
        "product_relation_rate": product_is_target / pair_count if pair_count else 0.0,
        "quotient_relation_rate": quotient_is_target / pair_count if pair_count else 0.0,
        "gcd_all_fraction": math.log2(target_gcd) / max(logs) if target_gcd > 1 else 0.0,
        "max_small_prime_coverage": max(prime_coverages),
        "mean_small_prime_coverage": safe_mean(prime_coverages),
        "start_divides_target_rate": any_start_divides,
    }
    for name, threshold in close_thresholds.items():
        features[name] = sum(ratio <= threshold for ratio in gap_ratios) / max(1, len(gap_ratios))
    return features


def summarize_by_family(rows: list[dict], features: list[dict[str, float]]) -> dict:
    grouped: dict[str, list[dict[str, float]]] = defaultdict(list)
    for row, feature_row in zip(rows, features):
        grouped[row["family"]].append(feature_row)

    selected = (
        "n_targets",
        "span_log2",
        "stdev_log2",
        "min_target_fraction",
        "adjacent_gap_min",
        "adjacent_gap_q25",
        "adjacent_prefix_max",
        "adjacent_close_1e3",
        "adjacent_close_1e6",
        "divisibility_rate",
        "small_quotient_rate",
        "pair_gcd_mean",
        "pair_gcd_q75",
        "max_small_prime_coverage",
        "start_divides_target_rate",
        "sum_relation_rate",
        "diff_relation_rate",
        "product_relation_rate",
    )
    result = {}
    for family in FAMILIES:
        family_rows = grouped[family]
        result[family] = {
            name: {
                "median": round(statistics.median(row[name] for row in family_rows), 8),
                "q25": round(quantile([row[name] for row in family_rows], 0.25), 8),
                "q75": round(quantile([row[name] for row in family_rows], 0.75), 8),
            }
            for name in selected
        }
    return result


def standardized_distance(a: dict[str, float], b: dict[str, float], scales: dict[str, float]) -> float:
    return math.sqrt(
        sum(((a[name] - b[name]) / scales[name]) ** 2 for name in scales) / max(1, len(scales))
    )


@dataclass
class StandardizedKNN:
    k: int = 7
    feature_names: tuple[str, ...] = ()
    scales: dict[str, float] | None = None
    training_features: list[dict[str, float]] | None = None
    training_labels: list[str] | None = None

    def fit(self, features: list[dict[str, float]], labels: list[str]) -> "StandardizedKNN":
        if not features:
            raise ValueError("empty training data")
        if not self.feature_names:
            self.feature_names = tuple(features[0])
        self.scales = {}
        for name in self.feature_names:
            values = [row[name] for row in features]
            scale = quantile(values, 0.75) - quantile(values, 0.25)
            if scale <= 1e-12:
                scale = safe_stdev(values)
            self.scales[name] = scale if scale > 1e-12 else 1.0
        self.training_features = features
        self.training_labels = labels
        return self

    def predict_proba_one(self, feature_row: dict[str, float]) -> dict[str, float]:
        assert self.scales is not None
        assert self.training_features is not None
        assert self.training_labels is not None
        neighbors = sorted(
            (
                standardized_distance(feature_row, candidate, self.scales),
                label,
            )
            for candidate, label in zip(self.training_features, self.training_labels)
        )[: self.k]
        votes = Counter()
        for distance, label in neighbors:
            votes[label] += 1.0 / max(distance, 1e-6)
        total = sum(votes.values())
        return {family: votes[family] / total for family in FAMILIES}

    def predict_one(self, feature_row: dict[str, float]) -> tuple[str, float, dict[str, float]]:
        probabilities = self.predict_proba_one(feature_row)
        label = max(probabilities, key=probabilities.get)
        return label, probabilities[label], probabilities


AMBIGUOUS_FAMILIES = {"shared", "multiplicative", "mixed"}
AMBIGUOUS_FEATURES = (
    "pair_gcd_q75",
    "adjacent_close_1e3",
    "adjacent_gap_median",
    "stdev_log2",
    "mean_small_prime_coverage",
    "span_log2",
)


@dataclass
class HierarchicalStructureClassifier:
    """Use exact structural rules first, then k-NN for overlapping families."""

    k: int = 9
    ambiguous_model: StandardizedKNN | None = None

    def fit(self, features: list[dict[str, float]], labels: list[str]) -> "HierarchicalStructureClassifier":
        selected = [
            (row, label)
            for row, label in zip(features, labels)
            if label in AMBIGUOUS_FAMILIES
        ]
        self.ambiguous_model = StandardizedKNN(
            k=self.k, feature_names=AMBIGUOUS_FEATURES
        ).fit([row for row, _ in selected], [label for _, label in selected])
        return self

    def predict_one(self, row: dict[str, float]) -> tuple[str, float, dict[str, float]]:
        if row["n_targets"] <= 4 and row["max_log2"] <= 4.0:
            return "tiny", 1.0, {family: float(family == "tiny") for family in FAMILIES}
        if row["span_log2"] < 4.5:
            return "independent", 1.0, {
                family: float(family == "independent") for family in FAMILIES
            }
        assert self.ambiguous_model is not None
        label, confidence, partial = self.ambiguous_model.predict_one(row)
        probabilities = {family: partial.get(family, 0.0) for family in FAMILIES}
        return label, confidence, probabilities


def strategy_for_family(family: str) -> str:
    return {
        "tiny": "exact_search",
        "independent": "individual_chains_then_global_reuse",
        "shared": "shared_trunk_and_small_differences",
        "multiplicative": "factor_graph_and_shared_products",
        "mixed": "hybrid_factor_and_difference_search",
    }[family]


def stratified_folds(labels: list[str], folds: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    grouped: dict[str, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        grouped[label].append(index)
    fold_indices = [[] for _ in range(folds)]
    for indices in grouped.values():
        rng.shuffle(indices)
        for offset, index in enumerate(indices):
            fold_indices[offset % folds].append(index)
    return fold_indices


def cross_validate_knn(
    features: list[dict[str, float]],
    labels: list[str],
    feature_names: tuple[str, ...],
    k: int,
    repeats: int = 20,
    folds: int = 5,
) -> dict:
    predictions = []
    truths = []
    confidences = []
    for seed in range(repeats):
        for test_indices in stratified_folds(labels, folds, seed):
            test_set = set(test_indices)
            train_features = [row for i, row in enumerate(features) if i not in test_set]
            train_labels = [label for i, label in enumerate(labels) if i not in test_set]
            model = StandardizedKNN(k=k, feature_names=feature_names).fit(train_features, train_labels)
            for index in test_indices:
                predicted, confidence, _ = model.predict_one(features[index])
                truths.append(labels[index])
                predictions.append(predicted)
                confidences.append(confidence)
    confusion = {family: Counter() for family in FAMILIES}
    for truth, prediction in zip(truths, predictions):
        confusion[truth][prediction] += 1
    correct = sum(a == b for a, b in zip(truths, predictions))
    return {
        "accuracy": correct / len(truths),
        "mean_confidence": safe_mean(confidences),
        "confusion": {truth: dict(confusion[truth]) for truth in FAMILIES},
    }


def cross_validate_hierarchical(
    features: list[dict[str, float]],
    labels: list[str],
    repeats: int = 30,
    folds: int = 5,
) -> dict:
    predictions = []
    truths = []
    confidences = []
    for seed in range(repeats):
        for test_indices in stratified_folds(labels, folds, seed):
            test_set = set(test_indices)
            train_features = [row for i, row in enumerate(features) if i not in test_set]
            train_labels = [label for i, label in enumerate(labels) if i not in test_set]
            model = HierarchicalStructureClassifier().fit(train_features, train_labels)
            for index in test_indices:
                predicted, confidence, _ = model.predict_one(features[index])
                truths.append(labels[index])
                predictions.append(predicted)
                confidences.append(confidence)
    confusion = {family: Counter() for family in FAMILIES}
    for truth, prediction in zip(truths, predictions):
        confusion[truth][prediction] += 1
    return {
        "accuracy": sum(a == b for a, b in zip(truths, predictions)) / len(truths),
        "mean_confidence": safe_mean(confidences),
        "confusion": {truth: dict(confusion[truth]) for truth in FAMILIES},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--practice", type=Path, required=True)
    parser.add_argument("--scored", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    practice = load_puzzles(args.practice)
    practice_features = [extract_features(row) for row in practice]
    labels = [row["family"] for row in practice]

    cv_result = cross_validate_hierarchical(practice_features, labels)
    model = HierarchicalStructureClassifier().fit(practice_features, labels)

    report = {
        "practice_rows": len(practice),
        "family_counts": dict(Counter(labels)),
        "family_feature_summary": summarize_by_family(practice, practice_features),
        "cross_validation": cv_result,
        "selected_model": {
            "type": "hierarchical_rules_plus_knn",
            "k": model.k,
            "features": AMBIGUOUS_FEATURES,
            "rules": [
                "n_targets <= 4 and max_log2 <= 4 => tiny",
                "span_log2 < 4.5 => independent",
                "otherwise classify shared/multiplicative/mixed with k-NN",
            ],
        },
    }

    if args.scored:
        scored = load_puzzles(args.scored)
        predictions = []
        for row in scored:
            feature_row = extract_features(row)
            label, confidence, probabilities = model.predict_one(feature_row)
            predictions.append(
                {
                    "id": row["id"],
                    "predicted_family": label,
                    "recommended_strategy": strategy_for_family(label),
                    "confidence": round(confidence, 6),
                    "probabilities": {k: round(v, 6) for k, v in probabilities.items()},
                    "signals": {
                        name: round(feature_row[name], 8)
                        for name in ("n_targets", "max_log2") + AMBIGUOUS_FEATURES
                    },
                }
            )
        report["scored_predictions"] = predictions
        report["scored_family_counts"] = dict(Counter(row["predicted_family"] for row in predictions))
        report["scored_low_confidence"] = sum(row["confidence"] < 0.55 for row in predictions)

    encoded = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)


if __name__ == "__main__":
    main()
