from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("lotes/", views.lote_list, name="lote_list"),
    path("lotes/crear/", views.lote_create, name="lote_create"),
    path("lotes/<int:pk>/editar/", views.lote_update, name="lote_update"),
    path("lotes/<int:pk>/toggle/", views.lote_toggle, name="lote_toggle"),
    path("lotes/<int:pk>/historial/", views.lote_historial_add, name="lote_historial_add"),
    path("lotes/<int:pk>/historial/<int:anio_inicio>/eliminar/", views.lote_historial_delete, name="lote_historial_delete"),
    path("cultivos/", views.cultivo_list, name="cultivo_list"),
    path("cultivos/crear/", views.cultivo_create, name="cultivo_create"),
    path("cultivos/<int:pk>/eliminar/", views.cultivo_delete, name="cultivo_delete"),
    path("cultivos/<int:pk>/desactivar/", views.cultivo_desactivar, name="cultivo_desactivar"),
    path("planificaciones/cultivos/<int:pk>/limites/guardar/", views.planificacion_limites_update, name="planificacion_limites_update"),
    path("costos/", views.costo_list, name="costo_list"),
    path("planificaciones/", views.planificacion_list, name="planificacion_list"),
    path("planificaciones/nueva/", views.planificacion_configuracion, name="planificacion_configuracion"),
    path("planificaciones/<int:pk>/datos/", views.planificacion_datos, name="planificacion_datos"),
    path("planificaciones/ejecutar/", views.ejecutar_optimizacion, name="ejecutar_optimizacion"),
    path("planificaciones/<int:pk>/estado/", views.planificacion_status, name="planificacion_status"),
    path("planificaciones/<int:pk>/estado/partial/", views.planificacion_status_partial, name="planificacion_status_partial"),
]
