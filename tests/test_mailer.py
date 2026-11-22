from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

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
                "SMTP_HOST": "smtp.example.test",
                "SMTP_PORT": 587,
                "SMTP_USERNAME": "bot@example.test",
                "SMTP_PASSWORD": "secret",
                "EMAIL_FROM": "alerts@example.test",
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

    def test_send_email_delivers_through_smtp(self):
        server = MagicMock()
        server.has_extn.return_value = False
        with patch("app.mailer.smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value = server
            sent = send_email("Hello", "Body text", "to@example.test")
        self.assertTrue(sent)
        smtp.assert_called_once_with("smtp.example.test", 587, timeout=15)
        message = server.send_message.call_args.args[0]
        self.assertEqual(message["To"], "to@example.test")
        self.assertEqual(message["From"], "alerts@example.test")
        self.assertEqual(message["Subject"], "Hello")
        self.assertIn("Body text", message.get_content())

    def test_send_email_is_disabled_without_smtp_host(self):
        self.app.config["SMTP_HOST"] = ""
        with patch("app.mailer.smtplib.SMTP") as smtp:
            self.assertFalse(send_email("Hello", "Body", "to@example.test"))
        smtp.assert_not_called()

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
