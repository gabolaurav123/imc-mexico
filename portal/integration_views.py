"""Operator-facing handoffs; no implicit delivery or remote access."""
import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_GET

from .integration import ack_delivery, delivery_metadata, record_manual_review, set_imc_media_selection
from .models import Asset, IntegrationDelivery, Machine, Publication
from .security import operator_required, staff_authorized


class ReceiptForm(forms.Form):
    delivery_id = forms.UUIDField(widget=forms.HiddenInput)
    receipt = forms.CharField(label='Acuse del sistema principal (JSON)', max_length=16000,
                              widget=forms.Textarea(attrs={'rows': 9}))
    evidence = forms.CharField(label='Dónde y cómo se verificó el acuse', min_length=12, max_length=4000,
                               widget=forms.Textarea(attrs={'rows': 3}))
    imc_advertiser = forms.CharField(label='Usuario o anunciante real usado en IMC', min_length=2, max_length=250)
    verified = forms.BooleanField(label='He comprobado el acuse en el sistema principal y que corresponde a esta ficha y versión.')

    def clean_receipt(self):
        try:
            value = json.loads(self.cleaned_data['receipt'])
        except (ValueError, RecursionError) as exc:
            raise forms.ValidationError('El acuse no contiene JSON válido.') from exc
        if not isinstance(value, dict):
            raise forms.ValidationError('El acuse debe ser un objeto JSON.')
        return value


class ManualReviewForm(forms.Form):
    delivery_id = forms.UUIDField(widget=forms.HiddenInput)
    imc_advertiser = forms.CharField(label='Usuario o anunciante de destino en IMC', min_length=2, max_length=250)
    duplicate_result = forms.ChoiceField(label='Resultado de la revisión de duplicados en IMC', choices=[
        ('not_checked', 'No revisado todavía'), ('partial', 'Búsqueda parcial o inconclusa'),
        ('no_match', 'Sin coincidencia en lo revisado'), ('match', 'Coincidencia encontrada'),
        ('update', 'Actualizar un registro existente'), ('legitimate', 'Caso legítimo; no es duplicado'),
    ])
    evidence = forms.CharField(label='Qué se comprobó y dónde', min_length=12, max_length=4000,
                               widget=forms.Textarea(attrs={'rows': 3}))
    limitations = forms.CharField(label='Límites de la revisión', max_length=4000, required=False,
                                  widget=forms.Textarea(attrs={'rows': 2}))


def _copy_blocks(machine, snapshot):
    data = snapshot.get('data', {}) if isinstance(snapshot, dict) else {}
    def value(key, fallback='Pendiente'):
        item = data.get(key)
        return str(item).strip() if item not in (None, '') else fallback
    exact_year = value('year')
    if exact_year == 'Pendiente' and (data.get('estimated_year_from') or data.get('estimated_year_to')):
        exact_year = 'Pendiente; existe un rango local, no copiarlo como año exacto'
    price = value('price')
    if price != 'Pendiente':
        price = f"{price} {value('currency', 'USD')}"
    return [
        ('Datos del equipo', '\n'.join([
            f"Tipo de máquina: {snapshot.get('category_name') or 'Pendiente'}",
            f"Marca: {value('brand')}", f"Modelo: {value('model')}",
            f"Número de serie: {value('serial')}",
        ])),
        ('Datos comerciales y ubicación', '\n'.join([
            f"Precio solicitado: {price}", f"Año exacto: {exact_year}",
            f"Horas de uso: {value('hours')}", f"Ubicación: {value('location')}",
        ])),
        ('Descripción pública', value('description', 'Pendiente de redactar o confirmar.')),
    ]


