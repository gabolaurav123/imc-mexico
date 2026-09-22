"""Refresh one editable draft from reviewed local references without provider calls."""
import hashlib
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from portal.knowledge import research_from_knowledge
from portal.market_catalogue import valuation_from_library
from portal.models import AnalysisJob, Consent, Machine
from portal.research import merge_research
from portal.valuation import _identity
from portal.services import apply_analysis_automatically, automatic_application_snapshot, audit


class Command(BaseCommand):
    help = "Previsualiza o aplica referencias revisadas a un borrador, sin IA ni proveedor."

    def add_arguments(self, parser):
        parser.add_argument("machine_uuid")
        parser.add_argument("--apply", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        try: machine = Machine.objects.select_related("owner", "category").get(pk=options["machine_uuid"])
        except (Machine.DoesNotExist, ValueError): raise CommandError("La maquinaria no está disponible.")
        if not machine.editable or not machine.category_id: raise CommandError("Sólo se puede reparar un borrador editable con categoría.")
        data, provenance = machine.data, machine.provenance
        identity = {}
        for key in ("brand", "model"):
            meta = provenance.get(key, {}) if isinstance(provenance, dict) else {}
            if data.get(key) and meta.get("source") in {"user", "plate", "image"} and meta.get("review") in {"confirmed", "clear"}: identity[key] = data[key]
        if len(identity) != 2: raise CommandError("Falta una identidad actual de marca y modelo confirmada por usuario o lectura clara.")
        snapshot = {"data": data, "provenance": provenance, "category": machine.category.name}
        result = {"data": {}, "provenance": {}, "fields": [], "warnings": [], "questions": []}
        research = research_from_knowledge(result, snapshot, machine.category, identity)
        if research: merge_research(result, research, snapshot)
        valuation = valuation_from_library(_identity({"data": data, "provenance": provenance}, snapshot), machine.category)
        if valuation:
            result["valuation"] = valuation
            for key, value in valuation.get("fields", {}).items():
                if value not in (None, ""): result["data"][key] = value; result["provenance"][key] = {"source":"valuation", "review":"needs_review", "component":"machine"}
        assets = [str(a.pk) for a in machine.assets.filter(kind="image", processing_status="ready").exclude(purpose="document")]
        result["input_snapshot"] = {"revision": machine.revision, "category_id": machine.category_id, "assets": assets,
                                    "data": data, "provenance": provenance}
        latest = machine.analysis_jobs.filter(status="completed").first()
        if latest and set(latest.asset_ids) == set(assets) and isinstance(latest.result.get("relevance"), dict): result["relevance"] = latest.result["relevance"]
        if valuation and valuation.get("status") == "estimated" and valuation.get("suggested_price"):
            result["data"]["estimate_suggested_price"] = valuation["suggested_price"]
            result["provenance"]["estimate_suggested_price"] = {"source":"valuation", "review":"needs_review", "component":"machine"}
        fields = sorted(result["data"])
        self.stdout.write(f"{machine.folio} candidatos={','.join(fields) or 'ninguno'} estado={'aplicar' if options['apply'] else 'simulación'}")
        if not options["apply"]: return
        consent = Consent.objects.filter(user=machine.owner, machine=machine, kind="ai").order_by("-created_at", "-pk").first()
        if not consent or not consent.granted:
            self.stdout.write(f"{machine.folio} aplicado=omitido consentimiento=no-vigente")
            return
        if (not assets or not latest or set(latest.asset_ids) != set(assets)
                or latest.result.get('relevance', {}).get('status') != 'relevant'
                or latest.result.get('blocking_reason')):
            self.stdout.write(f"{machine.folio} aplicado=omitido fotos=requieren-análisis")
            return
        fingerprint = hashlib.sha256(json.dumps([str(machine.pk), machine.revision, fields, timezone.now().isoformat()], sort_keys=True).encode()).hexdigest()
        job = AnalysisJob.objects.create(machine=machine, requested_by=machine.owner, revision=machine.revision, asset_ids=assets,
            fingerprint=fingerprint, status="completed", result=result, auto_apply=True, application_snapshot=automatic_application_snapshot(machine),
            model="reviewed-library", prompt_version="reviewed-library", finished_at=timezone.now())
        _machine, status = apply_analysis_automatically(machine, machine.owner, job, machine.revision)
        audit(machine.owner, "library_reference.refreshed", machine, {"job_id":str(job.pk), "status":status.get("status"), "fields":fields})
        self.stdout.write(f"{machine.folio} aplicado={status.get('status')} campos={','.join(status.get('applied_fields', [])) or 'ninguno'}")
