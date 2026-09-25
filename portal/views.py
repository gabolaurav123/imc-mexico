import copy
import json
import re
from urllib.parse import urlencode
from functools import wraps
from datetime import timedelta
from django.conf import settings
from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum, F
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from .models import *
from .forms import ContactForm
from .security import operator_required, staff_authorized, throttle, is_management_user, login_destination
from . import services
from .analytics import capture_context,record_event
from .backup_status import get_backup_status

def owned(request,pk):
    query=Machine.objects.select_related('owner','category','approved_version')
    if not (staff_authorized(request.user) and request.user.has_perm('portal.view_machine')):query=query.filter(owner=request.user)
    return get_object_or_404(query,pk=pk)


def can_export_machine(request):
    """Template hint only; export views enforce the same rule server-side."""
    return bool(request.user.is_authenticated and request.user.is_staff
                and request.user.has_perm('portal.publish_machine')
                and (not settings.STAFF_MFA_REQUIRED or request.user.is_verified()))

def payload(request,allowed=None):
    try:
        value=json.loads(request.body or '{}')
        if not isinstance(value,dict):raise ValueError
        if allowed is not None and set(value)-set(allowed):raise ValidationError('La solicitud contiene campos no permitidos.')
        return value
    except (ValueError,UnicodeDecodeError):raise ValidationError('El contenido de la solicitud no es válido.')

def api(fn):
    @wraps(fn)
    def wrapper(request,*args,**kwargs):
        if not request.user.is_authenticated:return JsonResponse({'error':'Inicia sesión para continuar.'},status=401)
        try:return fn(request,*args,**kwargs)
        except services.DraftRevisionConflict as exc:return JsonResponse({'error':' '.join(exc.messages)},status=409)
        except ValidationError as exc:return JsonResponse({'error':' '.join(exc.messages)},status=400)
        except (ValueError,TypeError,KeyError):return JsonResponse({'error':'Revisa los datos enviados.'},status=400)
        except PermissionDenied:return JsonResponse({'error':'No tienes permiso para realizar esta acción.'},status=403)
        except (Http404,Machine.DoesNotExist):return JsonResponse({'error':'El registro no está disponible.'},status=404)
    return wrapper

def event(request,name,machine=None):
    record_event(request,name,machine,page='wizard')

def home(request):
    content=SiteContent.objects.filter(key='home-hero',active=True).first()
    return render(request,'portal/home.html',{'home_content':content})

@require_http_methods(["GET", "POST"])
def publish_start(request):
    # Existing temporary drafts retain their session capability and claim
    # route, while new publication starts with the user's contact account.
    if not request.user.is_authenticated:
        return redirect('/registro/?next=/panel/maquinarias/nueva/')
    return redirect('machine_create')

PAGES={
 'como-funciona': ('Tu máquina, una ficha compartible', 'Elige el tipo de máquina y aporta serie o fotos.', [('01 · Tipo de máquina, serie o fotos', 'Completa tu contacto y selecciona el tipo de máquina en el buscador. Te preguntamos si tienes serie: puedes escribir la serie sin una foto de la placa o continuar sólo con fotos. Necesitamos serie o imágenes para generar la ficha. Pulsa Generar ficha de maquinaria: se consultan referencias para proponer identificación, descripción y estimaciones de año y valor cuando haya evidencia suficiente. Las referencias sin identificadores fiables son contexto general; no confirman especificaciones de tu unidad.'), ('02 · Edita y comparte tu ficha', 'Corrige cualquier propuesta o indica año y precio exactos, horas o ubicación. Los datos sin valor no aparecen en la ficha compartida. Puedes habilitar un enlace corto y desactivarlo después. La serie y el contacto sólo se incluyen con autorización expresa. También puedes enviar la ficha a revisión; IMC México autoriza por separado su publicación en el catálogo.')]),
 'guia-de-fotos': ('Una buena foto ayuda mucho', 'No necesitas equipo profesional: basta con tu celular y buena luz.', [('Vista general', 'Fotografía la máquina completa de costado. Evita personas y documentos ajenos en el encuadre.'), ('Detalles que importan', 'Incluye accesorios, puntos de desgaste y defectos visibles, sin ocultarlos ni alterar las imágenes.'), ('Placa, si la tienes', 'Acércate hasta que se lean los caracteres, evita reflejos y toma la imagen de frente. Indica si pertenece al motor, a la máquina o a otro componente.'), ('Sin placa también puedes empezar', 'Puedes escribir la serie sin fotografiar la placa o continuar sólo con una fotografía útil. No inventes series, año u horas si los desconoces.'), ('Video opcional', 'Un recorrido breve puede complementar las fotografías. El análisis de video mediante IA está desactivado.')]),
 'preguntas-frecuentes': ('Resolvemos tus dudas', 'Lo esencial antes de anunciar tu maquinaria.', [('¿Necesito la placa?', 'No. Selecciona el tipo de máquina y escribe su número de serie o sube fotografías. La foto de la placa es opcional.'), ('¿La ficha se completa automáticamente?', 'Se identifican datos y se consultan referencias para proponer una ficha editable, incluidos rangos de año y precio cuando haya evidencia suficiente. Puedes sustituirlos por datos exactos. No se certifican características ni funcionamiento.'), ('¿Puedo compartir antes de la aprobación?', 'Sí. El propietario puede habilitar un enlace corto de su ficha preparada y desactivarlo después. Se comparte por WhatsApp, Facebook u otras aplicaciones. No equivale a publicar en el catálogo de IMC México.'), ('¿Qué se ve al compartir?', 'Los datos completados y las fotografías de maquinaria admitidas para compartir. Las imágenes de placas, documentos y notas internas permanecen privadas. La serie escrita y el contacto sólo aparecen con autorización expresa.'), ('¿Puedo descargar un PDF?', 'La ficha se consulta y comparte en la web. La descarga PDF está reservada al personal autorizado.'), ('¿Puedo continuar más tarde?', 'Sí. El borrador se guarda en tu cuenta. Si editas una ficha compartida, vuelve a compartirla para actualizar el enlace.'), ('¿Se publica al enviar?', 'No. IMC México revisa la solicitud y autoriza por separado su publicación en el catálogo.')]),
 'privacidad': ('Aviso de privacidad', 'Documento operativo pendiente de validación por el responsable de IMC México.', [('Finalidad', 'Tratamos los datos de cuenta, contacto, archivos y maquinaria para preparar fichas, revisar solicitudes y dar seguimiento. Las comunicaciones comerciales requieren consentimiento separado.'), ('Procesamiento con OpenAI', 'Al pulsar Generar ficha de maquinaria, autorizas enviar a OpenAI las imágenes necesarias y los identificadores disponibles para preparar la ficha. Puedes escribir la serie sin fotografiar la placa o continuar sólo con fotos. El número de serie, la marca y el modelo aportados o identificados, o el tipo de equipo cuando no haya identificadores fiables, se utilizan para búsquedas web de referencias técnicas. Las series se comparten con el buscador para esta finalidad y permanecen privadas en la ficha salvo autorización expresa al compartir. Las consultas de búsqueda no incluyen tus datos de contacto ni la ubicación del equipo. No enviamos intencionalmente tu correo ni teléfono. Evita documentos personales en las imágenes. store:false evita almacenar una respuesta como recurso recuperable, pero no garantiza ausencia absoluta de retención: aplican los controles y excepciones del proveedor.'), ('Acceso y publicación', 'Tus borradores y originales son privados. Como propietario puedes habilitar y desactivar un enlace de tu ficha preparada: será accesible a quienes tengan el enlace con los datos completados y las fotografías de maquinaria admitidas para compartir. La serie escrita y el contacto sólo se incluyen con autorización expresa e independiente. Las imágenes de placas, documentos y notas internas permanecen privadas. Compartir no autoriza la publicación en el catálogo de IMC México, que requiere revisión y permisos separados. La descarga PDF está reservada al personal autorizado.'), ('Conservación y derechos', 'Puedes solicitar acceso, corrección o eliminación en Panel → Seguridad. El responsable resolverá la solicitud y las obligaciones de conservación aplicables. La política inicial propone revisar datos inactivos tras 365 días; no elimina publicaciones activas automáticamente.'), ('Responsable y contacto', 'Los datos legales del responsable, domicilio, transferencias, plazos y procedimiento definitivo deben ser validados por IMC México antes de apertura comercial. No se declara cumplimiento legal automático.')]),
 'terminos': ('Términos de uso', 'Borrador pendiente de validación por el responsable de IMC México.', [('Objeto del portal', 'Esta plataforma recibe información de maquinaria, ayuda a organizarla y la somete a revisión. No es un sistema de pagos, subastas, financiamiento ni una garantía de venta.'), ('Tu información', 'Declara únicamente datos que conozcas y señala defectos o limitaciones. Debes contar con autorización para anunciar el equipo y compartir las imágenes suministradas.'), ('Revisión y permisos', 'La revisión administrativa no implica inspección ni certificación mecánica. El propietario puede habilitar y desactivar un enlace de su ficha preparada. IMC México decide por separado el permiso de anunciante, la aprobación del contenido y la publicación en el catálogo.'), ('Asistencia mediante IA', 'Las sugerencias pueden contener errores. Debes revisarlas antes de enviar. Los datos desconocidos permanecen sin especificar y pueden solicitarse aclaraciones.'), ('Cambios y disponibilidad', 'Las modificaciones relevantes requieren una nueva revisión. Informa si el equipo se reserva, vende o retira. Compartir el enlace no acredita publicación en la web principal.')]),
}

