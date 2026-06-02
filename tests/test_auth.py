from pathlib import Path

from agentify.auth import is_authorized, parse_api_keys


def test_parse_api_keys_from_string_and_file(tmp_path: Path) -> None:
    key_file = tmp_path / "keys.txt"
    key_file.write_text("\nfile-one\n\nfile-two\n", encoding="utf-8")

    assert parse_api_keys(" inline-one, inline-two ,,", key_file) == {
        "inline-one",
        "inline-two",
        "file-one",
        "file-two",
    }


def test_is_authorized_accepts_bearer_and_x_api_key() -> None:
    keys = {"abc123"}

    assert is_authorized({"authorization": "Bearer abc123"}, keys)
    assert is_authorized({"x-api-key": "abc123"}, keys)
    assert not is_authorized({"authorization": "Bearer bad"}, keys)


def test_is_authorized_allows_when_no_keys_configured() -> None:
    assert is_authorized({}, set())

