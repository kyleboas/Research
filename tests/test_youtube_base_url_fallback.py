from socket import gaierror
from urllib.error import URLError

from src.ingestion.youtube import YouTubeChannelConfig, fetch_all_channels


def test_fetch_all_channels_retries_default_endpoint_on_dns_failure(monkeypatch) -> None:
    calls: list[str] = []

    def _fake_poll_channel_videos(channel, *, api_key, provider_base_url):
        calls.append(provider_base_url)
        if provider_base_url == "https://bad-host.example/api/v2":
            err = RuntimeError("request failed")
            err.__cause__ = URLError(gaierror(-2, "Name or service not known"))
            return [], 0, err
        return [], 0, None

    monkeypatch.setattr("src.ingestion.youtube.poll_channel_videos", _fake_poll_channel_videos)

    records, failed, missing = fetch_all_channels(
        [YouTubeChannelConfig(name="Test", channel_id="abc")],
        api_key="token",
        provider_base_url="https://bad-host.example/api/v2",
    )

    assert records == []
    assert failed == 0
    assert missing == 0
    assert calls == ["https://bad-host.example/api/v2", "https://transcriptapi.com/api/v2"]
