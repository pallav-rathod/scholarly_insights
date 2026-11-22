from __future__ import annotations

import io
import json
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from app import create_app
from app.db import get_db, save_articles
from app.mailer import email_new_paper_alerts, send_email


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": f"{self.temp_dir.name}/test.sqlite3",
                "RESEND_API_KEY": "re_test_key",
                "EMAIL_FROM": "Scholarly Insight <onboarding@resend.dev>",
                "PUBLIC_BASE_URL": "https://scholarlyinsights.vercel.app",
            }
        )
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        self.context.pop()
        self.temp_dir.cleanup()

    @staticmethod
    def article(arxiv_id="2401.12345"):
        return {
            "arxiv_id": arxiv_id,
            "title": "A paper about graphs",
            "authors": ["Researcher One"],
            "abstract": "Abstract.",
            "categories": ["cs.LG"],
            "primary_category": "cs.LG",
            "published": "2024-01-10T12:00:00Z",
            "updated": "2024-01-10T12:00:00Z",
            "pdf_url": "",
            "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
            "doi": "",
            "journal_ref": "",
            "comment": "",
        }

    def seed_user_and_article(self):
        db = get_db()
        db.execute(
            "INSERT INTO users(uid, email, display_name) VALUES (?, ?, ?)",
            ("user-1", "researcher@example.test", "Researcher"),
        )
        db.commit()
        save_articles([self.article()])

    def test_send_email_posts_to_resend_api(self):
        response = MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        with patch("app.mailer.urlopen", return_value=response) as open_url:
            sent = send_email("Hello", "Body text", "to@example.test")
        self.assertTrue(sent)
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(
            request.headers["Authorization"], "Bearer re_test_key"
        )
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["to@example.test"])
        self.assertEqual(payload["from"], "Scholarly Insight <onboarding@resend.dev>")
        self.assertEqual(payload["subject"], "Hello")
        self.assertEqual(payload["text"], "Body text")

    def test_send_email_is_disabled_without_api_key(self):
        self.app.config["RESEND_API_KEY"] = ""
        with patch("app.mailer.urlopen") as open_url:
            self.assertFalse(send_email("Hello", "Body", "to@example.test"))
        open_url.assert_not_called()

    def test_send_email_returns_false_on_api_error(self):
        error = HTTPError(
            "https://api.resend.com/emails", 403, "Forbidden", {}, io.BytesIO(b"denied")
        )
        with patch("app.mailer.urlopen", side_effect=error):
            self.assertFalse(send_email("Hello", "Body", "to@example.test"))

    def test_email_new_paper_alerts_lists_new_matches(self):
        self.seed_user_and_article()
        with patch("app.mailer.send_email", return_value=True) as send:
            sent = email_new_paper_alerts("user-1", "Graphs", ["2401.12345"])
        self.assertTrue(sent)
        subject, body, to = send.call_args.args
        self.assertEqual(to, "researcher@example.test")
        self.assertIn("Graphs", subject)
        self.assertIn("A paper about graphs", body)
        self.assertIn("Researcher One", body)
        self.assertIn("https://arxiv.org/abs/2401.12345", body)
        self.assertIn("https://scholarlyinsights.vercel.app/alerts", body)

    def test_email_new_paper_alerts_skips_users_without_email(self):
        self.seed_user_and_article()
        get_db().execute("UPDATE users SET email='' WHERE uid='user-1'")
        get_db().commit()
        with patch("app.mailer.send_email") as send:
            self.assertFalse(email_new_paper_alerts("user-1", "Graphs", ["2401.12345"]))
        send.assert_not_called()
