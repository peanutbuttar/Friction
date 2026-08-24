from friction import notify


def test_message_is_passed_as_argument_not_interpolated():
    """A message with quotes must not be able to break or alter the script."""
    assert not any("%s" in part or "{}" in part for part in notify.SEND_SCRIPT)
    assert notify.SEND_SCRIPT[-1] == "end run"


def test_notify_contacts_handles_dicts_and_strings(monkeypatch):
    seen = []

    def fake(handle, message):
        seen.append((handle, message))
        return notify.SendResult(handle, "", True)

    monkeypatch.setattr(notify, "send_imessage", fake)
    results = notify.notify_contacts(
        [{"name": "Alex", "handle": "+1555"}, "+1666", {"name": "x"}], "hi")

    assert [h for h, _ in seen] == ["+1555", "+1666"]   # entry with no handle skipped
    assert results[0].name == "Alex"
    assert results[1].name == "+1666"                    # falls back to the handle


def test_failure_is_reported_not_swallowed(monkeypatch):
    monkeypatch.setattr(notify, "send_imessage",
                        lambda h, m: notify.SendResult(h, "", False, "boom"))
    results = notify.notify_contacts([{"name": "Alex", "handle": "+1"}], "hi")
    assert not results[0].accepted and results[0].error == "boom"


def test_script_does_not_use_reserved_messages_terms():
    """`handle` is a term in Messages' own dictionary. Using it as a variable
    makes `participant handle of svc` parse as a class reference and the send
    fails with -1728. Guard against anyone reintroducing it."""
    script = " ".join(notify.SEND_SCRIPT)
    assert "handle" not in script, "rename the variable; `handle` collides"
    assert "recipientId" in script
