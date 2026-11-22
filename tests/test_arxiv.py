from __future__ import annotations

import ssl
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from app import create_app
from app.arxiv import ArxivClient, client
from app.db import get_db


ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>https://arxiv.org/abs/2401.12345v2</id>
    <title>  A Study of &amp;lt;Graphs&amp;gt;  </title>
    <summary>First line
      second line</summary>
    <published>2024-01-10T12:00:00Z</published>
    <updated>2024-02-10T12:00:00Z</updated>
    <author><name>Researcher One</name></author>
    <category term="cs.LG"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.LG"/>
    <link title="pdf" type="application/pdf" href="https://arxiv.org/pdf/2401.12345"/>
  </entry>
</feed>"""


class ArxivTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": f"{self.temp_dir.name}/test.sqlite3",
                "ARXIV_MIN_INTERVAL": 0,
                "ARXIV_CACHE_TTL": 86400,
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        client._last_request = 0

    def tearDown(self):
        self.context.pop()
        self.temp_dir.cleanup()

    def test_build_query_combines_filters_and_date_bounds(self):
        query, normalized = ArxivClient().build_query(
            {
                "q": "graph  learning",
                "author": 'Ada "Lovelace"',
                "category": "cs.LG",
                "from_date": "2025-01-02",
                "to_date": "2025-01-31",
            }
        )
        self.assertIn('all:"graph learning"', query)
        self.assertIn('au:"Ada \\"Lovelace\\""', query)
        self.assertIn("cat:cs.LG", query)
        self.assertIn("submittedDate:[202501020000 TO 202501312359]", query)
        self.assertEqual(normalized["from_date"], "2025-01-02")

    def test_invalid_category_and_date_range_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "category"):
            ArxivClient().build_query({"category": "cs.LG OR all:*"})
        with self.assertRaisesRegex(ValueError, "not be later"):
            ArxivClient().build_query(
                {"from_date": "2025-02-01", "to_date": "2025-01-01"}
            )

    def test_multiple_author_and_category_filters_are_or_grouped(self):
        query, _ = ArxivClient().build_query(
            {"author": "Ada Lovelace, Alan Turing", "category": "cs.LG, cs.AI"}
        )
        self.assertIn('(au:"Ada Lovelace" OR au:"Alan Turing")', query)
        self.assertIn("(cat:cs.LG OR cat:cs.AI)", query)

    def test_arxiv_id_filter_and_empty_sort_use_supported_defaults(self):
        query, _ = ArxivClient().build_query({"id": "2401.12345"})
        self.assertEqual(query, "id:2401.12345")
        with patch.object(client, "_fetch", return_value=ATOM) as fetch:
            result = client.search({"q": "graphs", "sort": "", "limit": 1})
        self.assertEqual(len(result["articles"]), 1)
        self.assertEqual(fetch.call_args.args[0]["sortBy"], "submittedDate")

    def test_empty_filters_match_all_papers(self):
        query, normalized = ArxivClient().build_query({})
        self.assertEqual(query, "cat:*")
        self.assertEqual(normalized, {})
        with patch.object(client, "_fetch", return_value=ATOM) as fetch:
            result = client.search({"sort": "newest"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(fetch.call_args.args[0]["search_query"], "cat:*")

    def test_comma_only_author_and_category_are_rejected(self):
        for filters, field in (({"author": ",,"}, "author"), ({"category": ",,"}, "category")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                ArxivClient().build_query(filters)

    def test_cached_search_parses_atom_and_avoids_second_request(self):
        with patch.object(client, "_fetch", return_value=ATOM) as fetch:
            first = client.search({"q": "graphs", "limit": 1})
            second = client.search({"q": "graphs", "limit": 1})
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first["articles"][0]["arxiv_id"], "2401.12345")
        self.assertEqual(first["articles"][0]["authors"], ["Researcher One"])
        self.assertEqual(first["articles"][0]["categories"], ["cs.LG"])
        self.assertEqual(second["articles"][0]["title"], "A Study of &lt;Graphs&gt;")

    def test_tracker_refresh_can_bypass_fresh_cache(self):
        with patch.object(client, "_fetch", return_value=ATOM) as fetch:
            client.search({"q": "graphs", "limit": 1})
            client.search({"q": "graphs", "limit": 1}, force_refresh=True)
        self.assertEqual(fetch.call_count, 2)

    def test_expired_cached_search_is_returned_when_upstream_fails(self):
        with patch.object(client, "_fetch", return_value=ATOM):
            client.search({"q": "graphs", "limit": 1})
        get_db().execute("UPDATE query_cache SET fetched_at=0")
        get_db().commit()
        with patch("app.arxiv.time.time", return_value=90000), patch.object(
            client, "_fetch", side_effect=OSError("offline")
        ):
            result = client.search({"q": "graphs", "limit": 1})
        self.assertTrue(result["stale"])
        self.assertEqual(len(result["articles"]), 1)

    def test_throttle_waits_for_configured_interval(self):
        self.app.config["ARXIV_MIN_INTERVAL"] = 3
        client._last_request = 4
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"atom"
        with patch("app.arxiv.time.monotonic", side_effect=[5, 5]), patch(
            "app.arxiv.time.sleep"
        ) as sleep, patch("app.arxiv.urlopen", return_value=response):
            client._fetch({"search_query": "all:test"})
        sleep.assert_called_once_with(2)

    def test_upstream_request_uses_verified_certifi_ca_bundle(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"atom"
        with patch("app.arxiv.urlopen", return_value=response) as open_url:
            client._fetch({"search_query": "all:graph"})
        context = open_url.call_args.kwargs["context"]
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)