def public_page(request,slug):
    if slug not in PAGES:raise Http404
    title,intro,sections=PAGES[slug]
    if slug=='privacidad':
        sections=[*sections,('Analítica opcional','La analítica está desactivada inicialmente. Si se habilita, puedes permitirla o rechazarla desde el pie de página. La elección es independiente de los mensajes comerciales. Se cuentan pasos del portal, el tipo general de dispositivo y etiquetas de campaña limitadas; no se guardan IP, direcciones completas, datos de contacto ni identificadores de cuenta o maquinaria en estos eventos. Con aceptación se usa una huella aleatoria de navegador durante 30 minutos, sin relacionar dispositivos. La preferencia se conserva hasta 180 días. Si el responsable configura contadores sin consentimiento, estos no llevan cookies ni huella de sesión; tu rechazo también los detiene. Retirar la aceptación elimina la huella de la sesión actual. Los eventos agregados se conservan según la política indicada; no se convierten en contactos comerciales.')]
    content=SiteContent.objects.filter(key=slug,active=True).first()
    if content:title=content.title or title;sections=[('',content.body)]
    if slug=='privacidad':
        sections=[*sections,('Seguridad de cuentas y accesos','Al iniciar sesión se registra la cuenta, fecha, tipo general de dispositivo e IP de conexión. También se conserva, separada y como dato no verificado, la IP declarada por la cabecera de red. Se registra una muestra periódica de actividad de sesiones existentes y la verificación del segundo factor. Este historial privado sirve para revisar accesos y atender incidencias; sólo puede consultarlo el personal con permiso específico. No incluye contraseñas, códigos temporales, contenido de formularios ni ubicación física. Los registros caducan a los 90 días y se eliminan en la limpieza periódica del servicio. Es independiente de la analítica opcional de visitas.')]
    return render(request,'portal/page.html',{'title':title,'intro':intro,'sections':[{'title':a,'body':b} for a,b in sections],'slug':slug})

def example(request):
    return render(request,'portal/example.html')

def contact(request):
    linked_machine=None
    linked_title=''
    share_code=request.POST.get('share','') if request.method=='POST' else request.GET.get('share','')
    machine_id=request.POST.get('machine') if request.method=='POST' else request.GET.get('maquinaria')
    if machine_id:
        try:linked_machine=Machine.objects.select_related('owner','approved_version').get(pk=machine_id)
        except (Machine.DoesNotExist,ValidationError,ValueError):raise Http404
        private_access=request.user.is_authenticated and (linked_machine.owner_id==request.user.pk or (staff_authorized(request.user) and request.user.has_perm('portal.view_machine')))
        public_access=linked_machine.approved_version_id and linked_machine.owner.advertiser_status=='approved' and linked_machine.availability!='withdrawn' and linked_machine.publications.filter(destination='share',enabled=True,status='published',version_id=linked_machine.approved_version_id).exists()
        prepared=None
        if share_code:
            from .sharing import record
            prepared=record(share_code)
            if prepared.machine_id != linked_machine.pk:raise Http404
            public_access=True
        if not private_access and not public_access:raise Http404
        linked_title=(linked_machine.title if private_access else prepared.snapshot.get('title','Maquinaria')
            if prepared else linked_machine.approved_version.data.get('title','Maquinaria'))
    form=ContactForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if not throttle(request,'contact',5,3600):form.add_error(None,'Has enviado varias consultas. Espera un momento antes de intentar de nuevo.')
        else:
            lead=form.save(commit=False)
            lead.machine=linked_machine
            if request.user.is_authenticated:lead.user=request.user;lead.is_test=request.user.is_test
            lead.save()
            flash.success(request,'Recibimos tu consulta. Quedó registrada para seguimiento del equipo.')
            return redirect('/contacto/?enviado=1')
    return render(request,'portal/contact.html',{'form':form,'contact_machine':linked_machine,'contact_machine_title':linked_title,'share_code':share_code})

@login_required
def panel(request):
    if is_management_user(request.user) and request.GET.get('modo')!='anunciante':
        return redirect(login_destination(request))
    qs=request.user.machines.all()
    counts={'total':qs.count(),'drafts':qs.filter(status='draft').count(),'pending':qs.filter(status__in=['submitted','in_review']).count(),'approved':qs.filter(approved_version__isnull=False).count(),'corrections':qs.filter(status='changes_requested').count()}
    return render(request,'portal/dashboard.html',{'machines':qs.prefetch_related('assets')[:6],'counts':counts,'recent_messages':Message.objects.filter(machine__owner=request.user,machine__deleted_at__isnull=True,internal=False).select_related('machine','sender').order_by('-created_at','-pk')[:5]})

@login_required
def machines(request):
    is_trash=request.GET.get('papelera')=='1'
    trash=Machine.all_objects.filter(owner=request.user,deleted_at__isnull=False)
    qs=(trash if is_trash else request.user.machines.all()).prefetch_related('assets','publications')
    q=request.GET.get('q','')[:100]
    if q:
        folio_query=q.removeprefix('IMC-').removeprefix('imc-').replace('-','')
        qs=qs.filter(Q(title__icontains=q)|Q(data__icontains=q)|Q(id__istartswith=folio_query))
    state=request.GET.get('status',request.GET.get('estado',''))
    if state:qs=qs.filter(status=state)
    page=Paginator(qs,12).get_page(request.GET.get('page'))
    return render(request,'portal/machines.html',{'machines':page,'page_obj':page,'q':q,'is_trash':is_trash,'trash_count':trash.count()})

