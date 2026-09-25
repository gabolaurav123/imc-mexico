from django.contrib import admin
from django.urls import path
from portal import views as v, auth_views as a, knowledge_views, guest
from portal.analytics import preferences as analytics_preferences
from portal import catalog_views
from portal import integration_views
from portal import machine_api
from portal import sharing

admin.site.site_header='IMC México · Administración'
admin.site.site_title='IMC México'
admin.site.index_title='Operación de la plataforma'
urlpatterns=[
 path('api/maquinarias/<uuid:pk>/compartir/',sharing.manage,name='prepared_share_manage'),
 path('s/<slug:code>/',sharing.sheet,name='prepared_share'),
 path('s/<slug:code>/archivo/<uuid:pk>/',sharing.asset,name='prepared_share_asset'),
 path('operaciones/integracion/',integration_views.integration_index,name='integration_index'),
 path('operaciones/integracion/<uuid:pk>/',integration_views.integration_detail,name='integration_detail'),
 path('panel/vinculos/imc/',integration_views.main_record_return,name='main_record_return'),
 path('administracion/',a.administration_sign_in,name='administration_login'),
 path('operaciones/notificaciones/nueva/',v.notification_compose,name='notification_compose'),
 path('panel/notificaciones/',v.notification_list,name='notification_list'),
 path('panel/notificaciones/resumen/',v.notification_summary,name='notification_summary'),
 path('panel/notificaciones/leer-todas/',v.notification_read_all,name='notification_read_all'),
 path('panel/notificaciones/<int:pk>/',v.notification_detail,name='notification_detail'),
 path('panel/notificaciones/<int:pk>/leer/',v.notification_read,name='notification_read'),
 path('preferencias/analitica/',analytics_preferences,name='analytics_preferences'),
 path('',v.home,name='home'),path('salud/',v.health,name='health'),path('maquinaria/',catalog_views.catalogue,name='catalogue'),
 path('publicar/',v.publish_start,name='publish_start'),path('invitados/<uuid:pk>/',guest.wizard,name='guest_wizard'),
 path('como-funciona/',v.public_page,{'slug':'como-funciona'}),path('guia-de-fotos/',v.public_page,{'slug':'guia-de-fotos'}),path('preguntas-frecuentes/',v.public_page,{'slug':'preguntas-frecuentes'}),path('privacidad/',v.public_page,{'slug':'privacidad'}),path('terminos/',v.public_page,{'slug':'terminos'}),path('ejemplo-de-ficha/',v.example,name='example'),path('contacto/',v.contact,name='contact'),
 path('registro/',a.register,name='register'),path('iniciar-sesion/',a.sign_in,name='login'),path('cerrar-sesion/',a.sign_out,name='logout'),path('recuperar-acceso/',a.recover,name='recover'),path('activar/<str:uidb64>/<str:token>/',a.activate,name='activate'),
 path('panel/',v.panel,name='panel'),path('panel/maquinarias/',v.machines,name='machines'),path('panel/maquinarias/nueva/',v.machine_create,name='machine_create'),path('panel/maquinarias/<uuid:pk>/',v.machine_wizard,name='machine_wizard'),path('panel/maquinarias/<uuid:pk>/ficha/',v.machine_sheet,name='machine_sheet'),path('panel/maquinarias/<uuid:pk>/pdf/',v.machine_pdf,name='machine_pdf'),path('panel/solicitudes/',v.requests_list,name='requests_list'),path('panel/mensajes/',v.messages_list,name='messages_list'),path('panel/perfil/',a.profile,name='profile'),path('panel/seguridad/',a.security,name='security'),
 path('api/maquinarias/',v.api_create),path('api/maquinarias/catalogo/',v.api_catalogue_intake,name='catalogue_intake_api'),path('api/maquinarias/<uuid:pk>/',machine_api.machine_detail,name='machine_api_detail'),path('api/maquinarias/<uuid:pk>/guardar/',v.api_save),path('api/maquinarias/<uuid:pk>/archivos/',v.api_upload),path('api/archivos/<uuid:pk>/accion/',v.api_asset_action),path('api/maquinarias/<uuid:pk>/analizar/',v.api_analyze),path('api/analisis/<uuid:pk>/',v.api_analysis),path('api/maquinarias/<uuid:pk>/aplicar/',v.api_apply),path('api/maquinarias/<uuid:pk>/enviar/',v.api_submit),path('api/maquinarias/<uuid:pk>/accion/',v.api_machine_action),
 path('api/invitados/',guest.start,name='guest_start'),path('api/invitados/<uuid:pk>/',guest.detail,name='guest_detail'),path('api/invitados/<uuid:pk>/guardar/',guest.save,name='guest_save'),path('api/invitados/<uuid:pk>/archivos/',guest.upload,name='guest_upload'),path('api/invitados/<uuid:pk>/archivos/<uuid:asset_pk>/',guest.asset,name='guest_asset'),path('api/invitados/<uuid:pk>/archivos/<uuid:asset_pk>/accion/',guest.asset_action,name='guest_asset_action'),path('api/invitados/<uuid:pk>/analizar/',guest.analyze,name='guest_analyze'),path('api/invitados/<uuid:pk>/analisis/<uuid:job_pk>/',guest.analysis,name='guest_analysis'),
 path('archivos/<uuid:pk>/',v.asset_download,name='asset_download'),path('ficha/<uuid:token>/',v.public_sheet,name='public_sheet'),path('ficha/<uuid:token>/archivo/<uuid:pk>/',v.public_asset,name='public_asset'),path('ficha/<uuid:token>/pdf/',v.public_pdf,name='public_pdf'),
 path('operaciones/',v.operations,name='operations'),path('operaciones/base-tecnica/',knowledge_views.technical_library,name='technical_library'),path('operaciones/base-tecnica/<int:pk>/',knowledge_views.technical_reference_detail,name='technical_reference_detail'),path('operaciones/solicitudes/<int:pk>/',v.review,name='review'),path('operaciones/maquinarias/<uuid:pk>/exportar/',v.export_machine,name='export_machine'),path('admin/',admin.site.urls),
]
