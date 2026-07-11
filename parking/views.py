from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from core.models import log_activity

from .forms import FloorForm, SlotFilterForm, SlotForm
from .models import Floor, Slot, SlotStatus
from .services import build_window, facility_floors, slots_with_availability


def _resolve_filters(request):
    """Parse the slot filter form from GET params into a service kwargs dict."""
    form = SlotFilterForm(request.GET or None)
    filters = {
        "floor": None,
        "vehicle_type": None,
        "only_available": False,
        "start": None,
        "end": None,
    }
    if form.is_valid():
        cd = form.cleaned_data
        filters["floor"] = cd.get("floor")
        filters["vehicle_type"] = cd.get("vehicle_type") or None
        filters["only_available"] = cd.get("availability") == "available"
        filters["start"], filters["end"] = build_window(
            cd.get("date"), cd.get("start_time"), cd.get("end_time")
        )
    return form, filters


# --- Public facility guide --------------------------------------------------

def facility(request):
    """Public 'Facility Guide' — floors with photos + live availability.

    Repurposes the legacy static landing gallery and the p1–p4 area pages into
    one responsive, data-driven page.
    """
    return render(request, "parking/facility.html", {"floors": facility_floors()})


# --- Customer-facing real-time slot monitoring ------------------------------

def _can_reserve(request):
    """Only signed-in customers may book; carry filter times into the booking."""
    return request.user.is_authenticated and getattr(
        request.user, "is_customer_role", False
    )


def slots(request):
    form, filters = _resolve_filters(request)
    slot_list, summary = slots_with_availability(**filters)
    return render(
        request,
        "parking/slots.html",
        {
            "form": form,
            "slots": slot_list,
            "summary": summary,
            "window": (filters["start"], filters["end"]),
            "querystring": request.GET.urlencode(),
            "can_reserve": _can_reserve(request),
            "reserve_query": request.GET.urlencode(),
        },
    )


def slots_partial(request):
    """Just the slot grid — polled by the page for auto-refresh."""
    _, filters = _resolve_filters(request)
    slot_list, summary = slots_with_availability(**filters)
    return render(
        request,
        "parking/_slot_grid.html",
        {
            "slots": slot_list,
            "summary": summary,
            "window": (filters["start"], filters["end"]),
            "can_reserve": _can_reserve(request),
            "reserve_query": request.GET.urlencode(),
        },
    )


def slots_api(request):
    """Machine-readable availability snapshot (JSON)."""
    _, filters = _resolve_filters(request)
    slot_list, summary = slots_with_availability(**filters)
    return JsonResponse(
        {
            "summary": summary,
            "slots": [
                {
                    "id": s.id,
                    "code": s.code,
                    "floor": s.floor.name,
                    "floor_code": s.floor.code,
                    "type": s.slot_type,
                    "status": s.status,
                    "available": s.available,
                }
                for s in slot_list
            ],
        }
    )


# --- Admin: floor management ------------------------------------------------

@admin_required
def floor_list(request):
    floors = Floor.objects.all()
    return render(request, "parking/manage/floor_list.html", {"floors": floors})


@admin_required
def floor_add(request):
    form = FloorForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        floor = form.save()
        log_activity("floor.created", floor.name, actor=request.user, request=request)
        messages.success(request, "Floor added.")
        return redirect("parking:floor_list")
    return render(
        request,
        "parking/manage/floor_form.html",
        {"form": form, "heading": "Add floor"},
    )


@admin_required
def floor_edit(request, pk):
    floor = get_object_or_404(Floor, pk=pk)
    form = FloorForm(request.POST or None, instance=floor)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Floor updated.")
        return redirect("parking:floor_list")
    return render(
        request,
        "parking/manage/floor_form.html",
        {"form": form, "heading": "Edit floor"},
    )


# --- Admin: slot management -------------------------------------------------

@admin_required
def slot_list(request):
    slot_qs = Slot.objects.select_related("floor")
    floor_id = request.GET.get("floor")
    if floor_id:
        slot_qs = slot_qs.filter(floor_id=floor_id)
    return render(
        request,
        "parking/manage/slot_list.html",
        {"slots": slot_qs, "floors": Floor.objects.all(), "current_floor": floor_id},
    )


@admin_required
def slot_add(request):
    form = SlotForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        slot = form.save()
        log_activity("slot.created", str(slot), actor=request.user, request=request)
        messages.success(request, "Slot added.")
        return redirect("parking:slot_list")
    return render(
        request,
        "parking/manage/slot_form.html",
        {"form": form, "heading": "Add slot"},
    )


@admin_required
def slot_edit(request, pk):
    slot = get_object_or_404(Slot, pk=pk)
    form = SlotForm(request.POST or None, instance=slot)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Slot updated.")
        return redirect("parking:slot_list")
    return render(
        request,
        "parking/manage/slot_form.html",
        {"form": form, "heading": f"Edit slot {slot.code}"},
    )


@admin_required
@require_POST
def slot_toggle(request, pk):
    """Flip a slot between AVAILABLE and MAINTENANCE."""
    slot = get_object_or_404(Slot, pk=pk)
    if slot.status == SlotStatus.AVAILABLE:
        slot.status = SlotStatus.MAINTENANCE
    else:
        slot.status = SlotStatus.AVAILABLE
    slot.save(update_fields=["status"])
    log_activity(
        "slot.status_changed",
        f"{slot.code} → {slot.get_status_display()}",
        actor=request.user,
        request=request,
    )
    messages.success(request, f"{slot.code} is now {slot.get_status_display()}.")
    return redirect(request.META.get("HTTP_REFERER") or "parking:slot_list")