@login_required
def machine_create(request):
    from .category_profiles import category_catalog
    from .intake import contact_complete
    from .catalogue_intake import catalogue_choices, catalogue_proposal
    if not contact_complete(request.user):
        return redirect('/panel/perfil/?next=/panel/maquinarias/nueva/')
    categories = Category.objects.filter(active=True)
    if request.method=='POST':
        category_id=request.POST.get('category')
        serial=request.POST.get('serial','').strip()[:150]
        declared={key:request.POST.get(key,'').strip()[:limit] for key,limit in
                  {'brand':100,'model':100,'description':10000}.items()}
        category=None
        if category_id in (None, '', 'unsure'):
            return render(request,'portal/start.html',{'categories_json':category_catalog(categories),
                'catalogue_intake_json':catalogue_choices(categories),
                'error':'Selecciona el tipo de máquina que quieres anunciar.'},status=400)
        if category_id not in (None, '', 'unsure'):
            try:
                category=categories.get(pk=category_id)
            except (Category.DoesNotExist, ValueError, TypeError):
                return render(request,'portal/start.html',{'categories_json':category_catalog(categories),
                    'catalogue_intake_json':catalogue_choices(categories),
                    'error':'Selecciona un tipo disponible o «No estoy seguro».'},status=400)
        entry_mode=request.POST.get('entry_mode','')
        provenance={'currency':{'source':'system','review':'needs_review'}}
        if category:provenance['category']={'source':'user','review':'confirmed'}
        data={'currency':'USD'}
        title=None
        if entry_mode=='catalogue':
            proposal=catalogue_proposal(category.pk,request.POST.get('catalogue_model'))
            data,provenance=proposal['data'],{**proposal['provenance'],
                'title':proposal['title_provenance'],
                'category':{'source':'user','review':'confirmed'}}
            title=proposal['title']
        elif entry_mode=='manual_identity':
            brand=request.POST.get('catalogue_manual_brand','').strip()[:100]
            model=request.POST.get('catalogue_manual_model','').strip()[:100]
            if not brand or not model:
                return render(request,'portal/start.html',{'categories_json':category_catalog(categories),
                    'catalogue_intake_json':catalogue_choices(categories),
                    'error':'Escribe la marca y el modelo, o selecciona un modelo del catálogo.'},status=400)
            data.update({'brand':brand,'model':model})
            provenance.update({'brand':{'source':'user','review':'confirmed'},
                               'model':{'source':'user','review':'confirmed'}})
        if serial: provenance['serial']={'source':'user','review':'confirmed'}
        if serial:data['serial']=serial
        for key,value in declared.items():
            if value:
                data[key]=value
                provenance[key]={'source':'user','review':'confirmed'}
        machine=Machine.objects.create(owner=request.user,category=category,data=data,
            provenance=provenance,**({'title':title} if title else {}))
        event(request,'draft_started',machine)
        suffix=('?entrada=catalogue&paso=2' if entry_mode=='catalogue' else
                '?entrada='+entry_mode if entry_mode in {'plate','serial','photos','manual_identity'} else '')
        return redirect(f'/panel/maquinarias/{machine.pk}/'+suffix)
    return render(request,'portal/start.html',{'categories_json':category_catalog(categories),
        'catalogue_intake_json':catalogue_choices(categories)})


@require_http_methods(["GET", "POST"])
@api
def api_catalogue_intake(request):
    """Read approved local models or create the explicit no-media catalogue draft."""
    from .catalogue_intake import catalogue_choices, catalogue_proposal
    from .intake import contact_complete
    if request.method=='GET':
        category=request.GET.get('category')
        categories=Category.objects.filter(active=True)
        if category:
            try:categories=categories.filter(pk=int(category))
            except (TypeError,ValueError):raise ValidationError('Selecciona un tipo de máquina disponible.')
        return JsonResponse({'models':catalogue_choices(categories)})
    if not contact_complete(request.user):
        return JsonResponse({'error':'Completa tus datos de contacto antes de publicar.',
                             'url':'/panel/perfil/?next=/panel/maquinarias/nueva/'},status=400)
    body=payload(request,allowed=['category','model_id'])
    proposal=catalogue_proposal(body.get('category'),body.get('model_id'))
    machine=Machine.objects.create(owner=request.user,category=proposal['category'],title=proposal['title'],data=proposal['data'],
        provenance={**proposal['provenance'],'title':proposal['title_provenance'],
                    'category':{'source':'user','review':'confirmed'}})
    event(request,'draft_started',machine)
    return JsonResponse({'id':str(machine.pk),'url':f'/panel/maquinarias/{machine.pk}/?entrada=catalogue&paso=2',
                         'mode':'catalogue','reference_count':proposal['reference_count']},status=201)

@login_required
@ensure_csrf_cookie
def machine_wizard(request,pk):
    from .category_profiles import category_catalog
    machine=owned(request,pk)
    try:step=max(1,min(2,int(request.GET.get('paso',request.GET.get('step',1)))))
    except ValueError:step=1
    job=AnalysisJob.objects.filter(machine=machine).order_by('-created_at').first()
    models=EquipmentModel.objects.filter(active=True,brand__active=True).filter(Q(category__isnull=True)|Q(category__active=True)).select_related('brand')
    catalog_models=[{'name':item.name,'brand':item.brand.name,'category':item.category_id} for item in models]
    shared=PreparedShare.objects.filter(machine=machine,authorized_by_id=machine.owner_id).first()
    share_context={'share_include_serial':bool(shared and shared.include_serial),
        'share_include_contact':bool(shared and shared.snapshot.get('contact_authorized'))}
    return render(request,'portal/wizard.html',{**share_context,'machine':machine,'can_delete_draft':machine.owner_id==request.user.pk and machine.can_delete_draft,'can_export':can_export_machine(request),'assets':machine.assets.all(),'categories':Category.objects.filter(active=True),'categories_json':category_catalog(Category.objects.filter(active=True)),'catalog_brands':Brand.objects.filter(active=True),'catalog_models_json':catalog_models,'step':step,'job':job,'data':machine.data,'provenance':machine.provenance,'machine_json':machine_state(machine)})

@login_required
def requests_list(request):
    return render(request,'portal/requests.html',{'submissions':Paginator(Submission.objects.filter(machine__owner=request.user,machine__deleted_at__isnull=True).select_related('machine','version'),20).get_page(request.GET.get('page'))})

@login_required
def messages_list(request):
    if request.method=='POST':
        machine=owned(request,request.POST.get('machine'))
        body=request.POST.get('body','').strip()
        if body and len(body)<=5000 and throttle(request,'messages',30,3600,str(request.user.pk)):
            message=Message.objects.create(machine=machine,sender=request.user,body=body,internal=False)
            services.audit(request.user,'message.sent',message)
            flash.success(request,'Mensaje guardado para el equipo de IMC México.')
            return redirect('/panel/mensajes/')
        flash.error(request,'Escribe un mensaje de hasta 5 000 caracteres.')
    qs=Message.objects.filter(machine__owner=request.user,machine__deleted_at__isnull=True,internal=False).select_related('machine','sender')
    selected=request.GET.get('maquinaria','')
    if selected:
        try:
            selected_machine=request.user.machines.get(pk=selected)
            qs=qs.filter(machine=selected_machine)
        except (Machine.DoesNotExist,ValidationError,ValueError):raise Http404
    page=Paginator(qs,30).get_page(request.GET.get('page'))
    return render(request,'portal/messages.html',{'messages_list':page,'page_obj':page,'machines':request.user.machines.all()})

@require_POST
@api
def api_create(request):
    body=payload(request,allowed=['category'])
    from .intake import contact_complete
    if not contact_complete(request.user):
        return JsonResponse({'error':'Completa tus datos de contacto antes de publicar.',
                             'url':'/panel/perfil/?next=/panel/maquinarias/nueva/'},status=400)
    if not throttle(request,'create',30,3600,str(request.user.pk)):raise ValidationError('Alcanzaste el límite de nuevos borradores por hora.')
    category=None
    if body.get('category') in (None, '', 'unsure'):
        raise ValidationError('Selecciona el tipo de máquina que quieres anunciar.')
    if body.get('category') not in (None, '', 'unsure'):
        try:category=Category.objects.get(pk=body['category'],active=True)
        except (Category.DoesNotExist,ValueError,TypeError):raise ValidationError('Selecciona una categoría disponible.')
    provenance={'currency':{'source':'system','review':'needs_review'}}
    if category:provenance['category']={'source':'user','review':'confirmed'}
    machine=Machine.objects.create(owner=request.user,category=category,data={'currency':'USD'},provenance=provenance)
    event(request,'draft_started',machine)
    return JsonResponse({'id':str(machine.pk),'url':f'/panel/maquinarias/{machine.pk}/'},status=201)

