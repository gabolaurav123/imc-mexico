import copy
import json
from functools import wraps
from datetime import timedelta
from django.conf import settings
from django.contrib import messages as flash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_GET
from .models import *
from .forms import ContactForm
from .security import operator_required, staff_authorized, throttle
from . import services

def owned(request,pk):
    query=Machine.objects.select_related('owner','category','approved_version')
    if not (staff_authorized(request.user) and request.user.has_perm('portal.view_machine')):query=query.filter(owner=request.user)
    return get_object_or_404(query,pk=pk)

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
        except ValidationError as exc:return JsonResponse({'error':' '.join(exc.messages)},status=400)
        except (ValueError,TypeError,KeyError):return JsonResponse({'error':'Revisa los datos enviados.'},status=400)
        except PermissionDenied:return JsonResponse({'error':'No tienes permiso para realizar esta acción.'},status=403)
        except Http404:return JsonResponse({'error':'El registro no está disponible.'},status=404)
    return wrapper

def event(request,name,machine=None):
    if request.user.is_authenticated:
        AnalyticsEvent.objects.create(event=name,user=request.user,machine=machine,is_test=request.user.is_test,device='mobile' if 'Mobile' in request.META.get('HTTP_USER_AGENT','') else 'desktop')

def home(request):return render(request,'portal/home.html')

PAGES={
 'como-funciona':('Tus fotos son el punto de partida','Prepara tu maquinaria con ayuda, a tu ritmo.', [('01 · Fotografía','Sube una vista general de la máquina. Si tienes una foto de la placa o el horómetro, agrégala. Puedes continuar sin ellos.'),('02 · Revisa','La IA propone una ficha a partir de lo visible. Tú confirmas o corriges cada dato. Lo desconocido puede quedarse sin especificar.'),('03 · Envía','Completa la ubicación y los datos comerciales. IMC México revisará la solicitud y podrá pedir correcciones. El envío no equivale a publicación.'),('04 · Sigue el proceso','Consulta tus solicitudes y responde las observaciones desde tu panel. Conservamos el avance aunque cierres el navegador.')]),
 'guia-de-fotos':('Una buena foto ayuda mucho','No necesitas equipo profesional: basta con tu celular y buena luz.', [('Vista general','Fotografía la máquina completa de costado. Evita personas y documentos ajenos en el encuadre.'),('Detalles que importan','Incluye accesorios, puntos de desgaste y defectos visibles, sin ocultarlos ni alterar las imágenes.'),('Placa, si la tienes','Acércate hasta que se lean los caracteres, evita reflejos y toma la imagen de frente. Indica si pertenece al motor, a la máquina o a otro componente.'),('Sin placa también puedes empezar','Una sola fotografía útil permite guardar un borrador. No inventes series, año u horas si los desconoces.'),('Video opcional','Un recorrido breve puede complementar las fotografías. El análisis de video mediante IA está desactivado.')]),
 'preguntas-frecuentes':('Resolvemos tus dudas','Lo esencial antes de anunciar tu maquinaria.', [('¿Necesito la placa?','No. Puedes empezar con una fotografía general y dejar los datos desconocidos pendientes.'),('¿La IA certifica mi máquina?','No. Organiza información visible y propone textos. Necesita revisión humana y no evalúa el estado mecánico interno.'),('¿Se publica al enviar?','No. El permiso de anunciante, la aprobación de una solicitud y la publicación en cada destino se gestionan por separado.'),('¿Puedo continuar más tarde?','Sí. Tu borrador se guarda en tu cuenta. La interfaz confirma cuándo terminó el guardado.'),('¿Mis fotos son públicas?','Inicialmente son privadas. Las placas, series y documentos no se publican por defecto. Solo se comparten versiones autorizadas.'),('¿Qué ocurre si falla el análisis?','Conservamos las fotografías. Puedes completar datos manualmente, reintentar dentro de los límites o pedir asistencia.')]),
 'privacidad':('Aviso de privacidad','Documento operativo pendiente de validación por el responsable de IMC México.', [('Finalidad','Tratamos los datos de cuenta, contacto, archivos y maquinaria para preparar fichas, revisar solicitudes y dar seguimiento. Las comunicaciones comerciales requieren consentimiento separado.'),('Procesamiento con OpenAI','Con tu autorización, enviamos las imágenes necesarias al servidor de OpenAI para extraer información y proponer una ficha. No enviamos intencionalmente tu correo ni teléfono. Evita documentos personales en las imágenes. store:false evita almacenar una respuesta como recurso recuperable, pero no garantiza ausencia absoluta de retención: aplican los controles y excepciones del proveedor.'),('Acceso y publicación','Tus borradores y originales son privados. La difusión exige permisos y revisión. Las imágenes pueden contener identificadores: se revisan antes de autorizar su publicación.'),('Conservación y derechos','Puedes solicitar acceso, corrección o eliminación en Panel → Seguridad. El responsable resolverá la solicitud y las obligaciones de conservación aplicables. La política inicial propone revisar datos inactivos tras 365 días; no elimina publicaciones activas automáticamente.'),('Responsable y contacto','Los datos legales del responsable, domicilio, transferencias, plazos y procedimiento definitivo deben ser validados por IMC México antes de apertura comercial. No se declara cumplimiento legal automático.')]),
 'terminos':('Términos de uso','Borrador pendiente de validación por el responsable de IMC México.', [('Objeto del portal','Esta plataforma recibe información de maquinaria, ayuda a organizarla y la somete a revisión. No es un sistema de pagos, subastas, financiamiento ni una garantía de venta.'),('Tu información','Declara únicamente datos que conozcas y señala defectos o limitaciones. Debes contar con autorización para anunciar el equipo y compartir las imágenes suministradas.'),('Revisión y permisos','La revisión administrativa no implica inspección ni certificación mecánica. IMC México decide el permiso de anunciante, la aprobación del contenido y la difusión de cada versión por separado.'),('Asistencia mediante IA','Las sugerencias pueden contener errores. Debes revisarlas antes de enviar. Los datos desconocidos permanecen sin especificar y pueden solicitarse aclaraciones.'),('Cambios y disponibilidad','Las modificaciones relevantes requieren una nueva revisión. Informa si el equipo se reserva, vende o retira. La exportación no acredita publicación en la web principal.')])}

