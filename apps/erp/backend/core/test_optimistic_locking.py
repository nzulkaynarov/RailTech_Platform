"""F2.5 — optimistic locking mixin (If-Match / ETag). No DB; fake viewset base."""

from datetime import datetime, timezone

from django.test import SimpleTestCase
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from core.optimistic_locking import OptimisticLockingMixin


class _FakeObj:
    def __init__(self, pk, updated_at):
        self.pk = pk
        self.updated_at = updated_at


class _Base:
    """Stand-in for ModelViewSet.update — records that the write happened."""

    def update(self, request, *args, **kwargs):
        return Response({"ok": True})


class _ViewSet(OptimisticLockingMixin, _Base):
    def __init__(self, obj):
        self._obj = obj

    def get_object(self):
        return self._obj

    def get_serializer(self, instance):
        return type("S", (), {"data": {"id": instance.pk}})()


class OptimisticLockingTest(SimpleTestCase):
    def setUp(self):
        self.rf = APIRequestFactory()
        self.obj = _FakeObj(1, datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc))
        self.vs = _ViewSet(self.obj)

    def test_etag_weak_and_tracks_updated_at(self):
        e1 = self.vs._etag_for(self.obj)
        self.assertTrue(e1.startswith('W/"'))
        newer = _FakeObj(1, datetime(2026, 6, 22, 13, 0, 0, tzinfo=timezone.utc))
        self.assertNotEqual(e1, self.vs._etag_for(newer))

    def test_update_without_if_match_proceeds(self):
        resp = self.vs.update(self.rf.patch("/x", {}))
        self.assertEqual(resp.status_code, 200)

    def test_update_matching_if_match_proceeds_and_refreshes_etag(self):
        etag = self.vs._etag_for(self.obj)
        resp = self.vs.update(self.rf.patch("/x", {}, HTTP_IF_MATCH=etag))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["ETag"], etag)

    def test_update_stale_if_match_412(self):
        resp = self.vs.update(self.rf.patch("/x", {}, HTTP_IF_MATCH='W/"stale00000000"'))
        self.assertEqual(resp.status_code, 412)

    def test_retrieve_sets_etag(self):
        resp = self.vs.retrieve(self.rf.get("/x"))
        self.assertEqual(resp["ETag"], self.vs._etag_for(self.obj))
