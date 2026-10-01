from types import SimpleNamespace

import pytest

from typesafe_computer_use.writer import WriterError
from typesafe_computer_use.writer_fallback import Endpoint, FallbackWriter


class Client:
    def __init__(self, text):
        self.text = text
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


def request(writer):
    return writer.messages.create(
        model="unused",
        max_tokens=256,
        system="Write JSON",
        messages=[],
        output_config={"format": {"schema": {"properties": {"text": {"type": "string"}}}}},
    )


def test_invalid_output_falls_back_and_working_provider_stays_selected():
    bad, good = Client("not JSON"), Client('{"text":"JFK"}')
    writer = FallbackWriter([Endpoint("openai", bad, "nano"), Endpoint("anthropic", good, "haiku")])
    request(writer)
    request(writer)
    assert len(bad.calls) == 1 and len(good.calls) == 2
    assert [event["status"] for event in writer.events] == ["failed", "ok", "ok"]
    assert good.calls[0]["model"] == "haiku"
    assert "not JSON" not in repr(writer.events)


def test_exhausted_providers_stop_after_one_attempt_each():
    clients = [Client("broken") for _ in range(4)]
    writer = FallbackWriter([Endpoint(str(i), client, "small") for i, client in enumerate(clients)])
    with pytest.raises(WriterError, match="All configured"):
        request(writer)
    assert [len(client.calls) for client in clients] == [1, 1, 1, 1]


def test_low_reasoning_is_provider_specific():
    client = Client('{"text":"SFO"}')
    request(FallbackWriter([Endpoint("fireworks", client, "flash")]))
    assert client.calls[0]["reasoning"] == "none"


def test_planner_reasoning_override_is_not_sent_to_anthropic():
    client = Client('{"text":"ok"}')
    request(FallbackWriter([Endpoint("openai", client, "gpt-5.4-mini", "low")]))
    assert client.calls[-1]["reasoning"] == "low"
    request(FallbackWriter([Endpoint("anthropic", client, "haiku", "low")]))
    assert "reasoning" not in client.calls[-1]


@pytest.mark.parametrize("label", ["spinbutton", "shipping address", "Select a value: role=spinbutton"])
def test_noncredential_words_do_not_match_pin(label):
    from typesafe_computer_use.writer import looks_credential

    assert not looks_credential(label)


@pytest.mark.parametrize("label", ["PIN", "Enter PIN code", "OTP", "Password", "Card number", "Secret API key"])
def test_real_credentials_remain_blocked(label):
    from typesafe_computer_use.writer import looks_credential

    assert looks_credential(label)