@require_POST
@api
def api_save(request,pk):
    machine=owned(request,pk);body=payload(request)
    if str(body.get('revision'))!=str(machine.revision):return JsonResponse({'error':'Hay una versión más reciente. Recarga antes de guardar para no sobrescribir cambios.','revision':machine.revision},status=409)
    revision=body.pop('revision',None)
    machine=services.save_draft(machine,request.user,body,revision)
    return JsonResponse({'revision':machine.revision,'saved_at':machine.updated_at.isoformat(),'machine':machine_state(machine)})

def asset_info(asset):
    return {'id':str(asset.pk),'url':f'/archivos/{asset.pk}/','kind':asset.kind,'purpose':asset.purpose,'is_cover':asset.is_cover,'processing_status':asset.processing_status,'error':asset.error,'position':asset.position}


def machine_state(machine):
    from .analysis_specialization import private_completion_actions
    return {'id':str(machine.pk),'revision':machine.revision,'title':machine.title,'category':machine.category_id,
            'data':machine.data,'provenance':machine.provenance,'editable':machine.editable,'status':machine.status,
            'valuation':services.machine_valuation(machine), 'completion_actions':private_completion_actions(machine.data,machine.category)}


def analysis_state(job, machine):
    result=job.result if job.status=='completed' else None
    if isinstance(result,dict):result={key:value for key,value in result.items() if key!='photo_cache'}
    if isinstance(result,dict) and isinstance(result.get('valuation'),dict):
        result={**result,'valuation':{key:value for key,value in result['valuation'].items() if key!='diagnostics'}}
    return {'id':str(job.pk),'status':job.status,'result':result,'preflight':job.result.get('preflight') is True,
            'input_assets':[{'id':str(item.get('id')), 'purpose':item.get('purpose')}
                for item in (job.application_snapshot or {}).get('assets',[])
                if item.get('kind')=='image' and item.get('purpose')!='document'],
            'input_category':job.result.get('input_category_id'),
            'processing_stage':job.result.get('progress',{}).get('stage',job.status),
            'processing_progress':job.result.get('progress',{'stage':job.status}),
            'error':job.error if job.status=='failed' else '', 'assets':[asset_info(a) for a in machine.assets.all()],
            'machine':machine_state(machine),'auto_apply':services.automatic_application_status(job)}

@require_POST
@api
def api_upload(request,pk):
    from .processing import ingest_asset
    machine=owned(request,pk)
    if not request.FILES.get('file'):raise ValidationError('Selecciona un archivo.')
    if not throttle(request,'uploads',80,3600,str(request.user.pk)):raise ValidationError('Alcanzaste el límite de cargas por hora.')
    record_event(request,'upload_started',page='upload')
    asset=ingest_asset(machine,request.user,request.FILES['file'],request.POST.get('purpose','general'))
    event(request,'file_received',machine)
    machine.refresh_from_db(fields=['revision'])
    return JsonResponse({**asset_info(asset),'revision':machine.revision},status=201)

@require_POST
@api
def api_asset_action(request,pk):
    with transaction.atomic():
        asset=get_object_or_404(Asset,pk=pk)
        machine=owned(request,asset.machine_id)
        machine=Machine.objects.select_for_update().get(pk=machine.pk)
        services.require_owner(machine,request.user)
        if not machine.editable:raise ValidationError('La solicitud está en revisión. Espera las observaciones antes de cambiar sus archivos.')
        body=payload(request,allowed=['action','purpose']);action=body.get('action')
        if action=='delete':
            # A retained version must remain reproducible. Deletion is a removal from this draft only.
            referenced=any(str(asset.pk) in v.data.get('asset_ids',[]) for v in machine.versions.all())
            if referenced:raise ValidationError('Este archivo pertenece a una versión enviada. El equipo puede ayudarte a reemplazarlo conservando el historial.')
            asset_id=str(asset.pk)
            asset.delete()
            services.audit(request.user,'asset.removed',machine,{'asset_id':asset_id})
        elif action=='cover':
            if asset.kind!='image':raise ValidationError('La portada debe ser una fotografía.')
            machine.assets.update(is_cover=False);asset.is_cover=True;asset.save(update_fields=['is_cover'])
        elif action in ('up','down'):
            items=list(machine.assets.order_by('position','created_at'))
            index=next(i for i,a in enumerate(items) if a.pk==asset.pk)
            target=max(0,min(len(items)-1,index+(-1 if action=='up' else 1)))
            items[index],items[target]=items[target],items[index]
            for position,item in enumerate(items):item.position=position;item.save(update_fields=['position'])
        elif action=='purpose':
            purpose=body.get('purpose')
            if purpose not in ['general','plate','detail','document']:raise ValidationError('Tipo de fotografía no válido.')
            asset.purpose=purpose;asset.public_authorized=False;asset.save(update_fields=['purpose','public_authorized'])
        else:raise ValidationError('Acción no válida.')
        machine.revision+=1
        if machine.status=='approved':machine.status='draft'
        machine.save(update_fields=['revision','status','updated_at'])
        services.audit(request.user,'asset.'+action,machine,{'asset_id':str(pk),'revision':machine.revision})
    return JsonResponse({'ok':True,'revision':machine.revision,'assets':[asset_info(a) for a in machine.assets.all()]})

@require_POST
@api
def api_analyze(request,pk):
    from .processing import enqueue_analysis
    machine=owned(request,pk);body=payload(request,allowed=['consent','asset_ids','mode','auto_apply','revision','research','preflight'])
    if body.get('consent') is not True:raise ValidationError('Autoriza el procesamiento de las imágenes necesarias mediante OpenAI.')
    from .intake import preparation_mode
    mode=preparation_mode(machine,body.get('asset_ids'))
    if mode=='catalogue':
        # The catalogue fiche is already composed from approved local records.
        # Do not create an unsupported AnalysisJob or send a paid request when
        # the owner presses "Generar" again without unit evidence.
        if body.get('revision') is not None and body.get('revision') != machine.revision:
            return JsonResponse({'error':'Hay una versión más reciente. Recarga antes de actualizar la ficha.',
                                 'revision':machine.revision},status=409)
        return JsonResponse({'id':None,'status':'completed','mode':'catalogue','refresh':True,
                             'result':{'catalogue':{'status':'ready','message':'La ficha conserva las referencias documentadas del modelo; no son datos confirmados de esta unidad.'}},
                             'processing_stage':'completed','processing_progress':{'stage':'completed'},
                             'error':'','assets':[asset_info(asset) for asset in machine.assets.all()],
                             'machine':machine_state(machine),'auto_apply':{'status':'no_changes','applied_fields':[]}})
    preflight=body.get('preflight',False)
    if type(preflight) is not bool:raise ValidationError('Indica una comprobación de fotografías válida.')
    job=enqueue_analysis(machine,request.user,body.get('asset_ids'),mode,analytics_context=capture_context(request,page='analysis'),auto_apply=False if preflight else body.get('auto_apply',False),expected_revision=body.get('revision'),authorize_ai=True,research=False if preflight else body.get('research',True),preflight=preflight)
    machine.refresh_from_db()
    return JsonResponse(analysis_state(job,machine))

@require_GET
@api
def api_analysis(request,pk):
    job=get_object_or_404(AnalysisJob,pk=pk);machine=owned(request,job.machine_id)
    return JsonResponse(analysis_state(job,machine))

