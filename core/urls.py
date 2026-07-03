from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("lotes/", views.lote_list, name="lote_list"),
    path("lotes/crear/", views.lote_create, name="lote_create"),
    path("cultivos/", views.cultivo_list, name="cultivo_list"),
    path("cultivos/crear/", views.cultivo_create, name="cultivo_create"),
    path("planificaciones/", views.planificacion_list, name="planificacion_list"),
    path("planificaciones/ejecutar/", views.ejecutar_optimizacion, name="ejecutar_optimizacion"),
]