def public_page(request,slug):
    if slug not in PAGES:raise Http404
    title,intro,sections=PAGES[slug]
    content=SiteContent.objects.filter(key=slug,active=True).first()
    if content:title=content.title or title;sections=[('',content.body)]
    return render(request,'portal/page.html',{'title':title,'intro':intro,'sections':[{'title':a,'body':b} for a,b in sections],'slug':slug})

def example(request):
    return render(request,'portal/example.html')

def contact(request):
    form=ContactForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        if not throttle(request,'contact',5,3600):form.add_error(None,'Has enviado varias consultas. Espera un momento antes de intentar de nuevo.')
        else:
            lead=form.save(commit=False)
            if request.user.is_authenticated:lead.user=request.user;lead.is_test=request.user.is_test
            lead.save()
            flash.success(request,'Recibimos tu consulta. Quedó registrada para seguimiento del equipo.')
            return redirect('/contacto/?enviado=1')
    return render(request,'portal/contact.html',{'form':form})

@login_required
def panel(request):
    qs=request.user.machines.all()
    counts={'total':qs.count(),'drafts':qs.filter(status='draft').count(),'pending':qs.filter(status__in=['submitted','in_review']).count(),'approved':qs.filter(approved_version__isnull=False).count(),'corrections':qs.filter(status='changes_requested').count()}
    return render(request,'portal/dashboard.html',{'machines':qs.prefetch_related('assets')[:6],'counts':counts,'recent_messages':Message.objects.filter(machine__owner=request.user,internal=False).select_related('machine','sender')[:5]})

