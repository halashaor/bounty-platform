"""Initialize, seed or back up the local SQLite database."""
import argparse
import os
import sqlite3
from pathlib import Path
from run import ROOT
from bounty.db import initialize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('BOUNTY_DATA_DIR', ROOT / 'instance')))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Create empty database tables')
    commands.add_parser('demo', help='Seed an empty database only')
    backup = commands.add_parser('backup', help='Consistent SQLite backup; refuses to overwrite')
    backup.add_argument('output', type=Path)
    args = parser.parse_args()
    data = args.data_dir.resolve()
    database = data / 'bounty.sqlite3'
    if args.command == 'backup':
        if not database.exists():
            parser.error('Database does not exist')
        output = args.output.resolve()
        if output.exists():
            parser.error('Backup output already exists; choose a new filename')
        output.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        destination = sqlite3.connect(output)
        try:
            source.backup(destination)
        finally:
            source.close()
            destination.close()
        print(f'Backup: {output}')
    else:
        data.mkdir(parents=True, exist_ok=True)
        initialize(database)
        if args.command == 'demo':
            from bounty.demo import seed_demo
            try:
                count = seed_demo(database)
            except ValueError as error:
                parser.error(str(error))
            print(f'Created {count} demo tasks. Password: demo12345')
        print(f'Database: {database}')


if __name__ == '__main__':
    main()