@require_POST
@api
def api_apply(request,pk):
    machine=owned(request,pk);body=payload(request,allowed=['job_id','fields','revision','automatic'])
    job=get_object_or_404(AnalysisJob,pk=body.get('job_id'),machine=machine,status='completed')
    if 'automatic' in body and type(body['automatic']) is not bool:raise ValidationError('Indica una acción de completado válida.')
    if body.get('automatic') is True:
        machine,completion=services.apply_analysis_automatically(machine,request.user,job,body.get('revision'))
    else:
        machine=services.apply_analysis_suggestions(machine,request.user,job,body.get('fields',[]),body.get('revision'))
        completion=services.automatic_application_status(job)
        event(request,'sheet_reviewed',machine)
    return JsonResponse({'revision':machine.revision,'data':machine.data,'title':machine.title,'category':machine.category_id,
                         'provenance':machine.provenance,'machine':machine_state(machine),'auto_apply':completion})

@require_POST
@api
def api_submit(request,pk):
    machine=owned(request,pk);body=payload(request,allowed=['advertise_consent','contact_consent'])
    sub=services.submit_machine(machine,request.user,body.get('advertise_consent') is True,body.get('contact_consent') is True)
    event(request,'submission_sent',machine)
    return JsonResponse({'folio':machine.folio,'status':sub.status,'url':'/panel/solicitudes/'})

@require_POST
@api
def api_machine_action(request,pk):
    body=payload(request,allowed=['action','value','revision'])
    if body.get('action') in {'delete_draft','restore_draft'}:
        machine=get_object_or_404(Machine.all_objects,pk=pk,owner=request.user)
        action=services.delete_draft if body['action']=='delete_draft' else services.restore_draft
        machine=action(machine,request.user,body.get('revision'))
        return JsonResponse({'ok':True,'url':'/panel/maquinarias/','revision':machine.revision})
    machine=owned(request,pk)
    if body.get('action')=='duplicate':
        machine=services.duplicate_machine(machine,request.user)
        return JsonResponse({'id':str(machine.pk),'url':f'/panel/maquinarias/{machine.pk}/'})
    if body.get('action')=='availability':services.set_availability(machine,request.user,body.get('value'));return JsonResponse({'ok':True})
    raise ValidationError('Acción no válida.')

def safe_public_data(snapshot):
    from .public_data import public_projection
    raw_snapshot=snapshot if isinstance(snapshot,dict) else {}
    raw_data=raw_snapshot.get('data',{}) if isinstance(raw_snapshot.get('data',{}),dict) else {}
    identifiers={services._reference_text(raw_data.get(key)) for key in ('serial','vin')} - {''}
    data=public_projection(snapshot)
    # Keep exclusions from this version before removing its private fields.
    technical_keys=set(services.WEB_FIELD_LABELS) | {'hours','kilometers','attachments'} | services.VISUAL_LABELS.keys() | services.ESTIMATE_LABELS.keys()
    for key in technical_keys:
        if key in data and any(identifier in services._reference_text(data[key]) for identifier in identifiers):
            data.pop(key)
    for key in ['serial','vin','plate_transcription','plate_kind','plate_type','no_plate','notes','document','owner_email','owner_phone','email','phone']:data.pop(key,None)
    if not snapshot.get('contact_authorized'):data.pop('contact_public',None)
    return data

def public_record(token):
    publication=get_object_or_404(Publication.objects.select_related('machine','version','machine__owner'),token=token,destination='share',enabled=True,status='published',machine__deleted_at__isnull=True)
    if not publication.version or publication.machine.owner.advertiser_status!='approved' or publication.version_id!=publication.machine.approved_version_id or publication.machine.availability=='withdrawn':raise Http404
    return publication

def sheet_context(machine,version=None,public=False,token=None):
    from .sheet_details import build_sheet_details
    from .category_profiles import PROFILE_FIELD_LABELS, display_field_value
    from .commercial import commercial_rows, ESTIMATE_LABEL
    original_data=version.data.get('data',{}) if version else machine.data
    plate_ids=services.detected_plate_asset_ids(machine)
    if version:plate_ids |= set(version.data.get('private_plate_asset_ids',[]))
    if version:
        data=safe_public_data(version.data) if public else version.data.get('data',{})
        ids=version.data.get('public_asset_ids' if public else 'asset_ids',[])
        assets=machine.assets.filter(pk__in=ids,processing_status='ready')
        title=version.data.get('title',machine.title)
        if public:
            from .public_data import public_json
            title=public_json(version.data,title=title).get('title') or 'Maquinaria'
    else:data=safe_public_data({'data':original_data}) if public else original_data;assets=machine.assets.filter(processing_status='ready');title=machine.title
    if public:assets=assets.filter(public_authorized=True).exclude(purpose__in=['plate','document']).exclude(pk__in=plate_ids)
    # Render approved title rather than the current draft title.
    machine=copy.copy(machine);machine.title=title;machine._detected_plate_asset_ids=plate_ids
    if not public:
        assets=list(assets)
        for asset in assets:
            if str(asset.pk) in plate_ids:
                asset.purpose='plate'
    category_name=version.data.get('category_name','') if version else (machine.category.name if machine.category_id else '')
    field_provenance=version.data.get('provenance',{}) if version else machine.provenance
    def origin_label(key):
        meta=field_provenance.get(key,{})
        if not isinstance(meta,dict):return 'Dato de la ficha'
        if meta.get('review_reason')=='conflicting_reading':return 'Lectura en conflicto · por revisar'
        if meta.get('source')=='user':return 'Editado en la ficha'
        if meta.get('source')=='web':return 'Referencia web' + (' · confirmada' if meta.get('review')=='confirmed' else ' · por revisar')
        label={'plate':'Lectura de placa','image':'Lectura de fotografía'}.get(meta.get('source'),'Dato de la ficha')
        return label + (' · por revisar' if meta.get('review') in {'needs_review','not_identifiable'} else '')
    field_origins={key:origin_label(key) for key in data if data.get(key) not in (None,'')}
    labels={'power':'Potencia','weight':'Peso','capacity':'Capacidad','dimensions':'Dimensiones','fuel':'Combustible','kilometers':'Kilometraje','engine':'Motor','transmission':'Transmisión','attachments':'Accesorios',**services.PLATE_TECHNICAL_LABELS,**services.CATALOGUE_TECHNICAL_LABELS}
    labels={**{key:labels[key] for key in ('weight','digging_depth')}, **PROFILE_FIELD_LABELS, **labels}
    extra_fields=[{'key':key,'label':label,'value':display_field_value(key,data[key]),'source_label':'' if public else field_origins[key]} for key,label in labels.items() if data.get(key) not in (None,'')]
    display_location=data.get('location') or ', '.join(str(data[key]) for key in ('location_city','location_region','location_country') if data.get(key))
    has_identification=bool(category_name or any(data.get(key) not in (None,'') for key in ('brand','model','model_family','year','hours','condition','price','estimate_min','estimate_max','estimated_year_from','estimated_year_to','location','location_country','location_region','location_city')) or data.get('usage_condition') not in (None,'','Por confirmar') or not public)
    # The helper needs private exclusions, but returns only allowlisted reading aids.
    technical_interpretation=build_sheet_details(original_data,field_provenance,category=category_name)
    reference_snapshot=version.data if version else {'data':machine.data,'provenance':machine.provenance,'web_research':services.web_research_for_provenance(machine.provenance)}
    web_references=services.public_web_references(reference_snapshot,include_private=not public)
    if public:
        technical_interpretation=[item for item in technical_interpretation if item['key'] in data]
        web_references=[item for item in web_references if item['field'] in data and item['value']==data[item['field']]]
    whatsapp_url=''
    if public:
        contact_settings=PlatformSettings.objects.filter(pk=1).first()
        phone=re.sub(r'[\s()-]','',contact_settings.contact_phone if contact_settings else '')
        if re.fullmatch(r'\+[1-9]\d{7,14}',phone):
            whatsapp_url=f'https://wa.me/{phone[1:]}?'+urlencode({'text':f'Hola IMC México. Quiero información sobre {machine.folio}: {title}.'})
    valuation_snapshot=version.data if version else {'data':machine.data,'provenance':field_provenance,'valuations':services.valuations_for_provenance(field_provenance)}
    assets = list(assets)
    gallery = [asset for asset in assets if asset.kind == 'image' and asset.purpose not in {'plate', 'document'} and str(asset.pk) not in plate_ids]
    asset_base_url = f'/ficha/{token}/archivo/' if public else '/archivos/'
    essential_keys = {'weight', 'power', 'capacity', 'digging_depth', 'lift_height', 'working_height', 'drum_width', 'engine', 'dimensions', 'fuel'}
    essential_fields = [item for item in extra_fields if item['key'] in essential_keys][:6]
    return {'essential_fields': essential_fields, 'main_assets': gallery[:4], 'additional_assets': gallery[4:10], 'asset_base_url': asset_base_url, 'machine':machine,'data':data,'assets':assets,'public':public,'version':version,'token':token,'category_name':category_name,'extra_fields':extra_fields,'field_origins':{} if public else field_origins,'technical_interpretation':technical_interpretation,'whatsapp_url':whatsapp_url,'web_references':web_references,'provenance':{} if public else field_provenance,'display_location':display_location,'has_identification':has_identification,
            'commercial_rows':commercial_rows(data,field_provenance),'valuation':{} if public else services.public_valuation(valuation_snapshot),'estimate_label':ESTIMATE_LABEL}

