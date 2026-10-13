"""Rebuild the denormalized rollups of every counterparty relationship edge.

Rollups are normally refreshed by deal-stage transitions; run this after data migrations,
backfills, or whenever the numbers look stale:

    docker compose exec backend python manage.py recompute_relationship_rollups
    docker compose exec backend python manage.py recompute_relationship_rollups --company 42
"""

from django.core.management.base import BaseCommand

from crm.models import CounterpartyRelationship
from crm.services.relationships import recompute_rollups_for_edge


class Command(BaseCommand):
    help = "Rebuild deals_count/won_count/gmv on counterparty relationship edges"

    def add_arguments(self, parser):
        parser.add_argument("--company", type=int, default=None, help="Limit to edges owned by one company id")

    def handle(self, *args, **options):
        edges = CounterpartyRelationship.objects.all()
        if options["company"]:
            edges = edges.filter(owner_company_id=options["company"])
        count = 0
        for edge in edges.iterator():
            recompute_rollups_for_edge(edge)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Recomputed rollups for {count} edge(s)"))
