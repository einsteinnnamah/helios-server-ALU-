import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections, OperationalError
from helios.election_completion import process_next_completion


class Command(BaseCommand):
    help = 'Automatically count closed ALU elections and save a private Neon archive.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            try:
                worked = process_next_completion()
                if options['once']:
                    return
                if worked:
                    continue
            except OperationalError:
                self.stderr.write('Election completion database unavailable; retrying.')
                if options['once']:
                    raise
            time.sleep(5)