@login_required
def machine_sheet(request,pk):
    machine=owned(request,pk)
    version=get_object_or_404(MachineVersion,machine=machine,pk=request.GET['version']) if request.GET.get('version') else None
    record_event(request,'sheet_reviewed',page='internal_sheet')
    context = sheet_context(machine,version)
    context['main_record'] = machine.publications.filter(destination='main', acknowledged_at__isnull=False).first()
    context['can_export'] = can_export_machine(request)
    from .sharing import current_share, share_url
    share=current_share(machine)
    context['share_url'] = share_url(share) if share else ''
    context['include_serial'] = bool(share and share.include_serial)
    context['include_contact'] = bool(share and share.snapshot.get('contact_authorized'))
    return render(request,'portal/sheet.html',context)

def public_sheet(request,token):
    pub=public_record(token)
    context=sheet_context(pub.machine,pub.version,True,token)
    back=request.GET.get('back','')
    context['catalog_back']=back if back.startswith('/maquinaria/') else '/maquinaria/'
    context['can_export'] = False
    from .sharing import legacy_share_url
    context['share_url'] = legacy_share_url(pub.token)
    response=render(request,'portal/sheet.html',context)
    response['Cache-Control']='no-store';response['X-Robots-Tag']='noindex'
    return response

def send_asset(asset,original=False):
    f=asset.original if original or not asset.preview else asset.preview
    if not f:raise Http404
    content_type=asset.mime_type if original or not asset.preview else ('video/mp4' if asset.kind=='video' else 'image/jpeg')
    response=FileResponse(f.open('rb'),content_type=content_type)
    response['Cache-Control']='private, no-store'
    response['X-Robots-Tag']='noindex, nofollow'
    if original:response['Content-Disposition']=f'attachment; filename="{asset.pk}{__import__("pathlib").Path(f.name).suffix}"'
    return response

@login_required
def asset_download(request,pk):
    asset=get_object_or_404(Asset,pk=pk);owned(request,asset.machine_id)
    return send_asset(asset,request.GET.get('original')=='1')

def public_asset(request,token,pk):
    pub=public_record(token)
    if (str(pk) not in pub.version.data.get('public_asset_ids',[]) or str(pk) in pub.version.data.get('private_plate_asset_ids',[])
            or str(pk) in services.detected_plate_asset_ids(pub.machine)):raise Http404
    asset=get_object_or_404(Asset,pk=pk,machine=pub.machine,public_authorized=True,processing_status='ready')
    if asset.purpose in ['plate','document']:raise Http404
    return send_asset(asset)

def machine_pdf(request,pk):
    from .pdf import build_pdf
    machine=get_object_or_404(Machine.objects.select_related('approved_version'),pk=pk,deleted_at__isnull=True)
    if not can_export_machine(request):
        raise PermissionDenied
    version=get_object_or_404(MachineVersion,machine=machine,pk=request.GET['version']) if request.GET.get('version') else None
    context=sheet_context(machine,version)
    response=HttpResponse(build_pdf(context['machine'],context['data'],context['assets'],False,version),content_type='application/pdf')
    response['Content-Disposition']=f'attachment; filename="{machine.folio}.pdf"'
    response['Cache-Control']='private, no-store'
    response['X-Robots-Tag']='noindex, nofollow'
    return response

def public_pdf(request,token):
    from .pdf import build_pdf
    pub=public_record(token)
    if not can_export_machine(request):
        raise PermissionDenied
    context=sheet_context(pub.machine,pub.version,True,token)
    response=HttpResponse(build_pdf(context['machine'],context['data'],context['assets'],True,pub.version),content_type='application/pdf')
    response['Content-Disposition']=f'attachment; filename="{pub.machine.folio}.pdf"'
    response['Cache-Control']='private, no-store'
    response['X-Robots-Tag']='noindex, nofollow'
    return response

@require_GET
def health(request):
    from django.db import connection
    try:
        with connection.cursor() as c:c.execute('SELECT 1');c.fetchone()
    except Exception:return JsonResponse({'status':'unavailable'},status=503)
    return JsonResponse({'status':'ok'})

