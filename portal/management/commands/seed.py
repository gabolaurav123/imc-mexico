from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from portal.models import Category, PlatformSettings, SiteContent


class Command(BaseCommand):
    help = "Crea categorías, permisos y configuración inicial; nunca inventario ni credenciales."

    @transaction.atomic
    def handle(self, *args, **options):
        categories = {
            "excavadoras": ("Excavadoras", ["power", "weight", "capacity", "attachments"]),
            "retroexcavadoras": ("Retroexcavadoras", ["power", "weight", "attachments"]),
            "cargadores": ("Cargadores", ["power", "capacity", "weight"]),
            "tractores": ("Tractores", ["power", "weight", "fuel"]),
            "motoniveladoras": ("Motoniveladoras", ["power", "weight"]),
            "compactadores": ("Compactadores", ["weight", "power"]),
            "gruas": ("Grúas", ["capacity", "weight", "dimensions"]),
            "camiones": ("Camiones", ["kilometers", "capacity", "fuel", "transmission"]),
            "generadores": ("Generadores", ["power", "fuel", "engine"]),
            "motores": ("Motores", ["power", "fuel", "dimensions"]),
            "montacargas": ("Montacargas", ["capacity", "fuel", "weight"]),
            "otros": ("Otra maquinaria", []),
        }
        for slug, (name, fields) in categories.items():
            Category.objects.get_or_create(slug=slug, defaults={"name": name, "fields": fields})
        PlatformSettings.load()
        roles = {
            "Revisión IMC": {
                "view_user", "manage_advertisers", "operate_platform", "view_machine", "change_machine", "review_submission",
                "view_submission", "view_machineversion", "view_asset", "change_asset", "view_category", "view_consent",
                "view_message", "add_message", "view_analysisjob", "view_notification", "view_auditevent",
                "view_publication", "view_lead", "view_accountrequest",
            },
            "Publicación IMC": {
                "operate_platform", "view_machine", "view_machineversion", "view_asset", "view_publication", "change_publication", "publish_machine",
                "view_submission", "view_user", "view_category", "view_auditevent",
            },
            "Comercial IMC": {
                "operate_platform", "view_lead", "add_lead", "change_lead", "view_machine", "view_user", "view_message", "add_message",
                "view_publication", "view_accountrequest", "change_accountrequest",
            },
            "Contenido IMC": {"view_sitecontent", "add_sitecontent", "change_sitecontent", "view_category", "change_category"},
        }
        for role, codenames in roles.items():
            group, created = Group.objects.get_or_create(name=role)
            # Existing permissions are preserved: rerunning the seed cannot unexpectedly alter staff access.
            if created:
                group.permissions.set(Permission.objects.filter(content_type__app_label="portal", codename__in=codenames))
        pages = {
            "como-funciona": ("Tus fotos, una ficha más clara", "Sube una fotografía general de tu maquinaria. La placa ayuda, pero no es obligatoria. Revisa cada dato propuesto por la IA, completa la ubicación y envía tu solicitud. El equipo de IMC México revisa tu permiso de anunciante y el contenido antes de autorizar una publicación."),
            "guia-de-fotos": ("Una buena ficha comienza con tus fotos", "Fotografía la máquina completa con luz natural y desde varios ángulos. Incluye detalles de accesorios, desgaste y defectos conocidos. Si tienes una placa, toma la fotografía de frente y sin reflejos e indica si pertenece a la máquina, al motor u otro componente. No necesitas una placa para comenzar. No subas identificaciones personales ni documentos con datos sensibles salvo solicitud privada justificada."),
            "preguntas-frecuentes": ("Preguntas frecuentes", "¿Puedo empezar sin saber el año o la serie? Sí. Los datos desconocidos pueden dejarse vacíos.\n\n¿La IA certifica mi equipo? No. Organiza información visible y propone un borrador que debes revisar.\n\n¿Enviar equivale a publicar? No. IMC México revisa al anunciante y la solicitud; la difusión requiere una autorización separada.\n\n¿Puedo regresar después? Sí. Los borradores guardados permanecen en tu panel.\n\n¿Qué imágenes se publican? Sólo las autorizadas por IMC en la versión aprobada. Las placas y los documentos permanecen privados."),
            "privacidad": ("Aviso de privacidad · pendiente de validación", "Documento de trabajo pendiente de validación jurídica y de identificación formal del responsable por IMC México. Esta plataforma utiliza los datos de cuenta y contacto para gestionar acceso, borradores, solicitudes y atención. Las fotografías se conservan privadas salvo autorización expresa de difusión. El análisis asistido envía a OpenAI únicamente las imágenes seleccionadas con tu consentimiento. Puedes solicitar acceso, corrección, exportación o eliminación de tus datos desde Perfil y seguridad. Las finalidades comerciales adicionales requieren consentimiento independiente. IMC debe completar responsable, domicilio, contacto de privacidad, transferencias, plazos y procedimientos aplicables antes de habilitar el registro público."),
            "terminos": ("Términos de uso · pendientes de validación", "Documento de trabajo pendiente de validación jurídica por IMC México. El usuario declara contar con autorización para proporcionar información y fotografías de la maquinaria. Debe revisar y corregir los datos antes de enviar. Las sugerencias de IA y la revisión administrativa no certifican características, estado mecánico, propiedad ni documentación. Registrar una cuenta, obtener permiso de anunciante y aprobar una publicación son procesos distintos. El envío no implica publicación automática ni garantiza una venta. No se incluyen pagos, subastas, financiamiento ni suscripciones. IMC debe validar las condiciones definitivas y el mecanismo de atención antes de habilitar el registro público."),
        }
        for key, (title, body) in pages.items():
            SiteContent.objects.get_or_create(key=key, defaults={"title": title, "body": body})
        self.stdout.write(self.style.SUCCESS("Datos iniciales creados sin modificar contenidos ni permisos existentes."))