@login_required
def machines(request):
    qs=request.user.machines.prefetch_related('assets')
    q=request.GET.get('q','')[:100]
    if q:
        folio_query=q.removeprefix('IMC-').removeprefix('imc-').replace('-','')
        qs=qs.filter(Q(title__icontains=q)|Q(data__icontains=q)|Q(id__istartswith=folio_query))
    state=request.GET.get('status',request.GET.get('estado',''))
    if state:qs=qs.filter(status=state)
    page=Paginator(qs,12).get_page(request.GET.get('page'))
    return render(request,'portal/machines.html',{'machines':page,'page_obj':page,'q':q})

@login_required
def machine_create(request):
    if request.method=='POST':
        machine=Machine.objects.create(owner=request.user)
        event(request,'draft_started',machine)
        return redirect(f'/panel/maquinarias/{machine.pk}/')
    return render(request,'portal/start.html')

@login_required
@ensure_csrf_cookie
def machine_wizard(request,pk):
    machine=owned(request,pk)
    try:step=max(1,min(5,int(request.GET.get('paso',request.GET.get('step',1)))))
    except ValueError:step=1
    job=AnalysisJob.objects.filter(machine=machine).order_by('-created_at').first()
    return render(request,'portal/wizard.html',{'machine':machine,'assets':machine.assets.all(),'categories':Category.objects.filter(active=True),'categories_json':list(Category.objects.filter(active=True).values('id','name','fields')),'step':step,'job':job,'data':machine.data,'provenance':machine.provenance,'machine_json':{'id':str(machine.id),'revision':machine.revision,'title':machine.title,'category':machine.category_id,'data':machine.data,'provenance':machine.provenance,'editable':machine.editable,'status':machine.status}})

@login_required
def requests_list(request):
    return render(request,'portal/requests.html',{'submissions':Paginator(Submission.objects.filter(machine__owner=request.user).select_related('machine','version'),20).get_page(request.GET.get('page'))})

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
    qs=Message.objects.filter(machine__owner=request.user,internal=False).select_related('machine','sender')
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
    payload(request,allowed=[])
    if not throttle(request,'create',30,3600,str(request.user.pk)):raise ValidationError('Alcanzaste el límite de nuevos borradores por hora.')
    machine=Machine.objects.create(owner=request.user)
    event(request,'draft_started',machine)
    return JsonResponse({'id':str(machine.pk),'url':f'/panel/maquinarias/{machine.pk}/'},status=201)

@require_POST
@api
def api_save(request,pk):
    machine=owned(request,pk);body=payload(request)
    if str(body.get('revision'))!=str(machine.revision):return JsonResponse({'error':'Hay una versión más reciente. Recarga antes de guardar para no sobrescribir cambios.','revision':machine.revision},status=409)
    revision=body.pop('revision',None)
    machine=services.save_draft(machine,request.user,body,revision)
    return JsonResponse({'revision':machine.revision,'saved_at':machine.updated_at.isoformat()})

def asset_info(asset):
    return {'id':str(asset.pk),'url':f'/archivos/{asset.pk}/','kind':asset.kind,'purpose':asset.purpose,'is_cover':asset.is_cover,'processing_status':asset.processing_status,'error':asset.error,'position':asset.position}

@require_POST
@api
def api_upload(request,pk):
    from .processing import ingest_asset
    machine=owned(request,pk)
    if not request.FILES.get('file'):raise ValidationError('Selecciona un archivo.')
    if not throttle(request,'uploads',80,3600,str(request.user.pk)):raise ValidationError('Alcanzaste el límite de cargas por hora.')
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
    machine=owned(request,pk);body=payload(request,allowed=['consent','asset_ids','mode'])
    if body.get('consent') is not True:raise ValidationError('Autoriza el procesamiento de las imágenes necesarias mediante OpenAI.')
    if not Consent.objects.filter(user=request.user,machine=machine,kind='ai',granted=True).exists():Consent.objects.create(user=request.user,machine=machine,kind='ai',granted=True)
    job=enqueue_analysis(machine,request.user,body.get('asset_ids'),body.get('mode','analysis'))
    return JsonResponse({'id':str(job.pk),'status':job.status})

