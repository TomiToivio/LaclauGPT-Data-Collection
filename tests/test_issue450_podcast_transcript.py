"""#450: podcast transcripts come from the publisher's page, never from media bytes.

The owner decision for #450 is explicit: use transcripts that are already published,
do not download audio or video to make one, and leave an absent transcript absent
rather than synthesising it. These tests pin the four states a collector can be in
and prove no media is involved in any of them.
"""


from laclaugpt_data_collection.collectors.podcast import (
    MIN_TRANSCRIPT_CHARS,
    PodcastTranscriptCollector,
    episode_metadata,
)

SCRIPT = """
<header><nav>Chrome menu</nav></header>
<main>
  <h1>Episode 37</h1>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"PodcastEpisode",
   "headline":"The Only Defense Against AI","datePublished":"2026-04-23T15:46:23.000Z",
   "author":{"@type":"Organization","name":"Network School"}}
  </script>
  <p>%s</p>
</main>
<footer>Privacy Terms Security Support Jobs About</footer>
""" % ("We talked about zero knowledge and AI defence. " * 60)


def _collect(html, url="https://example.org/podcast/ep"):
    return PodcastTranscriptCollector(url, fetch=lambda _u: (url, html)).collect()


def test_metadata_comes_from_json_ld_when_the_theme_has_no_meta_tag():
    meta = episode_metadata(SCRIPT)
    assert meta["title"] == "The Only Defense Against AI"
    assert meta["author"] == "Network School"
    assert meta["published"] == "2026-04-23T15:46:23"


def test_transcript_record_carries_text_metadata_and_no_media():
    result = _collect(SCRIPT)
    assert not result.warnings
    record = result.records[0]
    assert record.source.platform == "podcast"
    assert "zero knowledge" in record.text
    meta = record.provenance[-1].metadata
    assert meta["transcript_source"] == "page-html"
    assert meta["text_chars"] == len(record.text)
    assert meta["audio_downloaded"] is False
    assert "podcast-transcript" in record.provenance[-1].transformations


def test_page_chrome_is_not_part_of_the_transcript():
    record = _collect(SCRIPT).records[0]
    assert "Chrome menu" not in record.text
    assert "Privacy Terms Security" not in record.text


def test_a_page_without_a_transcript_stays_absent():
    thin = SCRIPT.replace("We talked about zero knowledge and AI defence. " * 60, "Short note.")
    assert len(thin) < MIN_TRANSCRIPT_CHARS * 4
    result = _collect(thin)
    assert result.records == []
    assert result.warnings[0].startswith("transcript_unavailable")


def test_an_undated_episode_is_not_stored_as_a_record():
    html = SCRIPT.replace('"datePublished":"2026-04-23T15:46:23.000Z",', "")
    result = _collect(html)
    assert result.records == []
    assert result.warnings[0].startswith("publication_time_missing")


def test_an_unreachable_episode_is_reported_not_invented():
    result = PodcastTranscriptCollector("https://example.org/x", fetch=lambda _u: None).collect()
    assert result.records == []
    assert result.warnings[0].startswith("episode_unreachable")
