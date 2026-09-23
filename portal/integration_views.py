"""Operator-facing handoffs; no implicit delivery or remote access."""
import json

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_GET

from .integration import ack_delivery, delivery_metadata
from .models import IntegrationDelivery, Machine, Publication
from .security import operator_required, staff_authorized


class ReceiptForm(forms.Form):
    delivery_id = forms.UUIDField(widget=forms.HiddenInput)
    receipt = forms.CharField(label='Acuse del sistema principal (JSON)', max_length=16000,
                              widget=forms.Textarea(attrs={'rows': 9}))
    evidence = forms.CharField(label='Dónde y cómo se verificó el acuse', min_length=12, max_length=4000,
                               widget=forms.Textarea(attrs={'rows': 3}))
    verified = forms.BooleanField(label='He comprobado el acuse en el sistema principal y que corresponde a esta ficha y versión.')

    def clean_receipt(self):
        try:
            value = json.loads(self.cleaned_data['receipt'])
        except (ValueError, RecursionError) as exc:
            raise forms.ValidationError('El acuse no contiene JSON válido.') from exc
        if not isinstance(value, dict):
            raise forms.ValidationError('El acuse debe ser un objeto JSON.')
        return value


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
    machines = Machine.objects.filter(approved_version__isnull=False).select_related('owner', 'approved_version').prefetch_related('publications')
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
                    ack_delivery(delivery, request.user, receipt_form.cleaned_data['receipt'], receipt_form.cleaned_data['evidence'])
                except ValidationError as exc:
                    receipt_form.add_error(None, ' '.join(exc.messages))
                else:
                    messages.success(request, 'Acuse verificado por el operador y registrado. Se conservan la entrega y su evidencia.')
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
    return render(request, 'portal/integration_detail.html', {
        'machine': machine, 'publication': publication, 'deliveries': deliveries[:30],
        'receipt_form': receipt_form, 'catalogue_form': catalogue_form,
        'catalogue_result': catalogue_result, 'identity': identity, 'pending_update': pending_update,
        'metadata_json': json.dumps(metadata, ensure_ascii=False, indent=2) if metadata else '',
        'last_ack': deliveries.filter(state='acknowledged').order_by('-acknowledged_at').first(),
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
