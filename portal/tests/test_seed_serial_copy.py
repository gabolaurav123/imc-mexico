"""Exact installation-copy upgrades preserve staff edits and inactive pages."""
from io import StringIO
from django.core.management import call_command
from django.test import TestCase,override_settings
from portal.models import SiteContent

# Fixtures from the preceding release, independent of the current seed defaults.
OLD_INSTALLATION = {'como-funciona': ['De tus fotos a una ficha, en dos pasos', '01 · Sube tus fotos y prepara la ficha\nAgrega fotos o una captura y pulsa «Preparar mi ficha». La IA lee los datos visibles, busca especificaciones por número de serie o modelo y redacta la descripción con la información disponible. La placa ayuda, pero no es obligatoria.\n\n02 · Envía tu ficha a IMC México\nLa ficha queda preparada sin pedirte que llenes más campos. Puedes corregirla y añadir ubicación o precio si lo deseas. Los datos que no se encuentren quedan pendientes y no impiden enviar. Las referencias generales del modelo se identifican como tales. IMC México revisará la solicitud antes de cualquier publicación.'], 'privacidad': ['Aviso de privacidad · pendiente de validación', 'Documento de trabajo pendiente de validación jurídica y de identificación formal del responsable por IMC México. Esta plataforma utiliza los datos de cuenta y contacto para gestionar acceso, borradores, solicitudes y atención. Las fotografías se conservan privadas salvo autorización expresa de difusión. Al pulsar Preparar mi ficha, autorizas enviar las imágenes seleccionadas a OpenAI para identificar el equipo y redactar la ficha. La serie, marca y modelo identificados se utilizan en búsquedas web de referencias técnicas; las consultas no incluyen tu contacto ni la ubicación del equipo. Las series se conservan privadas en la ficha pública, aunque se comparten con el servicio de búsqueda para esta finalidad. Puedes solicitar acceso, corrección, exportación o eliminación de tus datos desde Perfil y seguridad. Las finalidades comerciales adicionales requieren consentimiento independiente. IMC debe completar responsable, domicilio, contacto de privacidad, transferencias, plazos y procedimientos aplicables antes de habilitar el registro público.']}

@override_settings(SECURE_SSL_REDIRECT=False,STORAGES={
    'default':{'BACKEND':'portal.storage.PrivateStorage'},
    'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class SerialCopySeedTests(TestCase):
    def seed(self):
        call_command('seed',stdout=StringIO())

    def test_exact_active_predecessors_upgrade_idempotently(self):
        rows={key:SiteContent.objects.create(key=key,title=old[0],body=old[1],active=True)
              for key,old in OLD_INSTALLATION.items()}
        self.seed()
        expected={}
        for key,row in rows.items():
            row.refresh_from_db()
            self.assertNotEqual(row.body,OLD_INSTALLATION[key][1])
            self.assertIn('sólo con fotos',row.body)
            self.assertIn('tipo de equipo',row.body)
            expected[key]=(row.title,row.body,row.active)
        self.seed()
        for key,row in rows.items():
            row.refresh_from_db()
            self.assertEqual((row.title,row.body,row.active),expected[key])
            self.assertEqual(SiteContent.objects.filter(key=key).count(),1)
        self.assertContains(self.client.get('/como-funciona/'),'puedes escribirla sin una foto de la placa')
        self.assertContains(self.client.get('/privacidad/'),'no incluyen tu contacto ni la ubicación')

    def test_custom_title_body_and_inactive_predecessors_remain_untouched(self):
        for key,(old_title,old_body) in OLD_INSTALLATION.items():
            for title,body,active in [(old_title+' · editado',old_body,True),
                                      (old_title,old_body+' ',True),
                                      (old_title,old_body,False)]:
                with self.subTest(key=key,active=active,title=title):
                    row,_=SiteContent.objects.update_or_create(key=key,defaults={'title':title,'body':body,'active':active})
                    self.seed();row.refresh_from_db()
                    self.assertEqual((row.title,row.body,row.active),(title,body,active))

    def test_new_installation_has_two_steps_and_explicit_search_privacy(self):
        self.seed()
        how=SiteContent.objects.get(key='como-funciona')
        self.assertIn('01 · Elige el tipo de máquina y aporta serie o fotos',how.body)
        self.assertIn('02 · Edita, comparte o envía tu ficha',how.body)
        self.assertNotIn('03 ·',how.body)
        self.assertIn('no identifican la unidad ni confirman sus especificaciones',how.body)
        privacy=SiteContent.objects.get(key='privacidad')
        self.assertIn('Puedes escribir la serie sin fotografiar la placa',privacy.body)
        self.assertIn('tipo de equipo cuando no haya identificadores fiables',privacy.body)
        self.assertIn('La serie escrita y el contacto permanecen privados salvo autorización expresa',privacy.body)
        self.assertIn('La descarga PDF está reservada al personal autorizado',privacy.body)
        self.assertIn('se comparten con el servicio de búsqueda',privacy.body)

    def test_fallback_pages_explain_photos_only_and_general_context(self):
        how=self.client.get('/como-funciona/')
        self.assertContains(how,'escribir la serie sin una foto de la placa')
        self.assertContains(how,'sólo con fotos')
        self.assertContains(how,'contexto general')
        privacy=self.client.get('/privacidad/')
        self.assertContains(privacy,'tipo de equipo cuando no haya identificadores fiables')
        self.assertContains(privacy,'no incluyen tus datos de contacto ni la ubicación')

    def test_public_templates_offer_written_serial_without_a_plate_photo(self):
        home=self.client.get('/')
        self.assertContains(home,'escríbela sin necesidad de una foto de la placa')
        self.assertContains(home,'contexto general, no especificaciones de tu unidad')
        guide=self.client.get('/guia-de-fotos/')
        self.assertContains(guide,'puedes escribirla sin fotografiar la placa')
