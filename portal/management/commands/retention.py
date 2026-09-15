"""Conservative retention: report by default; never delete machinery or media."""
from datetime import timedelta
from pathlib import Path
import json

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from portal.models import AnalysisJob,AnalyticsEvent,Asset,Notification,PlatformSettings,RateLimit
from portal.services import audit


class Command(BaseCommand):
    help="Reporta conservación. --apply purga sólo telemetría/sesiones vencidas y redacta enlaces de acceso vencidos; nunca medios ni maquinaria."

    def add_arguments(self,parser):
        parser.add_argument("--apply",action="store_true",help="Aplicar las expiraciones documentadas. Sin esta opción sólo informa.")
        parser.add_argument("--inspect-media",action="store_true",help="Contar archivos locales sin referencia; sólo diagnóstico, no los elimina.")

    def handle(self,*args,**options):
        now=timezone.now()
        platform=PlatformSettings.objects.filter(pk=1).first()
        retention_days=max(30,platform.retention_days if platform else 365)
        sessions=Session.objects.filter(expire_date__lt=now)
        rate_limits=RateLimit.objects.filter(window_start__lt=now-timedelta(days=31))
        analytics=AnalyticsEvent.objects.filter(created_at__lt=now-timedelta(days=retention_days))
        expired_hashes=AnalyticsEvent.objects.filter(created_at__lt=now-timedelta(minutes=30)).exclude(session_hash='')
        expired_contexts=AnalysisJob.objects.filter(analytics_context___expires_at__lte=now.timestamp())
        expired_auth=Notification.objects.filter(kind__in=["activation","admin_activation","verify","recovery"],created_at__lt=now-timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)).exclude(body="Enlace de acceso vencido. Contenido eliminado por política de conservación.")
        report={"mode":"apply" if options["apply"] else "report_only","retention_days":retention_days,
                "expired_sessions":sessions.count(),"rate_limits_older_31_days":rate_limits.count(),
                "expired_analytics":analytics.count(),"expired_auth_messages_to_redact":expired_auth.count(),
                "analytics_session_hashes_to_clear":expired_hashes.count(),"expired_analysis_contexts_to_clear":expired_contexts.count(),
                "media_deleted":0,"machines_deleted":0,"versions_deleted":0}
        if options["inspect_media"]:
            if getattr(settings,"PRIVATE_S3_BUCKET",""):
                report["orphan_inspection"]="No ejecutada: S3 requiere inventario del proveedor; no se enumeran ni eliminan objetos remotos."
            else:
                root=Path(settings.MEDIA_ROOT).resolve()
                referenced={name for row in Asset.objects.values_list("original","preview") for name in row if name}
                candidates=0
                if root.is_dir():
                    for path in root.rglob("*"):
                        if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root) and path.relative_to(root).as_posix() not in referenced:
                            candidates+=1
                report["local_unreferenced_files_candidates"]=candidates
                report["orphan_inspection"]="Sólo candidatos: comprobar backups y cargas concurrentes antes de cualquier intervención manual."
        if options["apply"]:
            with transaction.atomic():
                sessions.delete()
                rate_limits.delete()
                analytics.delete()
                expired_hashes.update(session_hash='')
                expired_contexts.update(analytics_context={})
                expired_auth.filter(status="pending").update(status="failed",error="El enlace venció antes de ser enviado. Solicita otro enlace.")
                expired_auth.update(body="Enlace de acceso vencido. Contenido eliminado por política de conservación.")
                if platform:
                    audit(None,"retention.expired_records",platform,{key:value for key,value in report.items() if key not in {"orphan_inspection"}})
        self.stdout.write(json.dumps(report,ensure_ascii=False,indent=2))
