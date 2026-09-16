"""Upgrade the shipped processing notice without rewriting staff content."""
from io import StringIO
from django.core.management import call_command
from django.test import TestCase
from portal.models import Machine,PlatformSettings,SiteContent

PREVIOUS_SHIPPED_DEFAULTS = {'como-funciona': ('De tus fotos a una ficha, en dos pasos', '01 · Sube tus fotos y prepara la ficha\nAgrega una fotografía general y pulsa «Preparar mi ficha». La IA completa los datos que puede identificar y propone una descripción. La placa es opcional y puedes continuar manualmente.\n\n02 · Revisa y envía a IMC México\nComprueba la ficha, indica la ubicación y corrige lo que necesites. El precio y los detalles técnicos son opcionales; los datos desconocidos pueden quedar vacíos. Envía tu solicitud cuando esté lista. IMC México revisa tu permiso de anunciante y el contenido antes de autorizar cualquier publicación.'), 'privacidad': ('Aviso de privacidad · pendiente de validación', 'Documento de trabajo pendiente de validación jurídica y de identificación formal del responsable por IMC México. Esta plataforma utiliza los datos de cuenta y contacto para gestionar acceso, borradores, solicitudes y atención. Las fotografías se conservan privadas salvo autorización expresa de difusión. El análisis asistido envía a OpenAI únicamente las imágenes seleccionadas con tu consentimiento. Puedes solicitar acceso, corrección, exportación o eliminación de tus datos desde Perfil y seguridad. Las finalidades comerciales adicionales requieren consentimiento independiente. IMC debe completar responsable, domicilio, contacto de privacidad, transferencias, plazos y procedimientos aplicables antes de habilitar el registro público.')}

class ResearchContentTests(TestCase):
    def seed(self):
        call_command('seed',stdout=StringIO())

    def test_previous_two_step_installation_gets_optional_fields_and_search_notice(self):
        for key,(title,body) in PREVIOUS_SHIPPED_DEFAULTS.items():
            SiteContent.objects.create(key=key,title=title,body=body,active=True)
        self.seed()
        how=SiteContent.objects.get(key='como-funciona')
        privacy=SiteContent.objects.get(key='privacidad')
        self.assertIn('busca especificaciones por número de serie o modelo',how.body)
        self.assertIn('sin pedirte que llenes más campos',how.body)
        self.assertNotIn('indica la ubicación',how.body)
        self.assertIn('se comparten con el servicio de búsqueda',privacy.body)
        self.assertFalse(PlatformSettings.load().legal_validated)
        self.assertFalse(Machine.objects.exists())
        before=list(SiteContent.objects.order_by('key').values('key','title','body','active'))
        self.seed()
        self.assertEqual(before,list(SiteContent.objects.order_by('key').values('key','title','body','active')))

    def test_staff_edits_and_disabled_notices_are_preserved(self):
        for key,(title,body) in PREVIOUS_SHIPPED_DEFAULTS.items():
            row,_=SiteContent.objects.get_or_create(key=key,defaults={'title':title,'body':body})
            for updated_title,updated_body,active in [(title+' personalizado',body,True),(title,body+' Nota propia.',True),(title,body,False)]:
                with self.subTest(key=key,active=active):
                    SiteContent.objects.filter(pk=row.pk).update(title=updated_title,body=updated_body,active=active)
                    self.seed()
                    row.refresh_from_db()
                    self.assertEqual((row.title,row.body,row.active),(updated_title,updated_body,active))
