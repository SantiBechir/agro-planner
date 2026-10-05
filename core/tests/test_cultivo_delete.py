from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.roles import EDITOR_ROLE, set_functional_role
from core.models import (
    AsignacionLoteSlot, CampaniaHistorica, CompatibilidadCultivoSuelo,
    Costo, Cultivo, HistorialLoteCultivo, Planificacion,
    RendimientoCultivoSuelo, SlotSiembra,
)
from core.services.cultivos import crear_cultivo
from .service_support import ServiceTestCase


class CultivoDeleteTest(ServiceTestCase):
    def setUp(self):
        self.custom = crear_cultivo(self.editor, **self.datos_cultivo())
        self.url = reverse("cultivo_delete", args=[self.custom.pk])

    def test_creator_can_delete_custom_crop_and_its_configuration(self):
        self.client.force_login(self.editor)
        response = self.client.get(reverse("cultivo_list"))
        self.assertContains(response, self.url)
        self.assertNotContains(response, reverse("cultivo_delete", args=[self.cultivo.pk]))

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cultivo Soja eliminado.")
        self.assertFalse(Cultivo.objects.filter(pk=self.custom.pk).exists())
        self.assertFalse(Costo.objects.filter(cultivo_id=self.custom.pk).exists())
        self.assertFalse(RendimientoCultivoSuelo.objects.filter(cultivo_id=self.custom.pk).exists())
        self.assertFalse(CompatibilidadCultivoSuelo.objects.filter(cultivo_id=self.custom.pk).exists())

    def test_seeded_crop_and_other_users_crop_cannot_be_deleted(self):
        other = get_user_model().objects.create_user(
            email="other@services.test", first_name="Other", last_name="Editor",
        )
        set_functional_role(other, EDITOR_ROLE)
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse("cultivo_list")), self.url)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Cultivo.objects.filter(pk=self.custom.pk).exists())

        self.client.force_login(self.editor)
        seeded_url = reverse("cultivo_delete", args=[self.cultivo.pk])
        self.assertEqual(self.client.post(seeded_url).status_code, 403)
        self.assertTrue(Cultivo.objects.filter(pk=self.cultivo.pk).exists())

    def test_reader_cannot_delete_custom_crop(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertTrue(Cultivo.objects.filter(pk=self.custom.pk).exists())

    def test_referenced_crop_is_preserved(self):
        self.client.force_login(self.editor)
        history = CampaniaHistorica.objects.create(codigo="CH1", anio_inicio=2024)
        HistorialLoteCultivo.objects.create(
            lote=self.lote, cultivo=self.custom, campania_historica=history,
        )
        response = self.client.post(self.url)
        self.assertContains(response, "No se puede eliminar este cultivo")
        self.assertTrue(Cultivo.objects.filter(pk=self.custom.pk).exists())

        HistorialLoteCultivo.objects.filter(cultivo=self.custom).delete()
        plan = Planificacion.objects.create(nombre="Guardada", usuario=self.editor)
        slot = SlotSiembra.objects.create(codigo="T1", orden=1, campania=self.campania)
        AsignacionLoteSlot.objects.create(
            planificacion=plan, lote=self.lote, cultivo=self.custom, slot=slot,
            dia_siembra=1, dia_cosecha=100,
        )
        response = self.client.post(self.url)
        self.assertContains(response, "No se puede eliminar este cultivo")
        self.assertTrue(Cultivo.objects.filter(pk=self.custom.pk).exists())
