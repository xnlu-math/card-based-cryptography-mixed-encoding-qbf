#!/usr/bin/env python3
"""Reproduce Table 2 of the paper: generate the instances, solve them, and write the results.

For each row of Table 2, this script writes the formula to instances/, runs DepQBF
(and CAQE, if available) on it, stores the raw solver output in outputs/, and writes
results/results.md with the truth values, formula sizes, wall-clock times, and the
protocols read off from the true formulas.

Usage:  python3 run.py [--depqbf PATH] [--caqe PATH | --no-caqe] [--timeout SECONDS]
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import time

from qbf_gen import build, decode, instance_name

HERE = os.path.dirname(os.path.abspath(__file__))

# The rows of Table 2: (number of working cards, number k of shuffles, shuffle class, security).
TABLE2 = [
    (3, 1, 'transposition', True),
    (3, 1, 'closed', True),
    (3, 1, 'arbitrary', True),
    (3, 1, 'arbitrary', False),
    (4, 1, 'rbc', True),
    (4, 1, 'closed', True),
    (4, 1, 'rc', True),
]

INPUT_SEQUENCE = {3: '(a, b, ¬b)', 4: '(♣, a, b, ¬b)'}
CLASS_NAME = {'transposition': '{id, τ}', 'rbc': 'random bisection cuts', 'closed': 'closed',
              'rc': 'random cuts', 'arbitrary': 'arbitrary'}


def solver_version(cmd):
    try:
        res = subprocess.run([cmd, '--version'], capture_output=True, text=True)
    except OSError:
        return None
    lines = (res.stdout or res.stderr).strip().splitlines()
    return lines[0] if lines else '?'


def solve(cmd, args, path, out_path, timeout):
    """Run a solver; return ('true' | 'false' | 'timeout' | 'error', seconds, true variables)."""
    t0 = time.perf_counter()
    try:
        # Run in the repository directory with a relative path, so that the stored outputs
        # do not contain local absolute paths.
        res = subprocess.run([cmd, *args, os.path.relpath(path, HERE)], cwd=HERE,
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 'timeout', time.perf_counter() - t0, set()
    secs = time.perf_counter() - t0
    with open(out_path, 'w') as fh:
        fh.write(res.stdout)
    # Both solvers exit with 10 for a true formula and 20 for a false one (QDIMACS convention).
    value = {10: 'true', 20: 'false'}.get(res.returncode, 'error')
    true_vars = {int(line.split()[1]) for line in res.stdout.splitlines()
                 if line.startswith('V') and int(line.split()[1]) > 0}
    return value, secs, true_vars


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--depqbf', default='depqbf', help='DepQBF executable (default: depqbf)')
    ap.add_argument('--caqe', default='caqe', help='CAQE executable (default: caqe; skipped if not found)')
    ap.add_argument('--no-caqe', action='store_true', help='do not run CAQE')
    ap.add_argument('--timeout', type=float, default=None, help='time limit per solver run in seconds')
    args = ap.parse_args()

    depqbf_version = solver_version(args.depqbf)
    if depqbf_version is None:
        sys.exit(f'DepQBF not found: {args.depqbf}')
    caqe = None if args.no_caqe else shutil.which(args.caqe)
    caqe_version = solver_version(caqe) if caqe else None
    if not args.no_caqe and caqe is None:
        print(f'CAQE not found ({args.caqe}); running DepQBF only.')

    dirs = {d: os.path.join(HERE, *d.split('/')) for d in
            ('instances', 'outputs/depqbf', 'outputs/caqe', 'results')}
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)

    rows, protocols = [], []
    for cards, k, shuffles, security in TABLE2:
        name = instance_name(cards, k, shuffles, security)
        path = os.path.join(dirs['instances'], name + '.qdimacs')
        q, info = build(cards, k, shuffles, security)
        q.write(path, [f'{name}: cards={cards} blocks={k} shuffles={shuffles} '
                       f'security={"yes" if security else "no"}'])
        # --qdo prints the values of the outermost existential block (the protocol);
        # DepQBF requires --no-dynamic-nenofex together with --qdo.
        d_val, d_secs, d_true = solve(args.depqbf, ['--qdo', '--no-dynamic-nenofex'], path,
                                      os.path.join(dirs['outputs/depqbf'], name + '.txt'), args.timeout)
        row = [name, INPUT_SEQUENCE[cards], CLASS_NAME[shuffles], 'yes' if security else 'no',
               str(q.num_vars), str(len(q.clauses)), d_val, f'{d_secs:.2f}']
        msg = f'{name:32s} DepQBF {d_val:7s} {d_secs:7.2f} s'
        if caqe:
            c_val, c_secs, _ = solve(caqe, ['--qdo'], path,
                                     os.path.join(dirs['outputs/caqe'], name + '.txt'), args.timeout)
            row += [c_val, f'{c_secs:.2f}']
            msg += f' | CAQE {c_val:7s} {c_secs:7.2f} s'
        print(msg, flush=True)
        rows.append(row)
        if d_val == 'true':
            protocols.append((name, decode(info, d_true)))

    with open(os.path.join(dirs['results'], 'results.md'), 'w', encoding='utf-8') as fh:
        fh.write('# Results (generated by run.py; do not edit by hand)\n\n')
        fh.write(f'- DepQBF: {depqbf_version}, options `--qdo --no-dynamic-nenofex`\n')
        fh.write(f'- CAQE: {caqe_version}, option `--qdo`\n' if caqe else '- CAQE: not run\n')
        fh.write(f'- Python {platform.python_version()} on {platform.platform()}, '
                 f'{os.cpu_count()} logical CPUs\n')
        fh.write(f'- Time limit: {"none" if args.timeout is None else f"{args.timeout:g} s"}; '
                 'times are wall-clock seconds\n\n')
        header = ['instance', 'input sequence', 'shuffles', 'security', 'variables', 'clauses',
                  'DepQBF', 'time (s)']
        if caqe:
            header += ['CAQE', 'time (s)']
        fh.write('| ' + ' | '.join(header) + ' |\n')
        fh.write('|' + '---|' * len(header) + '\n')
        for row in rows:
            fh.write('| ' + ' | '.join(row) + ' |\n')
        if protocols:
            fh.write('\n## Protocols read off from the true formulas (DepQBF)\n')
            for name, lines in protocols:
                fh.write(f'\n{name}:\n\n```\n' + '\n'.join(lines) + '\n```\n')
    print('wrote', os.path.relpath(os.path.join(dirs['results'], 'results.md'), os.getcwd()))


if __name__ == '__main__':
    main()
