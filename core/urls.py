from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("lotes/", views.lote_list, name="lote_list"),
    path("cultivos/", views.cultivo_list, name="cultivo_list"),
    path("planificaciones/", views.planificacion_list, name="planificacion_list"),
    path("planificaciones/ejecutar/", views.ejecutar_optimizacion, name="ejecutar_optimizacion"),
    path("planificaciones/<int:pk>/estado/", views.planificacion_status, name="planificacion_status"),
    path("planificaciones/<int:pk>/estado/partial/", views.planificacion_status_partial, name="planificacion_status_partial"),
]
