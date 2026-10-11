"""Exact installation-copy upgrades preserve staff edits and inactive pages."""
from io import StringIO
from django.core.management import call_command
from django.test import TestCase,override_settings
from portal.models import SiteContent

# Fixtures from the preceding release, independent of the current seed defaults.
OLD_INSTALLATION = {'como-funciona': ['De tus fotos a una ficha, en dos pasos', '01 · Sube tus fotos y prepara la ficha\nAgrega fotos o una captura y pulsa «Preparar mi ficha». La IA lee los datos visibles, busca especificaciones por número de serie o modelo y redacta la descripción con la información disponible. La placa ayuda, pero no es obligatoria.\n\n02 · Envía tu ficha a IMC México\nLa ficha queda preparada sin pedirte que llenes más campos. Puedes corregirla y añadir ubicación o precio si lo deseas. Los datos que no se encuentren quedan pendientes y no impiden enviar. Las referencias generales del modelo se identifican como tales. IMC México revisará la solicitud antes de cualquier publicación.'], 'privacidad': ['Aviso de privacidad · pendiente de validación', 'Documento de trabajo pendiente de validación jurídica y de identificación formal del responsable por IMC México. Esta plataforma utiliza los datos de cuenta y contacto para gestionar acceso, borradores, solicitudes y atención. Las fotografías se conservan privadas salvo autorización expresa de difusión. Al pulsar Preparar mi ficha, autorizas enviar las imágenes seleccionadas a OpenAI para identificar el equipo y redactar la ficha. La serie, marca y modelo identificados se utilizan en búsquedas web de referencias técnicas; las consultas no incluyen tu contacto ni la ubicación del equipo. Las series se conservan privadas en la ficha pública, aunque se comparten con el servicio de búsqueda para esta finalidad. Puedes solicitar acceso, corrección, exportación o eliminación de tus datos desde Perfil y seguridad. Las finalidades comerciales adicionales requieren consentimiento independiente. IMC debe completar responsable, domicilio, contacto de privacidad, transferencias, plazos y procedimientos aplicables antes de habilitar el registro público.']}

# Shipped catalogue-first copy immediately before the evidence requirement.
# These literals deliberately do not import the seed implementation: this is a
# migration regression, not a self-fulfilling comparison.
CATALOGUE_FIRST_DEFAULTS = {
    'como-funciona': ('De tu máquina a una ficha compartible', '01 · Elige el tipo, la marca y el modelo\nCompleta tus datos de contacto y selecciona el tipo de máquina, la marca y el modelo en el catálogo. Pulsa «Generar ficha de maquinaria» para usar las referencias documentadas de ese modelo. Si no encuentras el modelo o no lo conoces, puedes continuar con el número de serie o fotografías; la foto de la placa es opcional. Las referencias del modelo son contexto general y no confirman las especificaciones de tu unidad.\n\n02 · Edita, comparte o envía tu ficha a IMC México\nLa ficha queda preparada sin pedirte que llenes más campos técnicos. Puedes corregirla, indicar un año o precio exacto y añadir horas y ubicación. Los datos sin valor no aparecen en la ficha compartida. Comparte la ficha web mediante un enlace corto que puedes desactivar; no necesitas que aparezca antes en el catálogo. La serie y el contacto se muestran sólo si lo autorizas expresamente al compartir. También puedes enviar la ficha a revisión: IMC México autoriza por separado su publicación en el catálogo.'),
    'preguntas-frecuentes': ('Preguntas frecuentes', '¿Cómo empiezo? Selecciona el tipo de máquina, la marca y el modelo del catálogo. Si no encuentras el modelo o no lo conoces, continúa con el número de serie o fotografías. La foto de la placa es opcional. Puedes empezar sin conocer el año, precio u horas.\n\n¿La ficha se completa automáticamente? El catálogo aporta referencias documentadas del modelo y el sistema puede consultar referencias para proponer una ficha editable. Puede sugerir rangos de año y precio cuando haya evidencia suficiente. No certifica el funcionamiento ni inventa especificaciones exactas. Puedes sustituir las propuestas por datos que conozcas.\n\n¿Puedo compartir antes de la aprobación? Sí. Como propietario de una ficha preparada, puedes habilitar un enlace corto para compartirla por WhatsApp, Facebook u otras aplicaciones, y desactivarlo después. Compartir no equivale a publicar en el catálogo de IMC México.\n\n¿Qué se ve en el enlace? Los datos completados y las fotografías de maquinaria admitidas para compartir. Las imágenes de placas y documentos permanecen privadas. La serie escrita y el contacto sólo aparecen si los autorizas expresamente. No se muestran notas internas ni campos vacíos.\n\n¿Puedo descargar un PDF? La ficha se consulta y comparte en la web. La descarga PDF está reservada al personal autorizado.\n\n¿Puedo regresar después? Sí. Los borradores guardados permanecen en tu panel. Si modificas una ficha compartida, vuelve a compartirla para actualizar el enlace.\n\n¿Enviar equivale a publicar? No. IMC México revisa la solicitud y autoriza por separado su publicación en el catálogo.'),
}

