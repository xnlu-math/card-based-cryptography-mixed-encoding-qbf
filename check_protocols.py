#!/usr/bin/env python3
"""Check decoded AND protocols by exact enumeration, independently of the QBF.

Only the Python standard library is used; neither qbf_gen.py nor a solver is
imported. A protocol applies fixed rearrangement/shuffle blocks, turns one fixed
set of cards, and selects an unturned output from the public observation.
Permutations and positions in the JSON input are 1-based, as in the paper.
"""
import argparse
import itertools
import json
from collections import defaultdict
from fractions import Fraction
from pathlib import Path


def permutation(value, n):
    if (not isinstance(value, list) or len(value) != n
            or any(type(j) is not int for j in value)
            or sorted(value) != list(range(1, n + 1))):
        raise ValueError('a permutation must contain each position exactly once')
    return [j - 1 for j in value]


def move(cards, perm):
    result = [None] * len(cards)
    for source, destination in enumerate(perm):
        result[destination] = cards[source]
    return tuple(result)


def check_protocol(protocol):
    layout = protocol['input_layout']
    if (not isinstance(layout, list) or not layout
            or any(type(card) not in (int, str) or card not in (0, 1, 'a', 'b', 'not_b')
                   for card in layout)):
        raise ValueError('input cards must be 0, 1, a, b, or not_b')
    n = len(layout)
    blocks = []
    for block in protocol['blocks']:
        rearrangement = permutation(block['rearrangement'], n)
        outcomes = []
        for outcome in block['outcomes']:
            if not isinstance(outcome['probability'], str):
                raise ValueError('write exact probabilities as strings, e.g. "1/2"')
            probability = Fraction(outcome['probability'])
            if probability <= 0:
                raise ValueError('every shuffle outcome must have positive probability')
            outcomes.append((permutation(outcome['permutation'], n), probability))
        if sum((p for _, p in outcomes), Fraction(0)) != 1:
            raise ValueError('shuffle probabilities must sum to one')
        if len({tuple(perm) for perm, _ in outcomes}) != len(outcomes):
            raise ValueError('a shuffle must not repeat a permutation')
        blocks.append((rearrangement, outcomes))

    raw_turn = protocol['turn']
    if (not isinstance(raw_turn, list) or any(type(j) is not int or not 1 <= j <= n for j in raw_turn)
            or len(set(raw_turn)) != len(raw_turn) or len(raw_turn) >= n):
        raise ValueError('the turn set must contain distinct positions and leave an output card')
    turn = [j - 1 for j in raw_turn]
    rules = protocol['output']
    observations = {''.join(map(str, v)) for v in itertools.product((0, 1), repeat=len(turn))}
    if set(rules) != observations:
        raise ValueError('the output rule must cover every possible observation')
    if any(type(j) is not int or not 1 <= j <= n or j in raw_turn for j in rules.values()):
        raise ValueError('every output position must be a valid unturned position')

    distributions, failures = {}, []
    for a, b in itertools.product((0, 1), repeat=2):
        values = {0: 0, 1: 1, 'a': a, 'b': b, 'not_b': 1 - b}
        initial = tuple(values[card] for card in layout)
        distribution = defaultdict(Fraction)
        for outcomes in itertools.product(*(support for _, support in blocks)):
            cards, probability = initial, Fraction(1)
            for (rearrangement, _), (shuffle, weight) in zip(blocks, outcomes):
                cards = move(move(cards, rearrangement), shuffle)
                probability *= weight
            visible = ''.join(str(cards[j]) for j in turn)
            distribution[visible] += probability
            output = cards[rules[visible] - 1]
            if output != (a & b):
                failures.append({'input': [a, b], 'observation': visible, 'output': output,
                                 'probability': str(probability)})
        distributions[str(a) + str(b)] = dict(distribution)

    baseline = distributions['00']
    actual = {
        'correct': not failures,
        'possibilistic_security': all(set(d) == set(baseline) for d in distributions.values()),
        'perfect_security': all(d == baseline for d in distributions.values()),
    }
    expected = protocol['expected']
    if set(expected) != set(actual) or any(type(value) is not bool for value in expected.values()):
        raise ValueError('expected must specify the three Boolean verdicts')
    return {
        'name': protocol['name'],
        'passed': actual == expected,
        'actual': actual,
        'expected': expected,
        'trace_probabilities': {ab: {v: str(p) for v, p in sorted(d.items())}
                                for ab, d in distributions.items()},
        'incorrect_executions': failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('protocols', nargs='?', type=Path,
                        default=Path(__file__).resolve().parent / 'witnesses' / 'positive_protocols.json')
    parser.add_argument('--json', type=Path, help='write the full exact results to this file')
    args = parser.parse_args()
    try:
        document = json.loads(args.protocols.read_text(encoding='utf-8'))
        if document['schema_version'] != 1 or not document['protocols']:
            raise ValueError('expected schema version 1 and a nonempty list of protocols')
        results = [check_protocol(p) for p in document['protocols']]
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as error:
        parser.exit(2, 'Invalid protocol input: {}\n'.format(error))
    for result in results:
        verdict = result['actual']
        print('{} {}: correct={}, possibilistic_security={}, perfect_security={}'.format(
            'PASS' if result['passed'] else 'FAIL', result['name'],
            verdict['correct'], verdict['possibilistic_security'], verdict['perfect_security']))
    if args.json:
        args.json.write_text(json.dumps({'results': results}, indent=2, ensure_ascii=False) + '\n',
                             encoding='utf-8')
    raise SystemExit(0 if all(result['passed'] for result in results) else 1)


if __name__ == '__main__':
    main()
