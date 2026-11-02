"""Compare existing child rows using generated SQL from Drizzle issue #6621."""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=Path(__file__).resolve().parents[2], type=Path,
                        help='Keepstep source checkout; no installation needed.')
    parser.add_argument('output', type=Path, help='New output directory.')
    args = parser.parse_args()
    package = args.source.resolve() / 'src'
    if not (package / 'schema_rehearsal' / '__main__.py').is_file():
        parser.error('--source must point to a Keepstep source checkout.')
    case = Path(__file__).resolve().parent
    input_names = ('initial.sql', 'seed.sql', 'old.sql', 'fixed.sql', 'unchanged.sql', 'suite.json')
    inputs = {name: sha256(case / name) for name in input_names}
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    database = output / 'before.sqlite'
    with closing(sqlite3.connect(database)) as connection:
        connection.execute('PRAGMA foreign_keys=ON')
        connection.executescript((case / 'initial.sql').read_text())
        connection.executescript((case / 'seed.sql').read_text())
    before_hash = sha256(database)
    results = {'python': sys.version, 'sqlite': sqlite3.sqlite_version,
               'input_sha256': inputs, 'database_sha256': before_hash, 'cases': {}}
    for name in ('old', 'fixed', 'unchanged'):
        migration = case / (name + '.sql')
        # Direct SQLite execution makes the fixture's hidden row values inspectable.
        with closing(sqlite3.connect(':memory:')) as direct:
            with closing(sqlite3.connect(database)) as source:
                source.backup(direct)
            direct.execute('PRAGMA foreign_keys=ON')
            direct.executescript(migration.read_text())
            observed = {
                'children': direct.execute('SELECT id,parent_id FROM children ORDER BY id').fetchall(),
                'parents': direct.execute('SELECT id FROM parents ORDER BY id').fetchall(),
                'unrelated': direct.execute('SELECT id FROM a_first ORDER BY id').fetchall(),
                'integrity_check': direct.execute('PRAGMA integrity_check').fetchall(),
                'foreign_key_check': direct.execute('PRAGMA foreign_key_check').fetchall(),
            }
        run = subprocess.run([
            sys.executable, '-m', 'schema_rehearsal', 'check',
            '--database', str(database), '--migration', str(migration),
            '--suite', str(case / 'suite.json'), '--output', str(output / name),
        ], cwd=output, env={**os.environ, 'PYTHONPATH': str(package)},
           capture_output=True, text=True, check=False)
        (output / (name + '-stdout.txt')).write_text(run.stdout)
        (output / (name + '-stderr.txt')).write_text(run.stderr)
        expected = 1 if name == 'old' else 0
        if run.returncode != expected:
            raise SystemExit(f'{name}: expected exit {expected}, got {run.returncode}; inspect saved logs.')
        report = json.loads((output / name / 'report.json').read_text())
        observations = report['scenarios'][0]['observations']
        if observations[0]['equal'] != (expected == 0) or not all(item['equal'] for item in observations[1:]):
            raise SystemExit(f'{name}: unexpected behavior comparison.')
        if not all(all(checks.values()) for checks in report['database_checks'].values()):
            raise SystemExit(f'{name}: unexpected database check failure.')
        if observed['parents'] != [(1,), (2,)] or observed['unrelated'] != [(1,)]:
            raise SystemExit(f'{name}: negative-control rows changed.')
        if observed['children'] != ([] if expected else [(1, 1), (2, 1), (3, 2)]):
            raise SystemExit(f'{name}: unexpected direct SQLite result.')
        if observed['integrity_check'] != [('ok',)] or observed['foreign_key_check']:
            raise SystemExit(f'{name}: direct SQLite checks did not pass.')
        results['cases'][name] = {'exit': run.returncode, 'status': report['status'],
                                 'database_checks': report['database_checks'], 'local_rows': observed}
        print(f'{name:9} exit {run.returncode}  child rows 3 -> {len(observed["children"])}')
    if sha256(database) != before_hash or inputs != {name: sha256(case / name) for name in input_names}:
        raise SystemExit('Input bytes changed.')
    results['source_and_inputs_unchanged'] = True
    (output / 'summary.json').write_text(json.dumps(results, indent=2) + '\n')
    print('All three runs passed integrity and foreign-key checks.')
    print('Source database and case input bytes unchanged.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError, IndexError) as error:
        print(f'Example could not finish: {error}', file=sys.stderr)
        raise SystemExit(2)