# Defaults shipped immediately before the type-only start screen.
TYPE_FIRST_DEFAULTS = {
    'como-funciona': ('De tu máquina a una ficha compartible', '01 · Elige el tipo, la marca y el modelo\nPuedes probar una ficha sin cuenta: selecciona el tipo de máquina y, si los conoces, la marca y el modelo en el catálogo. Si no encuentras el modelo o no lo conoces, continúa con el número de serie o fotografías. Esa selección sólo orienta el modelo: para generar la ficha agrega una fotografía de la máquina, una foto de su placa o escribe el número de serie. Una sola alternativa basta; las referencias del modelo sólo dan contexto y no confirman las especificaciones de tu unidad. La prueba privada incluye una preparación y conserva tu borrador durante 24 horas.\n\n02 · Edita, comparte o envía tu ficha\nAl compartir la ficha de prueba te pediremos crear una cuenta. Conservaremos las fotografías y datos que ya completaste; la ficha dejará de mostrar la marca de prueba y podrás preparar más publicaciones. Con evidencia de tu unidad, el sistema puede proponer el rango de año, el precio estimado y las características disponibles. Revisa y corrige los datos, añade horas y ubicación si los conoces. IMC México autoriza por separado la publicación en el catálogo.'),
    'preguntas-frecuentes': ('Preguntas frecuentes', '¿Puedo probar una ficha sin crear cuenta? Sí. Puedes preparar una ficha privada con una foto o serie. Incluye una preparación y se conserva durante 24 horas; para compartirla o preparar más fichas debes crear una cuenta.\n\n¿Qué necesito para generar la ficha? Selecciona el modelo si lo conoces y aporta al menos una fotografía de la máquina —puede ser de la placa— o escribe el número de serie. No se requieren ambas cosas. Puedes empezar sin conocer el año, precio u horas.\n\n¿La ficha se completa automáticamente? El catálogo orienta el modelo, pero no acredita datos de una unidad. Con tu foto o serie, el sistema consulta referencias y propone una ficha editable; puede sugerir rangos de año y precio cuando haya evidencia suficiente. No certifica el funcionamiento ni inventa especificaciones exactas.\n\n¿Puedo compartir antes de la aprobación? Sí, después de crear tu cuenta. Como propietario de una ficha preparada, puedes habilitar un enlace corto para compartirla por WhatsApp, Facebook u otras aplicaciones y desactivarlo después. Compartir no equivale a publicar en el catálogo de IMC México.\n\n¿Qué se ve en el enlace? Los datos completados y las fotografías de maquinaria admitidas para compartir. Las imágenes de placas y documentos permanecen privadas. La serie escrita y el contacto sólo aparecen si los autorizas expresamente. No se muestran notas internas ni campos vacíos.\n\n¿Puedo descargar un PDF? La descarga PDF está reservada al personal autorizado.\n\n¿Puedo regresar después? La prueba sin cuenta se conserva 24 horas. Al crear tu cuenta, el borrador pasa a tu panel y puedes continuar cuando quieras.\n\n¿Enviar equivale a publicar? No. IMC México revisa la solicitud y autoriza por separado su publicación en el catálogo.'),
}

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
            expected[key]=(row.title,row.body,row.active)
        self.assertIn('tipo de máquina',rows['como-funciona'].body)
        self.assertIn('aporta una foto o serie',rows['como-funciona'].body)
        self.assertIn('identificamos la marca y el modelo cuando sea posible',rows['como-funciona'].body)
        self.seed()
        for key,row in rows.items():
            row.refresh_from_db()
            self.assertEqual((row.title,row.body,row.active),expected[key])
            self.assertEqual(SiteContent.objects.filter(key=key).count(),1)
        self.assertContains(self.client.get('/como-funciona/'),'Con esa evidencia identificamos la marca y el modelo')
        self.assertContains(self.client.get('/privacidad/'),'no incluyen tu contacto ni la ubicación')

    def test_catalogue_first_defaults_migrate_but_staff_copy_is_preserved(self):
        rows = {key: SiteContent.objects.create(key=key, title=title, body=body, active=True)
                for key, (title, body) in CATALOGUE_FIRST_DEFAULTS.items()}
        self.seed()
        for key, row in rows.items():
            row.refresh_from_db()
            self.assertNotEqual((row.title, row.body), CATALOGUE_FIRST_DEFAULTS[key])
            if key == 'como-funciona':
                self.assertIn('No necesitas ambas cosas', row.body)
            else:
                self.assertIn('Elige el tipo de máquina', row.body)

        title, body = CATALOGUE_FIRST_DEFAULTS['como-funciona']
        edited = SiteContent.objects.get(key='como-funciona')
        edited.title, edited.body = title + ' · edición IMC', body
        edited.save(update_fields=['title', 'body'])
        self.seed()
        edited.refresh_from_db()
        self.assertEqual((edited.title, edited.body), (title + ' · edición IMC', body))

    def test_type_first_defaults_migrate_without_replacing_staff_or_inactive_copy(self):
        rows = {key: SiteContent.objects.create(key=key, title=title, body=body, active=True)
                for key, (title, body) in TYPE_FIRST_DEFAULTS.items()}
        self.seed()
        for key, row in rows.items():
            row.refresh_from_db()
            self.assertNotEqual((row.title, row.body), TYPE_FIRST_DEFAULTS[key])
            self.assertIn('foto o serie', row.body)
        title, body = TYPE_FIRST_DEFAULTS['como-funciona']
        edited = SiteContent.objects.get(key='como-funciona')
        edited.title, edited.body = title + ' · edición IMC', body
        edited.save(update_fields=['title', 'body'])
        self.seed()
        edited.refresh_from_db()
        self.assertEqual((edited.title, edited.body), (title + ' · edición IMC', body))
        faq_title, faq_body = TYPE_FIRST_DEFAULTS['preguntas-frecuentes']
        inactive = SiteContent.objects.get(key='preguntas-frecuentes')
        inactive.title, inactive.body, inactive.active = faq_title, faq_body, False
        inactive.save(update_fields=['title', 'body', 'active'])
        self.seed()
        inactive.refresh_from_db()
        self.assertEqual((inactive.title, inactive.body, inactive.active), (faq_title, faq_body, False))

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
        self.assertIn('01 · Elige el tipo y aporta una foto o serie',how.body)
        self.assertIn('02 · Edita, comparte o envía tu ficha',how.body)
        self.assertNotIn('03 ·',how.body)
        self.assertIn('identificamos la marca y el modelo cuando sea posible',how.body)
        privacy=SiteContent.objects.get(key='privacidad')
        self.assertIn('Puedes escribir la serie sin fotografiar la placa',privacy.body)
        self.assertIn('tipo de equipo cuando no haya identificadores fiables',privacy.body)
        self.assertIn('La serie escrita y el contacto permanecen privados salvo autorización expresa',privacy.body)
        self.assertIn('La descarga PDF está reservada al personal autorizado',privacy.body)
        self.assertIn('se comparten con el servicio de búsqueda',privacy.body)

    def test_fallback_pages_explain_photos_only_and_general_context(self):
        how=self.client.get('/como-funciona/')
        self.assertContains(how,'Selecciona el tipo de máquina y después sube una fotografía')
        self.assertContains(how,'identificamos la marca y el modelo cuando sea posible')
        self.assertContains(how,'Puedes probar una ficha sin cuenta')
        self.assertContains(how,'Al compartir la prueba te pediremos crear una cuenta')
        self.assertContains(how,'href="/publicar/">Comenzar con mis fotos')
        self.assertContains(how,'No necesitas ambas cosas')
        privacy=self.client.get('/privacidad/')
        self.assertContains(privacy,'tipo de equipo cuando no haya identificadores fiables')
        self.assertContains(privacy,'no incluyen tus datos de contacto ni la ubicación')

    def test_public_templates_offer_written_serial_without_a_plate_photo(self):
        home=self.client.get('/')
        self.assertContains(home,'La marca, el modelo y los demás datos se completan a partir de tu foto o serie')
        self.assertContains(home,'Empieza con una fotografía o el número de serie')
        self.assertContains(home,'Las estimaciones de cada equipo se calculan con la información y las referencias disponibles')
        guide=self.client.get('/guia-de-fotos/')
        self.assertContains(guide,'puedes escribirla sin fotografiar la placa')
