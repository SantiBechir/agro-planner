"""Entradas públicas compatibles de las vistas de core."""

from accounts.views import login_view, logout_view
from .dashboard import home
from .lotes import lote_list, lote_create, lote_update, lote_toggle, lote_historial_add, lote_historial_delete
from .cultivos import cultivo_list, cultivo_create
from .costos import costo_list
from .planificaciones import planificacion_list, ejecutar_optimizacion, planificacion_status, planificacion_status_partial

__all__ = [
    "login_view",
    "logout_view",
    "home",
    "lote_list",
    "lote_create",
    "lote_update",
    "lote_toggle",
    "lote_historial_add",
    "lote_historial_delete",
    "cultivo_list",
    "cultivo_create",
    "costo_list",
    "planificacion_list",
    "ejecutar_optimizacion",
    "planificacion_status",
    "planificacion_status_partial",
]