class CatalogueCheckForm(forms.Form):
    catalogue = forms.CharField(label='Extracto autorizado del catálogo (JSON)', max_length=500000,
                                widget=forms.Textarea(attrs={'rows': 6}))

    def clean_catalogue(self):
        try:
            value = json.loads(self.cleaned_data['catalogue'])
        except (ValueError, RecursionError) as exc:
            raise forms.ValidationError('El catálogo no contiene JSON válido.') from exc
        if not isinstance(value, list) or len(value) > 3000:
            raise forms.ValidationError('Introduce una lista de hasta 3 000 correspondencias autorizadas.')
        return value


@operator_required('portal.publish_machine')
@require_GET
def integration_index(request):
    machines = Machine.objects.filter(approved_version__isnull=False).select_related('owner', 'approved_version').prefetch_related(
        Prefetch('publications', queryset=Publication.objects.filter(destination='main')))
    q = request.GET.get('q', '').strip()[:180]
    if q:
        machines = machines.filter(Q(title__icontains=q) | Q(publications__external_id__icontains=q) |
                                   Q(publications__external_reference__icontains=q)).distinct()
    page = Paginator(machines, 25).get_page(request.GET.get('page'))
    return render(request, 'portal/integration_index.html', {'page_obj': page, 'q': q})


