from __future__ import annotations

import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import create_app


class FakeFirebaseAuth:
    @staticmethod
    def verify_id_token(token, app=None, check_revoked=False):
        if token != "valid-token":
            raise ValueError("invalid token")
        return {
            "uid": "firebase-user-1",
            "email": "researcher@example.test",
            "name": "Researcher",
        }


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": f"{self.temp_dir.name}/test.sqlite3",
                "FIREBASE_PROJECT_ID": "test-project",
                "ARXIV_MIN_INTERVAL": 0,
            }
        )
        self.client = self.app.test_client()
        self.firebase = patch(
            "app.auth._firebase_admin", return_value=(FakeFirebaseAuth(), object())
        )
        self.firebase.start()

    def tearDown(self):
        self.firebase.stop()
        self.temp_dir.cleanup()

    def auth_headers(self):
        return {"Authorization": "Bearer valid-token"}

    def test_production_requires_secret_and_postgres_url(self):
        production_config = {
            "APP_ENV": "production",
            "SECRET_KEY": "",
            "DATABASE_URL": "",
        }
        with patch.dict(os.environ, production_config):
            with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
                create_app()

        production_config["SECRET_KEY"] = "configured-secret"
        with patch.dict(os.environ, production_config):
            with self.assertRaisesRegex(RuntimeError, "DATABASE_URL"):
                create_app()

    @staticmethod
    def article():
        return {
            "arxiv_id": "2401.12345",
            "title": "A paper about graphs",
            "authors": ["Researcher"],
            "abstract": "Abstract about graphs.",
            "categories": ["cs.LG"],
            "primary_category": "cs.LG",
            "published": "2024-01-10T12:00:00Z",
            "updated": "2024-01-10T12:00:00Z",
            "pdf_url": "https://arxiv.org/pdf/2401.12345",
            "abs_url": "https://arxiv.org/abs/2401.12345",
            "doi": "",
            "journal_ref": "",
            "comment": "",
        }

    def save_article(self):
        from app.db import save_articles

        with self.app.app_context():
            save_articles([self.article()])

    def test_main_screens_render_without_firebase_or_arxiv_requests(self):
        for path in ("/", "/search", "/trackers", "/library", "/alerts", "/health"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_search_api_rejects_empty_and_invalid_filters(self):
        empty = self.client.get("/api/search")
        self.assertEqual(empty.status_code, 400)
        invalid = self.client.get("/api/search?category=bad%20OR%20all%3A%2A")
        self.assertEqual(invalid.status_code, 400)

    def test_search_results_and_pagination_render(self):
        article = {
            "arxiv_id": "2401.12345",
            "title": "Graph learning for research",
            "authors": ["Researcher"],
            "abstract": "A useful abstract.",
            "categories": ["cs.LG"],
            "primary_category": "cs.LG",
            "published": "2024-01-10T12:00:00Z",
            "updated": "2024-01-10T12:00:00Z",
            "pdf_url": "https://arxiv.org/pdf/2401.12345",
            "abs_url": "https://arxiv.org/abs/2401.12345",
            "doi": "",
            "journal_ref": "",
            "comment": "",
        }
        with patch(
            "app.routes.client.search",
            return_value={"articles": [article], "total": 21, "stale": False},
        ):
            response = self.client.get("/search?q=graph")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Graph learning for research", response.data)
        self.assertIn(b"Next page", response.data)

    def test_search_page_without_filters_browses_all_papers(self):
        with patch(
            "app.routes.client.search",
            return_value={"articles": [], "total": 0, "stale": False},
        ) as search:
            response = self.client.get("/search?sort=newest")
        self.assertEqual(response.status_code, 200)
        search.assert_called_once()

    def test_article_details_render_from_normalized_record(self):
        with patch("app.routes._ensure_article", return_value=self.article()), patch(
            "app.routes.related_articles", return_value=[]
        ):
            response = self.client.get("/article/2401.12345")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"A paper about graphs", response.data)
        self.assertIn(b"Read PDF", response.data)

    def test_protected_routes_require_verified_firebase_token(self):
        self.assertEqual(self.client.get("/api/trackers").status_code, 401)
        response = self.client.get("/api/trackers", headers=self.auth_headers())
        self.assertEqual(response.status_code, 200)

    def test_user_can_create_and_delete_owned_tracker(self):
        created = self.client.post(
            "/api/trackers",
            headers=self.auth_headers(),
            json={"name": "Vision research", "categories": "cs.CV"},
        )
        self.assertEqual(created.status_code, 201)
        tracker_id = created.get_json()["id"]
        listed = self.client.get("/api/trackers", headers=self.auth_headers())
        self.assertEqual(listed.get_json()["trackers"][0]["name"], "Vision research")
        deleted = self.client.delete(
            f"/api/trackers/{tracker_id}", headers=self.auth_headers()
        )
        self.assertEqual(deleted.status_code, 200)

    def test_library_tracks_favorites_and_reading_activity(self):
        self.save_article()
        with patch("app.routes._ensure_article", return_value=self.article()):
            saved = self.client.post(
                "/api/articles/2401.12345/favorite", headers=self.auth_headers()
            )
            viewed = self.client.post(
                "/api/articles/2401.12345/history", headers=self.auth_headers()
            )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(viewed.status_code, 200)
        library = self.client.get("/api/library", headers=self.auth_headers()).get_json()
        self.assertEqual(len(library["favorites"]), 1)
        self.assertEqual(len(library["history"]), 1)
        self.assertTrue(library["history"][0]["activity_at"])

    def test_tracker_refresh_creates_deduplicated_in_app_alerts(self):
        article = self.article()
        self.save_article()
        created = self.client.post(
            "/api/trackers",
            headers=self.auth_headers(),
            json={"name": "Graphs", "keywords": "graphs"},
        )
        tracker_id = created.get_json()["id"]
        with patch(
            "app.routes.client.search",
            return_value={"articles": [article], "total": 1, "stale": False},
        ):
            for _ in range(2):
                response = self.client.post(
                    f"/api/trackers/{tracker_id}/refresh",
                    headers=self.auth_headers(),
                )
                self.assertEqual(response.status_code, 200)
        alerts = self.client.get("/api/alerts", headers=self.auth_headers()).get_json()
        self.assertEqual(len(alerts["alerts"]), 1)
        self.assertEqual(alerts["alerts"][0]["title"], article["title"])

    def test_tracker_refresh_reports_newly_created_alerts(self):
        article = self.article()
        self.save_article()
        created = self.client.post(
            "/api/trackers",
            headers=self.auth_headers(),
            json={"name": "Graphs", "keywords": "graphs"},
        )
        tracker_id = created.get_json()["id"]
        with patch(
            "app.routes.client.search",
            return_value={"articles": [article], "total": 1, "stale": False},
        ):
            first = self.client.post(
                f"/api/trackers/{tracker_id}/refresh", headers=self.auth_headers()
            ).get_json()
            second = self.client.post(
                f"/api/trackers/{tracker_id}/refresh", headers=self.auth_headers()
            ).get_json()
        self.assertEqual(first["new_alerts"], 1)
        self.assertEqual(second["new_alerts"], 0)

    def test_authenticated_comments_can_be_replied_to(self):
        self.save_article()
        root = self.client.post(
            "/api/articles/2401.12345/comments",
            headers=self.auth_headers(),
            json={"body": "Interesting result."},
        )
        self.assertEqual(root.status_code, 201)
        reply = self.client.post(
            "/api/articles/2401.12345/comments",
            headers=self.auth_headers(),
            json={"body": "Agreed.", "parent_id": root.get_json()["id"]},
        )
        self.assertEqual(reply.status_code, 201)
        comments = self.client.get("/api/articles/2401.12345/comments").get_json()["comments"]
        self.assertEqual(comments[0]["parent_id"], None)
        self.assertEqual(comments[1]["parent_id"], root.get_json()["id"])

    def test_comment_reply_must_belong_to_same_article(self):
        article = {
            "arxiv_id": "2401.12345",
            "title": "A paper",
            "authors": [],
            "abstract": "Abstract",
            "categories": [],
            "primary_category": "",
            "published": "",
            "updated": "",
            "pdf_url": "",
            "abs_url": "https://arxiv.org/abs/2401.12345",
            "doi": "",
            "journal_ref": "",
            "comment": "",
        }
        with self.app.app_context():
            from app.db import save_articles

            save_articles([article])
        response = self.client.post(
            "/api/articles/2401.12345/comments",
            headers=self.auth_headers(),
            json={"body": "Reply", "parent_id": 999},
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
