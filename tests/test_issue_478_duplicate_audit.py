"""Auditing duplicates that already exist in the AI26 corpus (#478).

The canonicalisation fix stops *new* duplicate documents. It does not remove the ones already in the store,
because removing one of two documents is a data decision (which survives, and what happens to analysis
attached to the other). This audit exists so that decision can be made from a list rather than from an
ad-hoc query, and so a repair can be verified afterwards.

Synthetic fixtures: this repository is public and its tests carry no corpus.
"""

from __future__ import annotations

import json

from laclaugpt_data_collection.duplicate_audit import (
    GROUP_SCHEMA,
    audit_documents,
    main,
    summarise_group,
)

POST = "2100246033183699070"


def doc(_id: int, url: str, *, platform: str = "x", method: str = "") -> dict:
    return {
        "_id": _id,
        "source_url": url,
        "source": {"platform": platform, "collection_method": method},
        "content": {"text": "not printed, ever"},
    }


class TestCounting:
    def test_variant_spellings_of_one_post_count_as_one_identity_two_documents(self):
        report = audit_documents(
            [
                doc(1, f"https://x.com/Example_User/status/{POST}"),
                doc(
                    2,
                    f"https://twitter.com/Example_User/status/{POST}?s=20",
                    platform="web",
                    method="http",
                ),
            ]
        )
        assert report["documents"] == 2
        assert report["distinct_identities"] == 1
        assert report["duplicate_identities"] == 1
        assert report["duplicate_documents"] == 1

    def test_a_clean_corpus_reports_nothing_and_says_so(self):
        report = audit_documents([doc(1, "https://example.org/a"), doc(2, "https://example.org/b")])
        assert report["duplicate_identities"] == 0
        assert "groups" not in report
        assert report["schema"] == GROUP_SCHEMA

    def test_documents_without_a_url_are_not_counted_as_identities(self):
        report = audit_documents([doc(1, ""), doc(2, "https://example.org/a")])
        assert report["documents"] == 1
        assert report["distinct_identities"] == 1


class TestKnownResiduals:
    def test_screen_name_casing_is_still_two_identities(self):
        # X screen names are case-insensitive but the store's identity keeps the path case, so two captures
        # differing only in the account's capitalisation are still two documents. The audit reports them as
        # they are rather than quietly folding what the store does not fold.
        report = audit_documents(
            [
                doc(1, f"https://x.com/Example_User/status/{POST}"),
                doc(2, f"https://x.com/example_user/status/{POST}"),
            ]
        )
        assert report["duplicate_identities"] == 0


class TestGroupShape:
    def test_a_group_names_the_post_not_the_url_and_keeps_the_ids_a_repair_must_choose_between(
        self,
    ):
        docs = [
            doc(1, f"https://x.com/Example_User/status/{POST}"),
            doc(
                7,
                f"https://x.com/Example_User/status/{POST}?ref_src=x",
                platform="web",
                method="http",
            ),
        ]
        group = summarise_group(f"https://x.com/example_user/status/{POST}", docs)
        assert group["identity"] == f"x.com/status/{POST}"
        assert group["document_ids"] == ["1", "7"]
        assert group["platforms"] == {"web": 1, "x": 1}
        assert group["collection_methods"] == {"": 1, "http": 1}

    def test_a_group_for_a_non_status_url_describes_the_path_by_length_only(self):
        group = summarise_group(
            "https://example.org/some/article", [doc(1, "https://example.org/some/article")]
        )
        assert group["identity"].startswith("example.org/")
        assert "some/article" not in group["identity"]

    def test_the_report_never_contains_text_or_handles(self):
        report = audit_documents(
            [
                doc(1, f"https://x.com/Example_User/status/{POST}"),
                doc(2, f"https://x.com/Example_User/status/{POST}"),
            ],
            show_groups=True,
        )
        rendered = json.dumps(report)
        assert "not printed, ever" not in rendered
        assert "Example_User" not in rendered
        assert POST in rendered  # the status id is the identifier a repair needs

    def test_groups_are_ordered_by_size_and_bounded(self):
        documents = []
        for index in range(3):
            documents.append(doc(index, "https://example.org/a"))
            documents.append(doc(10 + index, "https://example.org/b"))
        documents.append(doc(99, "https://example.org/c"))
        documents.append(doc(100, "https://example.org/c"))
        report = audit_documents(documents, show_groups=True, limit=1)
        assert report["groups_total"] == 3
        assert report["groups_shown"] == 1
        assert report["groups"][0]["documents"] == 3


class TestCli:
    def test_the_cli_reports_counts_without_a_database(self, capfd):
        class FakeCollection:
            def find(self, query, projection=None):
                return iter(
                    [
                        doc(1, f"https://x.com/Example_User/status/{POST}"),
                        doc(2, f"https://x.com/Example_User/status/{POST}?s=20", platform="web"),
                    ]
                )

        class FakeDatabase:
            def __getitem__(self, name):
                assert name == "ai26__records"
                return FakeCollection()

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __getitem__(self, name):
                return FakeDatabase()

        # No pymongo import: the CLI takes an injectable factory, so this test runs where the optional
        # [distributed] dependency is absent (CI installs only the base requirements).
        assert (
            main(
                ["--mongodb-uri", "mongodb://example.invalid", "--database", "db", "--show-groups"],
                client_factory=FakeClient,
            )
            == 0
        )
        out = capfd.readouterr().out
        assert "1 duplicate identit" in out
        assert f"x.com/status/{POST}" in out
        assert "not printed, ever" not in out