@require_GET
@api
def api_analysis(request,pk):
    job=get_object_or_404(AnalysisJob,pk=pk);owned(request,job.machine_id)
    return JsonResponse({'id':str(job.pk),'status':job.status,'result':job.result if job.status=='completed' else None,'error':job.error if job.status=='failed' else '', 'assets':[asset_info(a) for a in job.machine.assets.all()]})

@require_POST
@api
def api_apply(request,pk):
    machine=owned(request,pk);body=payload(request,allowed=['job_id','fields','revision'])
    job=get_object_or_404(AnalysisJob,pk=body.get('job_id'),machine=machine,status='completed')
    machine=services.apply_analysis_suggestions(machine,request.user,job,body.get('fields',[]),body.get('revision'))
    event(request,'sheet_reviewed',machine)
    return JsonResponse({'revision':machine.revision,'data':machine.data,'title':machine.title,'provenance':machine.provenance})

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
    machine=owned(request,pk);body=payload(request,allowed=['action','value'])
    if body.get('action')=='duplicate':
        machine=services.duplicate_machine(machine,request.user)
        return JsonResponse({'id':str(machine.pk),'url':f'/panel/maquinarias/{machine.pk}/'})
    if body.get('action')=='availability':services.set_availability(machine,request.user,body.get('value'));return JsonResponse({'ok':True})
    raise ValidationError('Acción no válida.')

def safe_public_data(snapshot):
    data=copy.deepcopy(snapshot.get('data',{}))
    for key in ['serial','vin','plate_transcription','plate_kind','plate_type','no_plate','notes','document','owner_email','owner_phone','email','phone']:data.pop(key,None)
    if not snapshot.get('contact_authorized'):data.pop('contact_public',None)
    return data

def public_record(token):
    publication=get_object_or_404(Publication.objects.select_related('machine','version','machine__owner'),token=token,destination='share',enabled=True,status='published')
    if not publication.version or publication.machine.owner.advertiser_status!='approved' or publication.version_id!=publication.machine.approved_version_id or publication.machine.availability=='withdrawn':raise Http404
    return publication

def sheet_context(machine,version=None,public=False,token=None):
    if version:
        data=safe_public_data(version.data) if public else version.data.get('data',{})
        ids=version.data.get('public_asset_ids' if public else 'asset_ids',[])
        assets=machine.assets.filter(pk__in=ids,processing_status='ready')
        title=version.data.get('title',machine.title)
    else:data=machine.data;assets=machine.assets.filter(processing_status='ready');title=machine.title
    if public:assets=assets.filter(public_authorized=True).exclude(purpose__in=['plate','document'])
    # Render approved title rather than the current draft title.
    machine=copy.copy(machine);machine.title=title
    category_name=version.data.get('category_name','') if version else (machine.category.name if machine.category_id else '')
    labels={'power':'Potencia declarada','weight':'Peso declarado','capacity':'Capacidad declarada','dimensions':'Dimensiones','fuel':'Combustible','kilometers':'Kilometraje','engine':'Motor','transmission':'Transmisión','attachments':'Accesorios'}
    extra_fields=[{'label':label,'value':data[key]} for key,label in labels.items() if data.get(key) not in (None,'')]
    return {'machine':machine,'data':data,'assets':assets,'public':public,'version':version,'token':token,'category_name':category_name,'extra_fields':extra_fields,'provenance':{} if public else (version.data.get('provenance',{}) if version else machine.provenance)}