@operator_required()
def operations(request):
    def allowed(*permissions):
        return any(request.user.has_perm('portal.'+permission) for permission in permissions)
    capabilities={
        'can_view_submissions':allowed('view_submission','change_submission','review_submission'),
        'can_view_leads':allowed('view_lead','change_lead'),
        'can_view_jobs':allowed('view_analysisjob','change_analysisjob'),
        'can_view_users':allowed('view_user','change_user','manage_advertisers'),
        'can_view_machines':allowed('view_machine','change_machine'),
        'can_view_publications':allowed('view_publication','change_publication','publish_machine'),
        'can_view_settings':allowed('view_platformsettings','change_platformsettings'),
        'can_view_messages':allowed('view_message','change_message'),
        'can_view_notifications':allowed('view_notification','change_notification'),
        'can_view_accesses':allowed('view_accountaccess'),
        'can_compose_notifications':allowed('add_notification') and allowed('view_user','change_user'),
        'can_send_messages':allowed('add_message') and allowed('view_machine','change_machine'),
    }
    qs=(Submission.objects.filter(machine__deleted_at__isnull=True) if capabilities['can_view_submissions'] else Submission.objects.none()).select_related('machine','machine__owner','version')
    q=request.GET.get('q','').strip()[:100]
    if q:
        folio_query=q.removeprefix('IMC-').removeprefix('imc-').replace('-','')
        qs=qs.filter(Q(machine__title__icontains=q)|Q(machine__owner__email__icontains=q)|Q(machine__data__icontains=q)|Q(machine__id__istartswith=folio_query))
    state=request.GET.get('status',request.GET.get('estado',''))
    if state:qs=qs.filter(status=state)
    live=Machine.objects.filter(owner__is_test=False)
    live_jobs=AnalysisJob.objects.filter(requested_by__is_test=False)
    visible_leads=Lead.objects.filter(Q(machine__isnull=True)|Q(machine__deleted_at__isnull=True)) if capabilities['can_view_leads'] else Lead.objects.none()
    visible_jobs=AnalysisJob.objects.filter(machine__deleted_at__isnull=True) if capabilities['can_view_jobs'] else AnalysisJob.objects.none()
    visible_messages=Message.objects.filter(machine__deleted_at__isnull=True) if capabilities['can_view_messages'] else Message.objects.none()
    visible_notifications=(Notification.objects.exclude(kind__in=['activation','admin_activation','verify','recovery'])
        if capabilities['can_view_notifications'] else Notification.objects.none())
    counts={
        'users':User.objects.filter(is_test=False,is_guest=False).count() if capabilities['can_view_users'] else None,
        'pending':live.filter(status__in=['submitted','in_review']).count() if capabilities['can_view_submissions'] else None,
        'advertisers':User.objects.filter(advertiser_status='pending',is_test=False,is_guest=False).count() if capabilities['can_view_users'] else None,
        'active':Publication.objects.filter(destination='share',enabled=True,status='published',machine__owner__is_test=False,machine__deleted_at__isnull=True).count() if capabilities['can_view_publications'] else None,
        'sold':live.filter(availability='sold').count() if capabilities['can_view_machines'] else None,
        'abandoned':live.filter(status='draft',updated_at__lt=timezone.now()-timedelta(days=30)).count() if capabilities['can_view_machines'] else None,
        'failed_jobs':live_jobs.filter(machine__deleted_at__isnull=True,status='failed').count() if capabilities['can_view_jobs'] else None,
        'tokens':(live_jobs.aggregate(total=Sum('input_tokens')+Sum('output_tokens'))['total'] or 0) if capabilities['can_view_jobs'] else None,
        'leads':visible_leads.filter(status='new',is_test=False).count() if capabilities['can_view_leads'] else None,
        'pending_emails':visible_notifications.filter(channel='email',status='pending',user__is_test=False).count() if capabilities['can_view_notifications'] else None,
        'failed_emails':visible_notifications.filter(channel='email',status='failed',user__is_test=False).count() if capabilities['can_view_notifications'] else None,
    }
    page=Paginator(qs,20).get_page(request.GET.get('page'))
    return render(request,'portal/operations.html',{'counts':counts,'submissions':page,'page_obj':page,
        'jobs':visible_jobs.select_related('machine').order_by('-created_at')[:10],
        'leads':visible_leads.order_by('-created_at')[:10],'q':q,
        'recent_users':User.objects.filter(is_test=False,is_guest=False).order_by(F('last_login').desc(nulls_last=True),'-date_joined')[:8] if capabilities['can_view_users'] else User.objects.none(),
        'recent_machines':live.select_related('owner').order_by('-updated_at')[:8] if capabilities['can_view_machines'] else Machine.objects.none(),
        'recent_messages':visible_messages.select_related('machine','sender').order_by('-created_at')[:8],
        'recent_notifications':visible_notifications.select_related('user').order_by('-created_at')[:8],
        'backup_status':get_backup_status() if capabilities['can_view_settings'] else None,**capabilities})


@login_required
@require_GET
def notification_list(request):
    from .notifications import visible_notifications
    notices=visible_notifications(request.user)
    page=Paginator(notices,20).get_page(request.GET.get('page'))
    return render(request,'portal/notification_list.html',{'notifications':page,'page_obj':page})


@require_GET
@api
def notification_summary(request):
    from django.db import OperationalError,ProgrammingError
    from .notifications import notification_summary as summarize
    try:
        with transaction.atomic():
            result=summarize(request.user)
    except (OperationalError,ProgrammingError):
        return JsonResponse({'error':'Los avisos no están disponibles temporalmente. Inténtalo de nuevo.'},status=503)
    return JsonResponse(result)


@login_required
@require_GET
def notification_detail(request,pk):
    from .notifications import visible_notifications,notification_target
    notice=get_object_or_404(visible_notifications(request.user).select_related('machine'),pk=pk)
    target_url,target_label=notification_target(notice,request.user)
    return render(request,'portal/notification_detail.html',{'notification':notice,
        'notification_target_url':target_url,'notification_target_label':target_label})


def _notification_read_response(request,pk=None):
    if 'application/json' in request.headers.get('Accept','') or request.content_type=='application/json':
        from .notifications import notification_summary as summarize
        return JsonResponse(summarize(request.user))
    return redirect('notification_detail',pk=pk) if pk is not None else redirect('notification_list')


@require_POST
@api
def notification_read(request,pk):
    from .notifications import mark_notification_read
    mark_notification_read(request.user,pk)
    return _notification_read_response(request,pk)


@require_POST
@api
def notification_read_all(request):
    from .notifications import mark_all_notifications_read
    mark_all_notifications_read(request.user)
    return _notification_read_response(request)


@operator_required('portal.add_notification')
def notification_compose(request):
    from .communications import ManualNotificationForm,can_compose_notifications,queue_manual_notification
    if not can_compose_notifications(request.user):raise PermissionDenied
    form=ManualNotificationForm(request.POST if request.method=='POST' else None,actor=request.user)
    if request.method=='POST' and form.is_valid():
        try:
            created=queue_manual_notification(actor=request.user,recipient=form.cleaned_data['recipient'],
                subject=form.cleaned_data['subject'],body=form.cleaned_data['body'],request_id=form.cleaned_data['request_token'])
            flash.success(request,'Notificación guardada en la plataforma y correo en cola. Consulta el estado del correo en Notificaciones.' if created else 'Este envío ya quedó registrado. No se ha duplicado.')
            return redirect('notification_compose')
        except ValidationError as exc:form.add_error(None,exc)
    return render(request,'portal/notification_compose.html',{'form':form})

@operator_required('portal.review_submission')
def review(request,pk):
    sub=get_object_or_404(Submission.objects.select_related('machine','version','machine__owner'),pk=pk,machine__deleted_at__isnull=True)
    machine=sub.machine
    if request.method=='POST':
        action=request.POST.get('action')
        try:
            if action=='review':services.review_submission(sub,request.user,request.POST.get('decision'),request.POST.get('reason',''))
            elif action=='local_duplicate_review':
                services.record_local_duplicate_review(machine,sub,request.user,request.POST.get('result'),
                    request.POST.get('evidence',''),request.POST.get('limitations',''))
            elif action=='advertiser':services.set_advertiser_status(machine.owner,request.user,request.POST.get('status'),request.POST.get('reason',''))
            elif action=='message':
                body=request.POST.get('body','').strip()
                if not body or len(body)>5000:raise ValidationError('Escribe un mensaje de hasta 5 000 caracteres.')
                internal=request.POST.get('internal') in ['1','on','true']
                with transaction.atomic():
                    current=get_object_or_404(Machine.objects.select_for_update().select_related('owner'),pk=machine.pk)
                    message=Message.objects.create(machine=current,sender=request.user,body=body,internal=internal)
                    services.audit(request.user,'message.internal' if internal else 'message.reply',message)
                    if not internal:services._notify(current.owner,current,'reply',f'{current.folio}: tienes una respuesta',body)
            elif action=='authorize_assets':
                if not request.user.has_perm('portal.publish_machine'):raise PermissionDenied
                if sub.status not in ['submitted','in_review']:raise ValidationError('La autorización de imágenes se fija antes de aprobar la solicitud.')
                ids=request.POST.getlist('asset_ids')
                valid_ids=set(sub.version.data.get('asset_ids',[]))
                if set(ids)-valid_ids:raise ValidationError('Hay archivos que no corresponden a la versión enviada.')
                with transaction.atomic():
                    Machine.objects.select_for_update().get(pk=machine.pk)
                    locked_sub=Submission.objects.select_for_update().get(pk=sub.pk)
                    if locked_sub.status not in ['submitted','in_review']:raise ValidationError('La solicitud ya fue resuelta. La versión aprobada es inmutable.')
                    machine.assets.filter(pk__in=valid_ids).update(public_authorized=False)
                    machine.assets.filter(pk__in=ids,purpose__in=['general','detail'],processing_status='ready').update(public_authorized=True)
                    services.audit(request.user,'assets.public_permissions',machine,{'asset_ids':ids})
            elif action=='share':services.set_publication(machine,request.user,request.POST.get('enabled') in ['1','on','true'])
            elif action=='export':
                if not request.user.has_perm('portal.publish_machine'):
                    raise PermissionDenied
                return export_machine(request,machine.pk)
            else:raise ValidationError('Acción no válida.')
            flash.success(request,'La acción quedó guardada y registrada en el historial.')
            return redirect(f'/operaciones/solicitudes/{sub.pk}/')
        except ValidationError as exc:flash.error(request,' '.join(exc.messages))
    pub=machine.publications.filter(destination='share').first()
    duplicate_review=services._local_duplicate_review_event(machine,sub)
    possible_duplicates=(services.find_possible_duplicates(machine,request.user)
                         if request.user.has_perm('portal.view_machine') else [])
    return render(request,'portal/review.html',{'submission':sub,'machine':machine,'assets':machine.assets.filter(pk__in=sub.version.data.get('asset_ids',[])),'data':sub.version.data.get('data',{}),'provenance':sub.version.data.get('provenance',{}),'versions':machine.versions.all(),'versions_json':[{'id':v.pk,'number':v.number,'data':v.data} for v in machine.versions.all()],'messages_list':machine.messages.select_related('sender'),'publication':pub,'share_url':f'{settings.PUBLIC_URL}/ficha/{pub.token}/' if pub and pub.enabled else '', 'can_select_imc_media':can_export_machine(request), 'jobs':AnalysisJob.objects.filter(machine=machine).order_by('-created_at'),'possible_duplicates':possible_duplicates,'local_duplicate_review':duplicate_review})

