from django.test import TestCase
from accounts.models import CustomUser, Company
from crm.models import Deal


class DealBasicTest(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name='Test Company', inn='123456789'
        )
        self.user = CustomUser.objects.create_user(
            username='testmanager',
            email='testmanager@test.com',
            password='password123',
        )
        self.deal = Deal.objects.create(
            company=self.company, client=self.user
        )

    def test_deal_creation(self):
        """Verify that a Deal can be created successfully."""
        self.assertIsNotNone(self.deal.pk)
        self.assertEqual(self.deal.company, self.company)
        self.assertEqual(self.deal.client, self.user)