@login_required
def machine_sheet(request,pk):
    machine=owned(request,pk)
    version=get_object_or_404(MachineVersion,machine=machine,pk=request.GET['version']) if request.GET.get('version') else None
    return render(request,'portal/sheet.html',sheet_context(machine,version))

def public_sheet(request,token):
    pub=public_record(token)
    response=render(request,'portal/sheet.html',sheet_context(pub.machine,pub.version,True,token))
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
    if str(pk) not in pub.version.data.get('public_asset_ids',[]):raise Http404
    asset=get_object_or_404(Asset,pk=pk,machine=pub.machine,public_authorized=True,processing_status='ready')
    if asset.purpose in ['plate','document']:raise Http404
    return send_asset(asset)

@login_required
def machine_pdf(request,pk):
    from .pdf import build_pdf
    machine=owned(request,pk)
    version=get_object_or_404(MachineVersion,machine=machine,pk=request.GET['version']) if request.GET.get('version') else None
    context=sheet_context(machine,version)
    response=HttpResponse(build_pdf(context['machine'],context['data'],context['assets'],False,version),content_type='application/pdf')
    response['Content-Disposition']=f'attachment; filename="{machine.folio}.pdf"'
    return response

def public_pdf(request,token):
    from .pdf import build_pdf
    pub=public_record(token);context=sheet_context(pub.machine,pub.version,True,token)
    response=HttpResponse(build_pdf(context['machine'],context['data'],context['assets'],True,pub.version),content_type='application/pdf')
    response['Content-Disposition']=f'attachment; filename="{pub.machine.folio}.pdf"';response['Cache-Control']='no-store'
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
    qs=Submission.objects.select_related('machine','machine__owner','version')
    q=request.GET.get('q','').strip()[:100]
    if q:
        folio_query=q.removeprefix('IMC-').removeprefix('imc-').replace('-','')
        qs=qs.filter(Q(machine__title__icontains=q)|Q(machine__owner__email__icontains=q)|Q(machine__data__icontains=q)|Q(machine__id__istartswith=folio_query))
    state=request.GET.get('status',request.GET.get('estado',''))
    if state:qs=qs.filter(status=state)
    live=Machine.objects.filter(owner__is_test=False)
    counts={'users':User.objects.filter(is_test=False).count(),'pending':live.filter(status__in=['submitted','in_review']).count(),'advertisers':User.objects.filter(advertiser_status='pending',is_test=False).count(),'active':Publication.objects.filter(destination='share',enabled=True,machine__owner__is_test=False).count(),'sold':live.filter(availability='sold').count(),'abandoned':live.filter(status='draft',updated_at__lt=timezone.now()-timedelta(days=30)).count(),'failed_jobs':AnalysisJob.objects.filter(status='failed').count(),'tokens':AnalysisJob.objects.aggregate(total=Sum('input_tokens')+Sum('output_tokens'))['total'] or 0,'leads':Lead.objects.filter(status='new',is_test=False).count()}
    page=Paginator(qs,20).get_page(request.GET.get('page'))
    return render(request,'portal/operations.html',{'counts':counts,'submissions':page,'page_obj':page,'jobs':AnalysisJob.objects.select_related('machine').order_by('-created_at')[:10],'leads':Lead.objects.order_by('-created_at')[:10],'q':q})

