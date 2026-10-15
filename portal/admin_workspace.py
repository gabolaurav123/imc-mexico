"""Focused, permission-scoped workspaces for the operations team.

These views deliberately keep account connection records separate from customer
work.  An address observed during a connection is a technical trace, not a
location or a statement about who was using the network.
"""
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import (AccountAccess, AccountRequest, Brand, Category, EquipmentModel,
                     Lead, Machine, Submission, User, WorkflowStatus)
from .security import operator_required


def _has(user, *permissions):
    return any(user.has_perm(f"portal.{permission}") for permission in permissions)


def _people_queryset(query="", *, include_work_counts=False, include_submission_counts=False):
    """External, non-test accounts only; no technical guest principals."""
    people = User.objects.filter(is_test=False, is_guest=False, is_staff=False)
    if query:
        people = people.filter(
            Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(company__icontains=query)
            | Q(phone__icontains=query)
        )
    annotations = {}
    if include_work_counts:
        active_machine = Q(machines__deleted_at__isnull=True)
        annotations.update({
            "last_activity": Max("machines__updated_at"),
            "machine_total": Count("machines", filter=active_machine, distinct=True),
            "draft_total": Count("machines", filter=active_machine & Q(machines__status=WorkflowStatus.DRAFT), distinct=True),
            "waiting_total": Count("machines", filter=active_machine & Q(machines__status__in=["submitted", "in_review", "changes_requested"]), distinct=True),
        })
    if include_submission_counts:
        annotations["submission_total"] = Count(
            "machines__submissions",
            filter=Q(machines__deleted_at__isnull=True),
            distinct=True,
        )
    if annotations:
        people = people.annotate(**annotations)
    return people.order_by("-last_activity", "-date_joined", "email") if include_work_counts else people.order_by("-date_joined", "email")


@require_GET
@operator_required()
def people_workspace(request):
    """One row per person, with work counts only when the role can read them."""
    if not _has(request.user, "view_user", "change_user", "manage_advertisers"):
        raise PermissionDenied
    query = request.GET.get("q", "").strip()[:100]
    can_view_machines = _has(request.user, "view_machine", "change_machine")
    can_view_submissions = _has(request.user, "view_submission", "change_submission", "review_submission")
    people = _people_queryset(
        query,
        include_work_counts=can_view_machines,
        include_submission_counts=can_view_submissions,
    )
    page = Paginator(people, 25).get_page(request.GET.get("page"))
    return render(request, "portal/admin_people_workspace.html", {
        "people": page,
        "page_obj": page,
        "q": query,
        "can_view_machines": can_view_machines,
        "can_view_submissions": can_view_submissions,
        "can_view_accesses": _has(request.user, "view_accountaccess"),
    })


@require_GET
@operator_required()
def person_workspace(request, pk):
    """All private operational records for one external account, permission by permission."""
    if not _has(request.user, "view_user", "change_user", "manage_advertisers"):
        raise PermissionDenied
    person = get_object_or_404(
        User.objects.filter(is_test=False, is_guest=False, is_staff=False),
        pk=pk,
    )
    can_view_machines = _has(request.user, "view_machine", "change_machine")
    can_view_submissions = _has(request.user, "view_submission", "change_submission", "review_submission")
    can_view_accesses = _has(request.user, "view_accountaccess")
    can_view_leads = _has(request.user, "view_lead", "change_lead")
    can_view_account_requests = _has(request.user, "view_accountrequest", "change_accountrequest")
    machine_queryset = (
        Machine.objects.filter(owner=person)
        .select_related("category")
        .order_by("-updated_at")
        if can_view_machines else Machine.objects.none()
    )
    submission_queryset = (
        Submission.objects.filter(machine__owner=person, machine__deleted_at__isnull=True)
        .select_related("machine", "version")
        .order_by("-created_at")
        if can_view_submissions else Submission.objects.none()
    )
    # The two work streams can grow independently. Separate query parameters
    # keep reviewing a later page of submissions from resetting the machine
    # history, and vice versa.
    machines = Paginator(machine_queryset, 25).get_page(request.GET.get("machines_page"))
    submissions = Paginator(submission_queryset, 25).get_page(request.GET.get("submissions_page"))
    accesses = (
        AccountAccess.objects.filter(user=person, expires_at__gt=timezone.now())
        .order_by("-created_at")[:20]
        if can_view_accesses else AccountAccess.objects.none()
    )
    lead_queryset = (
        Lead.objects.filter(user=person, is_test=False).select_related("machine", "assigned_to")
        .order_by("-created_at")
        if can_view_leads else Lead.objects.none()
    )
    account_request_queryset = (
        AccountRequest.objects.filter(user=person).order_by("-created_at")
        if can_view_account_requests else AccountRequest.objects.none()
    )
    leads = Paginator(lead_queryset, 25).get_page(request.GET.get("leads_page"))
    account_requests = Paginator(account_request_queryset, 25).get_page(
        request.GET.get("account_requests_page")
    )
    return render(request, "portal/admin_person_detail.html", {
        "person": person,
        "machines": machines,
        "submissions": submissions,
        "accesses": accesses,
        "leads": leads,
        "account_requests": account_requests,
        "can_view_machines": can_view_machines,
        "can_view_submissions": can_view_submissions,
        "can_view_accesses": can_view_accesses,
        "can_view_leads": can_view_leads,
        "can_view_account_requests": can_view_account_requests,
        "can_change_person": request.user.has_perm("portal.change_user"),
        "can_change_machine": request.user.has_perm("portal.change_machine"),
        "can_change_lead": request.user.has_perm("portal.change_lead"),
        "can_change_account_request": request.user.has_perm("portal.change_accountrequest"),
    })


