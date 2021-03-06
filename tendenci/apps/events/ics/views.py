from datetime import datetime
from django.shortcuts import render_to_response, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.template import RequestContext
from tendenci.apps.base.http import Http403
from tendenci.apps.events.ics.models import ICS


@login_required
def status(request, ics_id, template_name='ics/ics_status.html'):
    """Checks if an ics is completed.
    """

    if not request.user.is_superuser:
        raise Http403

    ics = get_object_or_404(ICS, pk=ics_id)

    return render_to_response(template_name, {
        'ics': ics,
        'datetime': datetime,
    }, context_instance=RequestContext(request))


@login_required
def download(request, ics_id):
    """Returns the ics file if it exists"""

    if not request.user.is_superuser:
        raise Http403

    ics = get_object_or_404(ICS, pk=ics_id)

    if ics.status == "completed":
        response = ics.result
        return response

    return redirect("ics.status", ics_id)