@operator_required('portal.publish_machine')
@require_http_methods(['GET', 'POST'])
def integration_detail(request, pk):
    machine = get_object_or_404(Machine.objects.select_related('owner', 'approved_version'), pk=pk)
    publication = machine.publications.select_related('current_delivery').filter(destination='main').first()
    deliveries = IntegrationDelivery.objects.filter(publication__machine=machine).select_related('version', 'acknowledged_by')
    selected = publication.current_delivery if publication and publication.current_delivery_id else deliveries.first()
    receipt_form = ReceiptForm(initial={'delivery_id': selected.pk}) if selected else None
    manual_review_form = ManualReviewForm(initial={'delivery_id': selected.pk}) if selected else None
    catalogue_form = CatalogueCheckForm()
    catalogue_result = None
    snapshot = machine.approved_version.data if machine.approved_version_id else {}
    identity = {'type': snapshot.get('category_name', ''),
                'brand': snapshot.get('data', {}).get('brand', ''),
                'model': snapshot.get('data', {}).get('model', '')}
    if request.method == 'POST':
        if request.POST.get('action') == 'acknowledge':
            receipt_form = ReceiptForm(request.POST)
            if receipt_form.is_valid():
                delivery = get_object_or_404(deliveries, pk=receipt_form.cleaned_data['delivery_id'])
                try:
                    receipt_form.cleaned_data['receipt']['imc_advertiser'] = receipt_form.cleaned_data['imc_advertiser']
                    ack_delivery(delivery, request.user, receipt_form.cleaned_data['receipt'], receipt_form.cleaned_data['evidence'])
                except ValidationError as exc:
                    receipt_form.add_error(None, ' '.join(exc.messages))
                else:
                    messages.success(request, 'Acuse verificado por el operador y registrado. Se conservan la entrega y su evidencia.')
                    return redirect('integration_detail', pk=machine.pk)
        elif request.POST.get('action') == 'manual_review':
            manual_review_form = ManualReviewForm(request.POST)
            if manual_review_form.is_valid():
                delivery = get_object_or_404(deliveries, pk=manual_review_form.cleaned_data['delivery_id'])
                try:
                    record_manual_review(delivery, request.user,
                        imc_advertiser=manual_review_form.cleaned_data['imc_advertiser'],
                        duplicate_result=manual_review_form.cleaned_data['duplicate_result'],
                        evidence=manual_review_form.cleaned_data['evidence'],
                        limitations=manual_review_form.cleaned_data['limitations'])
                except ValidationError as exc:
                    manual_review_form.add_error(None, ' '.join(exc.messages))
                else:
                    messages.success(request, 'La revisión manual quedó registrada. Preparar o copiar no publica en IMC.')
                    return redirect('integration_detail', pk=machine.pk)
        elif request.POST.get('action') == 'select_imc_media':
            try:
                set_imc_media_selection(machine, request.user,
                                        [value for value in request.POST.getlist('imc_asset_slots') if value])
            except ValidationError as exc:
                messages.error(request, ' '.join(exc.messages))
            else:
                messages.success(request, 'La selección para IMC quedó guardada para esta versión. No cambia la ficha compartida ni publica en IMC.')
                return redirect('integration_detail', pk=machine.pk)
        elif request.POST.get('action') == 'catalogue_check':
            catalogue_form = CatalogueCheckForm(request.POST)
            if catalogue_form.is_valid():
                from .integration_catalogue import resolve_catalogue
                catalogue_result = resolve_catalogue(identity, catalogue_form.cleaned_data['catalogue'])
        else:
            raise Http404
    metadata = delivery_metadata(selected) if selected else None
    # The canonical remote ID remains valid for consultation even if a later
    # availability/content update still needs a new acknowledgement.
    pending_update = bool(publication and publication.acknowledged_at and
                          (not selected or selected.state != 'acknowledged' or
                           selected.version_id != machine.approved_version_id or
                           selected.payload.get('availability') != machine.availability))
    selected_ids = []
    if publication and publication.imc_selection_version_id == machine.approved_version_id:
        selected_ids = [str(asset_id) for asset_id in publication.imc_asset_ids]
    version_asset_ids = snapshot.get('asset_ids', []) if isinstance(snapshot, dict) else []
    plate_ids = set(snapshot.get('private_plate_asset_ids', []) if isinstance(snapshot, dict) else [])
    from .services import detected_plate_asset_ids
    plate_ids |= detected_plate_asset_ids(machine)
    imc_media_assets = list(machine.assets.filter(pk__in=version_asset_ids).order_by('position', 'created_at'))
    image_slot = 0
    selected_slots = {}
    by_id = {str(asset.pk): asset for asset in imc_media_assets}
    for asset_id in selected_ids:
        asset = by_id.get(asset_id)
        if not asset:
            continue
        if asset.kind == 'video':
            selected_slots[asset_id] = 'video'
        else:
            image_slot += 1
            selected_slots[asset_id] = image_slot
    for asset in imc_media_assets:
        asset.imc_slot = selected_slots.get(str(asset.pk), '')
        asset.imc_allowed = (asset.processing_status == 'ready' and asset.public_authorized
                             and asset.purpose in ('general', 'detail') and str(asset.pk) not in plate_ids)
    return render(request, 'portal/integration_detail.html', {
        'machine': machine, 'publication': publication, 'deliveries': deliveries[:30],
        'receipt_form': receipt_form, 'manual_review_form': manual_review_form, 'catalogue_form': catalogue_form,
        'catalogue_result': catalogue_result, 'identity': identity, 'pending_update': pending_update,
        'metadata_json': json.dumps(metadata, ensure_ascii=False, indent=2) if metadata else '',
        'last_ack': deliveries.filter(state='acknowledged').order_by('-acknowledged_at').first(),
        'copy_blocks': _copy_blocks(machine, snapshot),
        'private_notes': snapshot.get('data', {}).get('notes', ''),
        'manual_events': (selected.manual_metadata.get('events', []) if selected and isinstance(selected.manual_metadata, dict) else []),
        'imc_media_assets': imc_media_assets,
    })


@login_required
@require_GET
def main_record_return(request):
    """Reciprocal consultation by acknowledged ID, always behind local permission."""
    external_id = request.GET.get('id', '')
    if not external_id or len(external_id) > 200:
        raise Http404
    publication = get_object_or_404(Publication.objects.select_related('machine'),
                                   destination='main', external_id=external_id,
                                   acknowledged_at__isnull=False, machine__deleted_at__isnull=True)
    if publication.machine.owner_id != request.user.pk and not (
            staff_authorized(request.user) and request.user.has_perm('portal.view_machine')):
        raise Http404
    return redirect('machine_sheet', pk=publication.machine_id)
