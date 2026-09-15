from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.models import Cultivo, Lote, Planificacion


@login_required(login_url="login")
def home(request):
    total_lotes = Lote.objects.count()
    total_cultivos = Cultivo.objects.count()
    total_planificaciones = Planificacion.objects.count()

    context = {
        "total_lotes": total_lotes,
        "total_cultivos": total_cultivos,
        "total_planificaciones": total_planificaciones,
    }
    return render(request, "core/index.html", context)
