"""Upgrade untouched public copy without rewriting staff changes."""
from io import StringIO
from django.core.management import call_command
from django.test import TestCase, override_settings
from portal.models import SiteContent

PREVIOUS_DEFAULTS = {'como-funciona': ('De tus fotos a una ficha, en dos pasos', '01 · Sube tus fotos y prepara la ficha\nAgrega fotos o una captura. Si conoces la serie, puedes escribirla sin una foto de la placa; es opcional. Pulsa «Preparar mi ficha»: la IA utiliza las fotos y los identificadores disponibles para buscar referencias y preparar la descripción. Sin serie, puedes continuar sólo con fotos. Si no hay identificadores fiables, puede consultar referencias generales del tipo de equipo; no identifican la unidad ni confirman sus especificaciones.\n\n02 · Envía tu ficha a IMC México\nLa ficha queda preparada sin pedirte que llenes más campos. Puedes corregirla y añadir ubicación o precio si lo deseas. Los datos que no se encuentren no impiden enviar. Las referencias de modelo y las generales por tipo se distinguen de los datos de la unidad. IMC México revisará la solicitud antes de cualquier publicación.'), 'guia-de-fotos': ('Una buena ficha comienza con tus fotos', 'Fotografía la máquina completa con luz natural y desde varios ángulos. Incluye detalles de accesorios, desgaste y defectos conocidos. Si tienes una placa, toma la fotografía de frente y sin reflejos e indica si pertenece a la máquina, al motor u otro componente. No necesitas una placa para comenzar. No subas identificaciones personales ni documentos con datos sensibles salvo solicitud privada justificada.'), 'preguntas-frecuentes': ('Preguntas frecuentes', '¿Puedo empezar sin saber el año o la serie? Sí. Los datos desconocidos pueden dejarse vacíos.\n\n¿La IA certifica mi equipo? No. Organiza información visible y propone un borrador que debes revisar.\n\n¿Enviar equivale a publicar? No. IMC México revisa al anunciante y la solicitud; la difusión requiere una autorización separada.\n\n¿Puedo regresar después? Sí. Los borradores guardados permanecen en tu panel.\n\n¿Qué imágenes se publican? Sólo las autorizadas por IMC en la versión aprobada. Las placas y los documentos permanecen privados.'), 'privacidad': ('Aviso de privacidad · pendiente de validación', 'Documento de trabajo pendiente de validación jurídica y de identificación formal del responsable por IMC México. Esta plataforma utiliza los datos de cuenta y contacto para gestionar acceso, borradores, solicitudes y atención. Las fotografías se conservan privadas salvo autorización expresa de difusión. Al pulsar Preparar mi ficha, autorizas enviar las imágenes seleccionadas y los identificadores disponibles a OpenAI para preparar la ficha. Puedes escribir la serie sin fotografiar la placa o continuar sólo con fotos. La serie, la marca y el modelo aportados o identificados, y el tipo de equipo cuando no haya identificadores fiables, se utilizan en búsquedas web de referencias técnicas; las consultas no incluyen tu contacto ni la ubicación del equipo. Las series no aparecen en la ficha ni en el PDF públicos, aunque se comparten con el servicio de búsqueda para esta finalidad. Puedes solicitar acceso, corrección, exportación o eliminación de tus datos desde Perfil y seguridad. Las finalidades comerciales adicionales requieren consentimiento independiente. IMC debe completar responsable, domicilio, contacto de privacidad, transferencias, plazos y procedimientos aplicables antes de habilitar el registro público.'), 'terminos': ('Términos de uso · pendientes de validación', 'Documento de trabajo pendiente de validación jurídica por IMC México. El usuario declara contar con autorización para proporcionar información y fotografías de la maquinaria. Debe revisar y corregir los datos antes de enviar. Las sugerencias de IA y la revisión administrativa no certifican características, estado mecánico, propiedad ni documentación. Registrar una cuenta, obtener permiso de anunciante y aprobar una publicación son procesos distintos. El envío no implica publicación automática ni garantiza una venta. No se incluyen pagos, subastas, financiamiento ni suscripciones. IMC debe validar las condiciones definitivas y el mecanismo de atención antes de habilitar el registro público.')}


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'portal.storage.PrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class PreparedShareContentTests(TestCase):
    def seed(self):
        call_command('seed', stdout=StringIO())

    def test_shipped_defaults_upgrade_and_rerun_is_idempotent(self):
        for key, (title, body) in PREVIOUS_DEFAULTS.items():
            SiteContent.objects.create(key=key, title=title, body=body, active=True)
        self.seed()
        for key in ('como-funciona', 'preguntas-frecuentes', 'privacidad', 'terminos'):
            self.assertNotEqual(SiteContent.objects.get(key=key).body, PREVIOUS_DEFAULTS[key][1])
        before = list(SiteContent.objects.order_by('key').values('key', 'title', 'body', 'active'))
        self.seed()
        self.assertEqual(before, list(SiteContent.objects.order_by('key').values('key', 'title', 'body', 'active')))
        self.assert_copy_matches_flow()

    def test_custom_and_disabled_latest_defaults_remain_untouched(self):
        for key in ('como-funciona', 'preguntas-frecuentes', 'privacidad', 'terminos'):
            title, body = PREVIOUS_DEFAULTS[key]
            for custom_title, custom_body, active in (
                (title + ' personalizado', body, True),
                (title, body + ' Nota propia.', True),
                (title, body, False),
            ):
                with self.subTest(key=key, active=active):
                    row, _ = SiteContent.objects.update_or_create(key=key, defaults={
                        'title': custom_title, 'body': custom_body, 'active': active,
                    })
                    self.seed()
                    row.refresh_from_db()
                    self.assertEqual((row.title, row.body, row.active), (custom_title, custom_body, active))

    def assert_copy_matches_flow(self):
        faq = self.client.get('/preguntas-frecuentes/')
        self.assertContains(faq, 'antes de la aprobación')
        self.assertContains(faq, 'enlace corto')
        self.assertContains(faq, 'La descarga PDF está reservada al personal autorizado')
        self.assertContains(faq, 'serie escrita y el contacto')
        self.assertContains(faq, 'Las imágenes de placas')
        privacy = self.client.get('/privacidad/')
        self.assertContains(privacy, 'Generar ficha de maquinaria')
        self.assertContains(privacy, 'autorización expresa')
        self.assertNotContains(privacy, 'Las series no aparecen en la ficha ni en el PDF públicos')

    def test_fallback_pages_follow_same_sharing_contract(self):
        self.assert_copy_matches_flow()
        how = self.client.get('/como-funciona/')
        self.assertContains(how, 'serie o fotos')
        self.assertContains(how, 'Necesitamos serie o imágenes')
        self.assertContains(how, 'enlace corto')
        self.assertContains(how, 'autoriza por separado')

    def test_home_and_catalogue_distinguish_sharing_from_main_catalogue(self):
        home = self.client.get('/')
        self.assertContains(home, 'Tipo de máquina y serie o fotos')
        self.assertContains(home, 'Compartir tu ficha y publicarla en el catálogo son acciones distintas')
        self.assertNotContains(home, 'comparte la ficha virtual cuando esté aprobada')
        catalogue = self.client.get('/maquinaria/')
        self.assertContains(catalogue, 'como referencia')
        self.assertContains(catalogue, 'https://www.imcmexico.com.mx/catalogo-de-maquinaria')
