"""Vision/search layer: the LLM is replaced by a fake provider so parsing and fallbacks are tested offline."""
import base64

import pytest

from kbeauty.vision import InvalidImage, TextSearch, VisionIdentifier, decode_image


class FakeProvider:
    def __init__(self, reply: str):
        self.reply = reply

    async def complete(self, prompt, image_b64, mime):
        assert "anua-heartleaf-toner |" in prompt      # catalog is in the prompt
        return self.reply


@pytest.mark.anyio
async def test_vision_parses_well_formed_reply(catalog):
    v = VisionIdentifier(FakeProvider('{"id":"boj-relief-sun","confidence":0.93,"candidates":["boj-relief-sun","roundlab-birch-sun"],"seen_text":"Relief Sun"}'), catalog)
    r = await v.identify("AAAA", "image/jpeg")
    assert r.product_id == "boj-relief-sun" and r.confidence == 0.93 and r.candidates[0] == "boj-relief-sun" and r.method == "vision"


@pytest.mark.anyio
async def test_vision_ignores_ids_not_in_catalog_and_garbage(catalog):
    v = VisionIdentifier(FakeProvider('Sure! {"id":"made-up","confidence":"high","candidates":["made-up","anua-heartleaf-toner"]}'), catalog)
    r = await v.identify("AAAA", "image/jpeg")
    assert r.product_id is None and r.confidence == 0.0 and r.candidates == ("anua-heartleaf-toner",)
    r2 = await VisionIdentifier(FakeProvider("not json at all"), catalog).identify("AAAA", "image/jpeg")
    assert r2.product_id is None and r2.candidates == ()


@pytest.mark.anyio
async def test_vision_disabled_without_provider(catalog):
    r = await VisionIdentifier(None, catalog).identify("AAAA", "image/jpeg")
    assert r.method == "no_ai" and r.error == "no_api_key"


def test_decode_image_validates():
    ok = "data:image/png;base64," + base64.b64encode(b"\x89PNG").decode()
    assert decode_image(ok, 1024)[1] == "image/png"
    with pytest.raises(InvalidImage):
        decode_image("data:image/png;base64,***", 1024)
    with pytest.raises(InvalidImage):
        decode_image(base64.b64encode(b"x" * 2048).decode(), 1024)


def test_text_search_ranks_and_decides(catalog):
    s = TextSearch(catalog)
    assert s.identify("anua toner").product_id == "anua-heartleaf-toner"
    assert s.identify("조선미녀 선크림").product_id == "boj-relief-sun"
    amb = s.identify("torriden")
    assert amb.product_id is None and {"torriden-divein-serum", "torriden-soothing-cream"} <= set(amb.candidates)
    assert s.identify("").candidates == ()
