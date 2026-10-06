from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings

from portal.models import SiteContent


PRE_GUEST_TRIAL_DEFAULTS = {
    "como-funciona": (
        "De tu máquina a una ficha compartible",
        "01 · Elige el tipo, la marca y el modelo\nCompleta tus datos de contacto y selecciona el tipo de máquina, la marca y el modelo en el catálogo. Si no encuentras el modelo o no lo conoces, continúa con el número de serie o fotografías. Esa selección sólo orienta el modelo: para generar la ficha agrega una fotografía de la máquina, una foto de su placa o escribe el número de serie. Una sola alternativa basta; las referencias del modelo son contexto general y no confirman las especificaciones de tu unidad.\n\n02 · Edita, comparte o envía tu ficha\nCon evidencia de tu unidad, el sistema puede consultar referencias y proponer el rango de año, el precio estimado y las características disponibles. La ficha queda preparada sin pedirte que llenes más campos técnicos; revisa y corrige los datos, añade horas y ubicación si los conoces. Comparte por enlace o envía a revisión cuando esté lista; IMC México autoriza por separado la publicación en el catálogo.",
    ),
    "preguntas-frecuentes": (
        "Preguntas frecuentes",
        "¿Qué necesito para generar la ficha? Selecciona el modelo si lo conoces y aporta al menos una fotografía de la máquina —puede ser de la placa— o escribe el número de serie. No se requieren ambas cosas. Puedes empezar sin conocer el año, precio u horas.\n\n¿La ficha se completa automáticamente? El catálogo orienta el modelo, pero no acredita datos de una unidad. Con tu foto o serie, el sistema consulta referencias y propone una ficha editable; puede sugerir rangos de año y precio cuando haya evidencia suficiente. No certifica el funcionamiento ni inventa especificaciones exactas.\n\n¿Puedo compartir antes de la aprobación? Sí. Como propietario de una ficha preparada, puedes habilitar un enlace corto para compartirla por WhatsApp, Facebook u otras aplicaciones, y desactivarlo después. Compartir no equivale a publicar en el catálogo de IMC México.\n\n¿Qué se ve en el enlace? Los datos completados y las fotografías de maquinaria admitidas para compartir. Las imágenes de placas y documentos permanecen privadas. La serie escrita y el contacto sólo aparecen si los autorizas expresamente. No se muestran notas internas ni campos vacíos.\n\n¿Puedo descargar un PDF? La descarga PDF está reservada al personal autorizado.\n\n¿Puedo regresar después? Sí. Los borradores guardados permanecen en tu panel.\n\n¿Enviar equivale a publicar? No. IMC México revisa la solicitud y autoriza por separado su publicación en el catálogo.",
    ),
}


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    "default": {"BACKEND": "portal.storage.PrivateStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class GuestSeedCopyTests(TestCase):
    def seed(self):
        call_command("seed", stdout=StringIO())

    def test_exact_pre_guest_defaults_upgrade_and_remain_idempotent(self):
        rows = {
            key: SiteContent.objects.create(key=key, title=title, body=body, active=True)
            for key, (title, body) in PRE_GUEST_TRIAL_DEFAULTS.items()
        }

        self.seed()
        for key, row in rows.items():
            row.refresh_from_db()
            self.assertNotEqual((row.title, row.body), PRE_GUEST_TRIAL_DEFAULTS[key])
            self.assertIn("sin cuenta", row.body)
            self.assertIn("24 horas", row.body)
            self.assertIn("cuenta", row.body)
        upgraded = {key: (row.title, row.body, row.active) for key, row in rows.items()}

        self.seed()
        for key, row in rows.items():
            row.refresh_from_db()
            self.assertEqual((row.title, row.body, row.active), upgraded[key])

    def test_staff_edit_is_not_replaced(self):
        title, body = PRE_GUEST_TRIAL_DEFAULTS["como-funciona"]
        page = SiteContent.objects.create(
            key="como-funciona", title=title + " · edición IMC", body=body, active=True,
        )

        self.seed()
        page.refresh_from_db()
        self.assertEqual((page.title, page.body), (title + " · edición IMC", body))

    def test_new_defaults_explain_trial_and_account_sharing(self):
        self.seed()
        how = SiteContent.objects.get(key="como-funciona")
        faq = SiteContent.objects.get(key="preguntas-frecuentes")
        self.assertIn("01 · Elige el tipo, la marca y el modelo", how.body)
        self.assertIn("crear una cuenta", how.body)
        self.assertIn("marca de prueba", how.body)
        self.assertIn("¿Puedo probar una ficha sin crear cuenta?", faq.body)
        self.assertIn("para compartirla o preparar más fichas debes crear una cuenta", faq.body)