@operator_required('portal.publish_machine')
@require_POST
def export_machine(request,pk):
    try:
        return _export_machine(request, pk)
    except (ValidationError, OSError) as exc:
        message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'No se pudo leer un archivo autorizado. Comprueba su almacenamiento antes de exportar.'
        flash.error(request, message)
        return redirect('integration_detail', pk=pk)


def _export_machine(request,pk):
    import zipfile
    from io import BytesIO
    from .pdf import build_pdf
    machine=get_object_or_404(Machine.objects.select_related('approved_version','owner'),pk=pk)
    if not machine.approved_version or machine.owner.advertiser_status!='approved' or machine.availability=='withdrawn':raise PermissionDenied
    version=machine.approved_version
    context=sheet_context(machine,version,True)
    output=BytesIO()
    from .export_payload import build_export_payload
    from .integration import prepare_delivery, delivery_metadata
    main_publication = machine.publications.filter(destination='main').first()
    selected_assets = (main_publication.imc_asset_ids if main_publication
                       and main_publication.imc_selection_version_id == version.pk else None)
    exported, files = build_export_payload(machine, version, asset_ids=selected_assets)
    # PDF and media are assembled before persisting an exported status. A
    # storage/PDF failure must not pretend a package was delivered. The PDF is
    # part of this manual handoff, so its images must be the exact ordered IMC
    # manifest rather than the independent Seenode shared-sheet selection.
    exported_ids = [item['id'] for item in exported['assets']]
    by_id = {str(asset.pk): asset for asset in machine.assets.filter(pk__in=exported_ids)}
    pdf_assets = [by_id[asset_id] for asset_id in exported_ids if asset_id in by_id]
    pdf_bytes = build_pdf(context['machine'], context['data'], pdf_assets, True, version,
                          destination_asset_ids=exported_ids)
    delivery = prepare_delivery(machine, request.user, exported)
    envelope = {'schema': 'imc-handoff-v1', **delivery_metadata(delivery),
                'module_record_url': f'{settings.PUBLIC_URL}/panel/maquinarias/{machine.pk}/ficha/',
                'remote_record_id': delivery.publication.external_id or None,
                'connection': 'manual_handoff', 'remote_transport_performed': False,
                'acknowledgement_recorded': delivery.state == 'acknowledged'}
    snapshot = version.data if isinstance(version.data, dict) else {}
    values = snapshot.get('data', {}) if isinstance(snapshot.get('data', {}), dict) else {}
    def copy_value(name, fallback='Pendiente'):
        value = values.get(name)
        return str(value).strip() if value not in (None, '') else fallback
    exact_year = copy_value('year')
    if exact_year == 'Pendiente' and (values.get('estimated_year_from') or values.get('estimated_year_to')):
        exact_year = 'Pendiente; existe un rango local, no es un año exacto'
    estimated_year_range = 'Pendiente'
    if values.get('estimated_year_from') or values.get('estimated_year_to'):
        estimated_year_range = f'{copy_value("estimated_year_from")} a {copy_value("estimated_year_to")}'
    data_for_imc = '\n'.join([
        f'Ficha local: {machine.folio}', f'Versión: {version.number}',
        f'Tipo: {snapshot.get("category_name") or "Pendiente"}', f'Marca: {copy_value("brand")}',
        f'Modelo: {copy_value("model")}', f'Número de serie: {copy_value("serial")}',
        f'Precio solicitado: {copy_value("price")} {copy_value("currency", "USD")}',
        f'Año exacto: {exact_year}', f'Rango de año estimado: {estimated_year_range}',
        f'Horas de uso: {copy_value("hours")}',
        f'Ubicación país: {copy_value("location_country")}',
        f'Ubicación estado o región: {copy_value("location_region")}',
        f'Ubicación ciudad: {copy_value("location_city")}',
        f'Ubicación adicional: {copy_value("location")}',
        f'Peso: {copy_value("weight")}', f'Potencia: {copy_value("power")}',
        f'Capacidad: {copy_value("capacity")}', f'Profundidad de excavación: {copy_value("digging_depth")}',
        '', 'Descripción pública:', copy_value('description', 'Pendiente de redactar o confirmar.'),
    ])
    manifest_lines = [
        f'Identificador local: {machine.folio}', f'Versión: {version.number}',
        f'Anunciante local: {machine.owner.get_full_name() or machine.owner.email}',
        f'Fecha de preparación: {delivery.created_at.isoformat()}',
        f'Estado de revisión local: {machine.get_status_display()}',
        f'Referencia IMC: {delivery.publication.external_reference or "Pendiente"}',
        'Contenido seleccionado para IMC:',
    ]
    for item in exported['assets']:
        manifest_lines.append(f"- {item['destination_role']} · {item['path']} · posición local {item['position']}{' · portada' if item['cover'] else ''}")
    manifest_lines.extend(['Campos pendientes: revisar los valores marcados como Pendiente en datos_para_imc.txt.',
                           'No se incluyen placas ni documentos privados; las notas internas permanecen en Seenode.'])
    package_root = f'ficha_{machine.folio}_{version.number}'
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f'{package_root}/datos_para_imc.txt',data_for_imc)
        archive.writestr(f'{package_root}/ficha_administrativa.pdf',pdf_bytes)
        for path, raw in files:
            archive.writestr(f'{package_root}/{path}', raw)
            archive.writestr(path, raw)
        archive.writestr(f'{package_root}/manifiesto.txt','\n'.join(manifest_lines))
        archive.writestr(f'{package_root}/publicacion.json',json.dumps(exported,ensure_ascii=False,indent=2))
        archive.writestr(f'{package_root}/integracion.json',json.dumps(envelope,ensure_ascii=False,indent=2))
        # Keep these envelopes at the root for existing internal import tools;
        # they carry the exact same frozen version as the human-readable folder.
        archive.writestr('publicacion.json',json.dumps(exported,ensure_ascii=False,indent=2))
        archive.writestr('integracion.json',json.dumps(envelope,ensure_ascii=False,indent=2))
    from .integration import mark_delivery_exported
    mark_delivery_exported(delivery, request.user)
    services.audit(request.user,'publication.exported',machine,{'version':version.number})
    response=HttpResponse(output.getvalue(),content_type='application/zip');response['Content-Disposition']=f'attachment; filename="{machine.folio}-v{version.number}.zip"'
    return response