@operator_required('portal.review_submission')
def review(request,pk):
    sub=get_object_or_404(Submission.objects.select_related('machine','version','machine__owner'),pk=pk)
    machine=sub.machine
    if request.method=='POST':
        action=request.POST.get('action')
        try:
            if action=='review':services.review_submission(sub,request.user,request.POST.get('decision'),request.POST.get('reason',''))
            elif action=='advertiser':services.set_advertiser_status(machine.owner,request.user,request.POST.get('status'),request.POST.get('reason',''))
            elif action=='message':
                body=request.POST.get('body','').strip()
                if not body or len(body)>5000:raise ValidationError('Escribe un mensaje de hasta 5 000 caracteres.')
                internal=request.POST.get('internal') in ['1','on','true']
                message=Message.objects.create(machine=machine,sender=request.user,body=body,internal=internal)
                services.audit(request.user,'message.internal' if internal else 'message.reply',message)
                if not internal:Notification.objects.create(user=machine.owner,machine=machine,kind='reply',subject=f'{machine.folio}: tienes una respuesta',body=body,channel='email')
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
            elif action=='export':return export_machine(request,machine.pk)
            else:raise ValidationError('Acción no válida.')
            flash.success(request,'La acción quedó guardada y registrada en el historial.')
            return redirect(f'/operaciones/solicitudes/{sub.pk}/')
        except ValidationError as exc:flash.error(request,' '.join(exc.messages))
    pub=machine.publications.filter(destination='share').first()
    return render(request,'portal/review.html',{'submission':sub,'machine':machine,'assets':machine.assets.filter(pk__in=sub.version.data.get('asset_ids',[])),'data':sub.version.data.get('data',{}),'provenance':sub.version.data.get('provenance',{}),'versions':machine.versions.all(),'messages_list':machine.messages.select_related('sender'),'publication':pub,'share_url':f'{settings.PUBLIC_URL}/ficha/{pub.token}/' if pub and pub.enabled else '', 'jobs':AnalysisJob.objects.filter(machine=machine).order_by('-created_at')})

@operator_required('portal.publish_machine')
@require_POST
def export_machine(request,pk):
    import zipfile
    from io import BytesIO
    from .pdf import build_pdf
    machine=get_object_or_404(Machine.objects.select_related('approved_version','owner'),pk=pk)
    if not machine.approved_version or machine.owner.advertiser_status!='approved' or machine.availability=='withdrawn':raise PermissionDenied
    version=machine.approved_version
    context=sheet_context(machine,version,True)
    output=BytesIO()
    exported={'schema_version':'1.0','folio':machine.folio,'machine_id':str(machine.pk),'version':version.number,'title':context['machine'].title,'category':version.data.get('category_name'),'data':context['data'],'availability':machine.availability,'assets':[],'destination_status':'exported','exported_at':timezone.now().isoformat()}
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('ficha.pdf',build_pdf(context['machine'],context['data'],context['assets'],True,version))
        for asset in context['assets']:
            f=asset.preview or asset.original
            suffix='.mp4' if asset.kind=='video' else '.jpg'
            path=f'fotografias/{asset.pk}{suffix}'
            with f.open('rb') as stream:archive.writestr(path,stream.read())
            exported['assets'].append({'id':str(asset.pk),'path':path,'kind':asset.kind,'cover':asset.is_cover})
        archive.writestr('publicacion.json',json.dumps(exported,ensure_ascii=False,indent=2))
        archive.writestr('LEEME.txt','Paquete autorizado para preparación editorial. Exportar NO publica automáticamente en imcmexico.com.mx. Registrar identificador/enlace externo solo tras confirmación verificable.')
    with transaction.atomic():
        current=Machine.objects.select_for_update().get(pk=machine.pk)
        if current.approved_version_id!=version.pk:raise ValidationError('La versión aprobada cambió durante la exportación. Vuelve a intentarlo.')
        publication,_=Publication.objects.select_for_update().get_or_create(machine=machine,destination='main')
        already_published=publication.status=='published' and publication.version_id==version.pk
        publication.version=version
        if not already_published:publication.status='exported'
        publication.enabled=False
        publication.save(update_fields=['version','status','enabled','updated_at'])
    services.audit(request.user,'publication.exported',machine,{'version':version.number})
    response=HttpResponse(output.getvalue(),content_type='application/zip');response['Content-Disposition']=f'attachment; filename="{machine.folio}-v{version.number}.zip"'
    return response