@require_GET
@operator_required()
def machinery_workspace(request):
    """A small operational inventory, not another unbounded dashboard."""
    if not _has(request.user, "view_machine", "change_machine"):
        raise PermissionDenied
    query = request.GET.get("q", "").strip()[:100]
    machines = Machine.objects.select_related("owner", "category").filter(owner__is_test=False, owner__is_guest=False)
    if query:
        machines = machines.filter(Q(title__icontains=query) | Q(owner__email__icontains=query) | Q(owner__company__icontains=query))
    state = request.GET.get("status", "")
    statuses = dict(WorkflowStatus.choices)
    if state in statuses:
        machines = machines.filter(status=state)
    else:
        state = ""
    page = Paginator(machines.order_by("-updated_at"), 25).get_page(request.GET.get("page"))
    return render(request, "portal/admin_machinery_workspace.html", {
        "machines": page,
        "page_obj": page,
        "q": query,
        "status": state,
        "statuses": WorkflowStatus.choices,
        "can_change_machine": request.user.has_perm("portal.change_machine"),
        "can_view_people": _has(request.user, "view_user", "change_user", "manage_advertisers"),
    })


@require_GET
@operator_required("portal.view_accountaccess")
def connections_workspace(request):
    """Short-lived connection history, presented without geo-IP inference."""
    query = request.GET.get("q", "").strip()[:100]
    accesses = AccountAccess.objects.filter(
        expires_at__gt=timezone.now(),
        user__is_test=False,
        user__is_guest=False,
        user__is_staff=False,
    ).select_related("user")
    if query:
        accesses = accesses.filter(
            Q(user__email__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(connection_ip__icontains=query)
            | Q(forwarded_ip__icontains=query)
        )
    event = request.GET.get("event", "")
    event_choices = dict(AccountAccess._meta.get_field("event").choices)
    if event in event_choices:
        accesses = accesses.filter(event=event)
    else:
        event = ""
    page = Paginator(accesses.order_by("-created_at"), 25).get_page(request.GET.get("page"))
    return render(request, "portal/admin_connections_workspace.html", {
        "accesses": page,
        "page_obj": page,
        "q": query,
        "event": event,
        "event_choices": AccountAccess._meta.get_field("event").choices,
        "can_view_people": _has(request.user, "view_user", "change_user", "manage_advertisers"),
    })


@require_GET
@operator_required()
def model_catalogue_workspace(request):
    """The editable catalogue of equipment identities, distinct from model evidence."""
    allowed = _has(request.user, "view_category", "change_category", "view_brand", "change_brand", "view_equipmentmodel", "change_equipmentmodel")
    if not allowed:
        raise PermissionDenied
    query = request.GET.get("q", "").strip()[:100]
    can_view_models = _has(request.user, "view_equipmentmodel", "change_equipmentmodel")
    models = EquipmentModel.objects.select_related("brand", "category") if can_view_models else EquipmentModel.objects.none()
    if query and can_view_models:
        models = models.filter(Q(name__icontains=query) | Q(brand__name__icontains=query) | Q(category__name__icontains=query))
    page = Paginator(models, 25).get_page(request.GET.get("page"))
    return render(request, "portal/admin_model_catalogue.html", {
        "models": page,
        "page_obj": page,
        "q": query,
        "can_view_models": can_view_models,
        "can_change_models": request.user.has_perm("portal.change_equipmentmodel"),
        "category_count": Category.objects.count() if _has(request.user, "view_category", "change_category") else None,
        "brand_count": Brand.objects.count() if _has(request.user, "view_brand", "change_brand") else None,
    })
