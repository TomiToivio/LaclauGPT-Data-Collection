from laclaugpt_data_collection.canonical import CanonicalSourceRecord


def test_uri_identity_and_nested_roundtrip():
    r=CanonicalSourceRecord(source_url='HTTPS://Example.Invalid/path/?x=1#fragment',native_ids={'tiktok':'1'},media_references=[{'uri':'objects/synthetic'}])
    assert r.identity=='https://example.invalid/path?x=1'
    assert CanonicalSourceRecord.model_validate(r.to_mongo_document()).native_ids['tiktok']=='1'
def test_text_only_is_valid():
    assert CanonicalSourceRecord(source_url='urn:synthetic:1',text='synthetic').media_references==[]
from laclaugpt_data_collection.models import NormalizedRecord

def test_normalized_record_preserves_canonical_uri_identity():
    record = NormalizedRecord(document_id="native-1", platform="synthetic", source_url="HTTPS://Example.Invalid/item/#fragment")
    assert record.source_url == "https://example.invalid/item"
    assert record.canonical_identity == record.source_url

def test_normalized_record_uses_uri_fallback_without_url():
    record = NormalizedRecord(document_id="native-1", platform="synthetic")
    assert record.canonical_identity == "urn:laclaugpt:synthetic:native-1"
