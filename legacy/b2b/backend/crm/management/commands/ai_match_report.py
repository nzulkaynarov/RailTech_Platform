"""AI-match threshold calibration report (spec-remaining-2026-07-07, AI-калибровка).

Sweeps candidate thresholds over the RESOLVED AIMatchOutcome rows and prints precision/coverage
per threshold, so AI_DRAFT_MATCH_CONFIDENCE (env, no deploy needed) can be tuned on real traffic.

    docker compose exec backend python manage.py ai_match_report
    docker compose exec backend python manage.py ai_match_report --thresholds 0.7,0.8,0.9 --company 42

A row is "correct" when the seller's final line product equals the AI top candidate
(final_product == candidate_product). Per threshold t:
    would-bind  = rows with confidence >= t
    precision   = correct / would-bind        (how often a t-bind would have been right)
    coverage    = would-bind / all resolved   (how much manual matching a t-bind saves)
    missed      = correct rows below t        (right candidates the threshold left for manual work)
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from crm.models import AIMatchOutcome

DEFAULT_THRESHOLDS = "0.7,0.8,0.85,0.9,0.95"


class Command(BaseCommand):
    help = "Precision/coverage of the AI draft-КП auto-match per confidence threshold (AI-калибровка)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--thresholds",
            default=DEFAULT_THRESHOLDS,
            help=f"Comma-separated thresholds to sweep (default: {DEFAULT_THRESHOLDS})",
        )
        parser.add_argument("--company", type=int, default=None, help="Limit to one seller company id")

    def handle(self, *args, **options):
        try:
            thresholds = sorted({float(value) for value in options["thresholds"].split(",") if value.strip()})
        except ValueError as exc:
            raise CommandError(f"Bad --thresholds value: {exc}")
        if not thresholds or not all(0 < threshold <= 1 for threshold in thresholds):
            raise CommandError("Thresholds must be in (0, 1]")

        rows = AIMatchOutcome.objects.exclude(resolution=AIMatchOutcome.RESOLUTION_PENDING)
        if options["company"]:
            rows = rows.filter(seller_company_id=options["company"])
        resolved = list(rows.values("confidence", "candidate_product_id", "final_product_id"))
        pending_count = AIMatchOutcome.objects.filter(resolution=AIMatchOutcome.RESOLUTION_PENDING).count()

        current = float(getattr(settings, "AI_DRAFT_MATCH_CONFIDENCE", 0.9))
        self.stdout.write(f"Resolved outcomes: {len(resolved)} (pending, excluded: {pending_count})")
        self.stdout.write(f"Current AI_DRAFT_MATCH_CONFIDENCE: {current}")
        if not resolved:
            self.stdout.write(self.style.WARNING("No resolved telemetry yet — nothing to calibrate on."))
            return

        total = len(resolved)
        correct_total = sum(1 for row in resolved if self._is_correct(row))
        self.stdout.write(f"Top candidate was correct overall: {correct_total}/{total} ({correct_total / total:.1%})")
        self.stdout.write("")
        header = f"{'threshold':>9} | {'would-bind':>10} | {'precision':>9} | {'coverage':>8} | {'missed':>6}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for threshold in thresholds:
            bound = [row for row in resolved if float(row["confidence"]) >= threshold]
            bound_correct = sum(1 for row in bound if self._is_correct(row))
            missed = correct_total - bound_correct
            precision = bound_correct / len(bound) if bound else 0.0
            coverage = len(bound) / total
            marker = " ←" if abs(threshold - current) < 1e-9 else ""
            self.stdout.write(
                f"{threshold:>9.2f} | {len(bound):>10} | {precision:>9.1%} | {coverage:>8.1%} | {missed:>6}{marker}"
            )
        self.stdout.write("")
        self.stdout.write(
            "Pick the lowest threshold whose precision is still acceptable (auto-bind errors reach the "
            "client only if the seller misses them in review) — then set AI_DRAFT_MATCH_CONFIDENCE in .env."
        )

    @staticmethod
    def _is_correct(row: dict) -> bool:
        return row["candidate_product_id"] is not None and row["candidate_product_id"] == row["final_product_id"]
