from django.contrib.auth.models import User
from django.test import TestCase

from market.models import Listing, Message, Thread

PW = "Zx9!longpass"


class Base(TestCase):
    def setUp(self):
        self.alex = User.objects.create_user("tess", "a@c.edu", PW)
        self.jordan = User.objects.create_user("jules", "j@c.edu", PW)
        self.mallory = User.objects.create_user("mallory", "m@c.edu", PW)
        self.listing = Listing.objects.create(
            owner=self.alex, title="Charger", description="d", price="18.00",
            category="electronics", seller_note="locker code SWAP-7741",
        )
        self.thread = Thread.objects.create(listing=self.listing, buyer=self.jordan)
        Message.objects.create(thread=self.thread, sender=self.jordan, body="still here?")

    def login(self, user):
        self.client.login(username=user.username, password=PW)


class PrivilegeEscalation(Base):
    def test_profile_cannot_set_is_staff(self):
        self.login(self.mallory)
        self.client.post("/profile/", {"first_name": "M", "last_name": "X", "email": "m@x.com", "is_staff": "on"})
        self.mallory.refresh_from_db()
        self.assertFalse(self.mallory.is_staff)
        self.assertEqual(self.client.get("/desk/").status_code, 403)

    def test_profile_still_saves_name_and_email(self):
        self.login(self.mallory)
        self.client.post("/profile/", {"first_name": "Mal", "last_name": "Lory", "email": "new@c.edu"})
        self.mallory.refresh_from_db()
        self.assertEqual((self.mallory.first_name, self.mallory.email), ("Mal", "new@c.edu"))

    def test_real_staff_reaches_desk(self):
        self.mallory.is_staff = True
        self.mallory.save()
        self.login(self.mallory)
        self.assertContains(self.client.get("/desk/"), "DESK-2290")


class ListingOwnership(Base):
    def test_non_owner_cannot_read_edit_form_or_seller_note(self):
        self.login(self.mallory)
        r = self.client.get(f"/listings/{self.listing.pk}/edit/")
        self.assertEqual(r.status_code, 404)
        self.assertNotContains(r, "SWAP-7741", status_code=404)

    def test_non_owner_cannot_edit_sell_or_delete(self):
        self.login(self.mallory)
        self.assertEqual(self.client.post(f"/listings/{self.listing.pk}/edit/", {"title": "pwned", "description": "x", "price": "1", "category": "other", "seller_note": ""}).status_code, 404)
        self.assertEqual(self.client.post(f"/listings/{self.listing.pk}/sold/").status_code, 404)
        self.assertEqual(self.client.post(f"/listings/{self.listing.pk}/delete/").status_code, 404)
        self.listing.refresh_from_db()
        self.assertEqual((self.listing.title, self.listing.status), ("Charger", "available"))

    def test_owner_can_post_edit_sell(self):
        self.login(self.alex)
        r = self.client.post("/listings/new/", {"title": "Lamp", "description": "ok", "price": "5", "category": "furniture", "seller_note": "n"})
        new = Listing.objects.get(title="Lamp")
        self.assertRedirects(r, f"/listings/{new.pk}/")
        self.assertEqual(self.client.post(f"/listings/{new.pk}/edit/", {"title": "Lamp 2", "description": "ok", "price": "6", "category": "furniture", "seller_note": "n"}).status_code, 302)
        self.client.post(f"/listings/{new.pk}/sold/")
        new.refresh_from_db()
        self.assertEqual((new.title, new.status), ("Lamp 2", "sold"))

    def test_detail_hides_owner_controls_from_others(self):
        self.login(self.mallory)
        r = self.client.get(f"/listings/{self.listing.pk}/")
        self.assertNotContains(r, "Edit listing")
        self.assertNotContains(r, "Mark sold")
        self.login(self.alex)
        self.assertContains(self.client.get(f"/listings/{self.listing.pk}/"), "Edit listing")


class Threads(Base):
    def test_outsider_cannot_read_or_post(self):
        self.login(self.mallory)
        self.assertEqual(self.client.get(f"/threads/{self.thread.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/threads/{self.thread.pk}/", {"body": "hi"}).status_code, 404)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_buyer_and_seller_can_reply(self):
        for u in (self.jordan, self.alex):
            self.login(u)
            self.assertEqual(self.client.get(f"/threads/{self.thread.pk}/").status_code, 200)
            self.client.post(f"/threads/{self.thread.pk}/", {"body": f"hi from {u.username}"})
        self.assertEqual(self.thread.messages.count(), 3)

    def test_start_thread_is_post_only_and_blocks_self_message(self):
        self.login(self.mallory)
        self.assertEqual(self.client.get(f"/listings/{self.listing.pk}/message/").status_code, 405)
        r = self.client.post(f"/listings/{self.listing.pk}/message/")
        t = Thread.objects.get(listing=self.listing, buyer=self.mallory)
        self.assertRedirects(r, f"/threads/{t.pk}/")
        self.login(self.alex)
        self.client.post(f"/listings/{self.listing.pk}/message/")
        self.assertFalse(Thread.objects.filter(buyer=self.alex).exists())


class LoggedOut(Base):
    def test_public_vs_private(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get(f"/listings/{self.listing.pk}/").status_code, 200)
        for p in ["/me/", "/profile/", "/desk/", "/listings/new/", f"/threads/{self.thread.pk}/", f"/listings/{self.listing.pk}/edit/"]:
            self.assertEqual(self.client.get(p).status_code, 302, p)
