"""FIX-42 (F-5): удаление категории с подкатегориями не стирает ветку каскадом.

`Category.parent` был `CASCADE`: «Удалить» в настройках сносило всё поддерево. Теперь `PROTECT`: сначала
подкатегории переносят или удаляют сами, API отвечает 400 `CATEGORY_HAS_CHILDREN`. Права на правку дерева —
`settings.edit` или `catalog.manage` (раздел «Категории» в Settings Hub показывался по несуществующему `catalog.edit`).
"""

import pytest
from django.db.models import ProtectedError
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Category, Product

pytestmark = pytest.mark.django_db


def _url(category):
    return f"/api/v1/catalog/categories/{category.pk}/"


@pytest.fixture
def tree():
    root = Category.objects.create(name="Запчасти")
    child = Category.objects.create(name="Подшипники", parent=root)
    grandchild = Category.objects.create(name="Роликовые", parent=child)
    return root, child, grandchild


def _staff_client(grant, *codes):
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    company = Company.objects.create(name="ООО Фикс42", inn="9420000001")
    company.types.add(supplier_type)
    user = CustomUser.objects.create_user(email="f42@seller.test", username="f42@seller.test", password="pw")
    CompanyMember.objects.create(user=user, company=company, role=role, is_active=True, is_primary=True)
    grant(user, *codes)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def test_delete_with_children_is_refused_and_keeps_the_tree(grant, tree):
    root, child, grandchild = tree

    response = _staff_client(grant, "settings.edit").delete(_url(root))

    assert response.status_code == 400
    assert response.json() == {"detail": "CATEGORY_HAS_CHILDREN"}
    assert Category.objects.filter(pk__in=[root.pk, child.pk, grandchild.pk]).count() == 3
    assert Category.objects.get(pk=child.pk).parent_id == root.pk


def test_leaf_can_be_deleted_and_then_its_parent(grant, tree):
    root, child, grandchild = tree
    client = _staff_client(grant, "settings.edit")

    assert client.delete(_url(grandchild)).status_code == 204
    assert client.delete(_url(child)).status_code == 204
    assert client.delete(_url(root)).status_code == 204
    assert not Category.objects.filter(pk__in=[root.pk, child.pk, grandchild.pk]).exists()


def test_children_moved_away_unblocks_the_delete(grant, tree):
    root, child, _ = tree
    client = _staff_client(grant, "settings.edit")

    assert client.patch(_url(child), {"parent": None}, format="json").status_code == 200

    assert client.delete(_url(root)).status_code == 204
    assert Category.objects.filter(pk=child.pk, parent__isnull=True).exists()


def test_leaf_with_products_still_detaches_them(grant):
    """Товары не стираются вместе с категорией (SET_NULL) — это прежнее поведение, оно не менялось."""
    leaf = Category.objects.create(name="Лист")
    product = Product.objects.create(name="Карточка", category=leaf)

    assert _staff_client(grant, "settings.edit").delete(_url(leaf)).status_code == 204

    product.refresh_from_db()
    assert product.category_id is None


def test_orm_delete_is_protected_too(tree):
    """Не только API: удаление через ORM/админку тоже не уносит ветку."""
    root = tree[0]

    with pytest.raises(ProtectedError):
        root.delete()

    assert Category.objects.filter(pk__in=[r.pk for r in tree]).count() == 3


def test_catalog_manager_edits_the_tree_without_settings_edit(grant, tree):
    _, _, grandchild = tree
    client = _staff_client(grant, "catalog.manage")

    assert client.patch(_url(grandchild), {"name": "Роликовые 2"}, format="json").status_code == 200
    assert client.post("/api/v1/catalog/categories/", {"name": "Новая"}, format="json").status_code == 201
    assert client.delete(_url(grandchild)).status_code == 204


def test_member_without_catalog_rights_cannot_touch_the_tree(grant, tree):
    _, _, grandchild = tree
    client = _staff_client(grant, "quote.build")

    assert client.patch(_url(grandchild), {"name": "Взлом"}, format="json").status_code == 403
    assert client.delete(_url(grandchild)).status_code == 403
    assert Category.objects.filter(pk=grandchild.pk, name="Роликовые").exists()
