"""One post must be one document, whichever machine collected it (#478).

`source_url` is the record's identity: it is half of the `routing_source_unique` index, and
`CanonicalRecord.dedup_key` returns it. So anything the canonicalizer fails to unify becomes a duplicate
document the moment two collectors see the same post.

That is not hypothetical. Measured in the live AI26 store before this change:

* **4 status IDs were already stored twice**, each pair differing only by X share parameters
  (`?s=20`, `?t=…&s=19`, `?a=…`);
* 9 X URLs carried such a parameter at all;
* 0 records used a `twitter.com` host, so unifying the host affects no existing record.

These tests pin the identity rules, and they pin the *boundaries*: the X rules must not reach into other
sites, where `t`, `s` and `a` are ordinary parameters that can select a different page.
"""
from __future__ import annotations

from laclaugpt_data_collection.models import CanonicalRecord, canonicalize_source_url

POST = "https://x.com/AnthropicAI/status/2001686747185394148"


class TestXHostVariantsAreOneIdentity:
    def test_twitter_and_x_hosts_reduce_to_one_url(self) -> None:
        variants = [
            "https://x.com/AnthropicAI/status/2001686747185394148",
            "https://www.x.com/AnthropicAI/status/2001686747185394148",
            "https://mobile.x.com/AnthropicAI/status/2001686747185394148",
            "https://twitter.com/AnthropicAI/status/2001686747185394148",
            "https://www.twitter.com/AnthropicAI/status/2001686747185394148",
            "https://mobile.twitter.com/AnthropicAI/status/2001686747185394148",
        ]
        assert {canonicalize_source_url(v) for v in variants} == {POST}

    def test_scheme_is_pinned_for_x_because_x_serves_only_https(self) -> None:
        assert canonicalize_source_url("http://x.com/a/status/1") == "https://x.com/a/status/1"
        assert canonicalize_source_url("HTTP://Twitter.com/a/status/1") == "https://x.com/a/status/1"

    def test_share_parameters_are_removed(self) -> None:
        for suffix in ("?s=20", "?t=abc&s=19", "?a=gqHFUht-AywT59iIaZs&s=46", "?ref_src=twsrc%5Etfw"):
            assert canonicalize_source_url(POST + suffix) == POST, suffix

    def test_share_parameters_combine_with_a_trailing_slash(self) -> None:
        assert canonicalize_source_url(POST + "/?s=20") == POST


class TestOtherSitesAreUntouched:
    def test_a_generic_parameter_named_like_a_share_parameter_survives(self) -> None:
        """`?t=` and `?s=` are meaningful on other sites; the X rule must not leak."""
        url = "https://example.org/search?t=report&s=3"
        assert canonicalize_source_url(url) == url

    def test_twitter_like_text_in_a_path_is_not_a_host(self) -> None:
        url = "https://example.org/x.com/status/1"
        assert canonicalize_source_url(url) == url

    def test_ordinary_normalisation_still_happens(self) -> None:
        assert canonicalize_source_url("https://EXAMPLE.org/a/?utm_source=x") == "https://example.org/a"

    def test_a_bare_non_http_identifier_is_returned_unchanged(self) -> None:
        assert canonicalize_source_url("did:plc:aeug3w4mdhnc2wv73hmrh36z") == "did:plc:aeug3w4mdhnc2wv73hmrh36z"


class TestTheRecordIdentityFollows:
    def test_two_captures_of_one_post_share_a_dedup_key(self) -> None:
        left = CanonicalRecord(source_url="https://twitter.com/AnthropicAI/status/2001686747185394148?s=20")
        right = CanonicalRecord(source_url=POST)
        assert left.dedup_key == right.dedup_key == POST

    def test_a_recollect_from_another_machine_does_not_change_the_key(self) -> None:
        first = CanonicalRecord(source_url=POST)
        again = CanonicalRecord(source_url="http://mobile.twitter.com/AnthropicAI/status/2001686747185394148?t=x")
        assert first.source_url == again.source_url
