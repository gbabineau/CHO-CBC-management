import json
import ssl
import sys
from datetime import date
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
from unittest.mock import patch

import pytest

from cho_cbc_management.generate_confirmation_emails import (
    DATA_DIR,
    build_messages,
    create_drafts,
    formatted_count_date,
    main,
)


@pytest.fixture(autouse=True, name="current_year_2026")
def mock_current_year():
    with patch("cho_cbc_management.generate_confirmation_emails.date") as mocked_date:
        mocked_date.today.return_value = date(2026, 11, 11)
        mocked_date.side_effect = date
        yield mocked_date


@pytest.fixture(name="data")
def sample_data():
    return {
        "count date": "2026-12-19",
        "compilers": [{"name": "Compiler", "email": "compiler@example.com"}],
        "emails": [
            {
                "name": "Sector Confirmation",
                "to": "sector captains",
                "subject": "Sectors",
                "message": "Hello\nCount on {date}",
            },
            {
                "name": "Route Confirmation",
                "to": "route leaders",
                "subject": "Routes",
                "message": "Hello\nNext paragraph",
            },
        ],
        "sector captains": [
            {
                "route": 1,
                "names": [
                    {"name": "Captain One", "email": " captain@example.com "},
                    {"name": "Leader One", "email": "leader@example.com"},
                ],
            },
            {
                "route": 2,
                "names": [
                    {"name": "Captain One", "email": "CAPTAIN@example.com"},
                    {"name": "Captain Two", "email": "second@example.com"},
                ],
            },
            {"route": 3, "names": [{"email": ""}]},
        ],
        "routes": [
            {
                "number": 1,
                "sectors": [1, 2],
                "description": "First description",
                "notes": "First notes",
                "leaders": [
                    {"name": "Leader One", "email": "leader@example.com"},
                    {"email": ""},
                ],
            },
            {
                "number": 2,
                "sectors": 2,
                "name": "Second route",
                "description": "Second description",
                "leaders": [
                    {"name": "Leader One", "email": "LEADER@example.com"},
                    {"name": "Another Leader", "email": "another@example.com"},
                ],
            },
            {"number": 3, "sectors": [3, 2], "leaders": []},
        ],
    }


def test_route_drafts_group_leaders_and_copy_captains(data, caplog):
    sender, messages = build_messages(data, "Route Confirmation")
    assert sender == "compiler@example.com"
    assert len(messages) == 2
    first = messages[0]
    assert first["To"] == "leader@example.com"
    assert first["Cc"] == "captain@example.com, second@example.com"
    assert first["From"] == "Compiler <compiler@example.com>"
    assert first["Subject"] == "Routes"
    body = first.get_content()
    assert body.startswith("Dear Leader One,\n\nHello\n\nNext paragraph")
    assert (
        "Route 1\nDescription: First description\nRoute Leader(s): Leader One (leader@example.com)\nSector Captain(s):"
        in body
    )
    assert "Sectors: 1 (PRIMARY), 2 (Secondary)" in body
    assert "Notes: First notes" in body
    assert "Route 2 - Second route" not in body
    assert not list(first.iter_attachments())
    assert messages[1]["To"] == "LEADER@example.com, another@example.com"
    assert messages[1]["Cc"] == "CAPTAIN@example.com, second@example.com"
    assert "Dear Leader One and Another Leader," in messages[1].get_content()
    assert "Route 1" not in messages[1].get_content()
    assert "Route 3 has no leader" in caplog.text
    assert "Sector 3 has no captain" in caplog.text


def test_sector_drafts_and_invalid_selection(data):
    _, messages = build_messages(data, "Sector Confirmation")
    assert [message["To"] for message in messages] == [
        "captain@example.com, leader@example.com",
        "CAPTAIN@example.com, second@example.com",
    ]
    body = messages[0].get_content()
    assert "Count on Saturday, December 19, 2026" in body
    assert "{date}" not in body
    assert body.startswith(
        "Dear Captain One and Leader One,\n\nYou are identified as the captain of sector 1.\n\nHello"
    )
    assert (
        "Sector 1 routes:\n\nRoute 1\nDescription: First description\nRoute Leader(s):"
        in body
    )
    assert "Sector 2 routes:" not in body
    sector_two = messages[1].get_content()
    assert sector_two.index("Route 2 - Second route") < sector_two.index(
        "Route 1\n"
    )
    assert "Route Leader(s): Open" in sector_two
    assert "Sector 3: Open" in sector_two
    assert not list(messages[0].iter_attachments())
    assert all(message["Cc"] is None for message in messages)
    with pytest.raises(ValueError, match="template"):
        build_messages(data, "Unknown")
    data["compilers"].append({"email": "other@example.com"})
    with pytest.raises(ValueError, match="compiler"):
        build_messages(data, "Sector Confirmation")
    assert (
        build_messages(data, "Sector Confirmation", "OTHER@example.com")[0]
        == "other@example.com"
    )


def test_missing_email_warns_without_omitting_person_from_route(data, caplog):
    data["routes"][0]["leaders"].append({"name": "Leader without email"})
    _, messages = build_messages(data, "Route Confirmation")
    assert (
        "Route 1 leader Leader without email has no email address"
        in caplog.text
    )
    assert (
        "Route Leader(s): Leader One (leader@example.com), Leader without email"
        in messages[0].get_content()
    )
    assert messages[0]["To"] == "leader@example.com"


def test_create_drafts_checks_account_and_never_sends(data, tmp_path):
    sender, messages = build_messages(data, "Route Confirmation")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAIL_USERNAME=other@example.com\nMAIL_PASSWORD=test-password\n",
        encoding="utf-8",
    )
    with (
        patch(
            "cho_cbc_management.generate_confirmation_emails.smtplib.SMTP_SSL"
        ) as smtp_factory,
        patch(
            "cho_cbc_management.generate_confirmation_emails.imaplib.IMAP4_SSL"
        ) as imap_factory,
    ):
        with pytest.raises(ValueError, match="does not match"):
            create_drafts(sender, messages, env_file)
        smtp_factory.assert_not_called()
        env_file.write_text(
            "MAIL_USERNAME=COMPILER@example.com\nMAIL_PASSWORD=test-password\n",
            encoding="utf-8",
        )
        smtp = smtp_factory.return_value.__enter__.return_value
        mailbox = imap_factory.return_value.__enter__.return_value
        mailbox.list.return_value = (
            "OK",
            [b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"'],
        )
        mailbox.append.return_value = ("OK", [b"created"])
        create_drafts(sender, messages, env_file)
        tls_context = smtp_factory.call_args.kwargs["context"]
        assert tls_context.verify_mode == ssl.CERT_REQUIRED
        assert tls_context.check_hostname
        smtp_factory.assert_called_once_with(
            "smtp.gmail.com", 465, context=tls_context, timeout=30
        )
        smtp.login.assert_called_once_with(
            "COMPILER@example.com", "test-password"
        )
        smtp.sendmail.assert_not_called()
        smtp.send_message.assert_not_called()
        imap_factory.assert_called_once_with(
            "imap.gmail.com", 993, ssl_context=tls_context, timeout=30
        )
        mailbox.login.assert_called_once_with(
            "COMPILER@example.com", "test-password"
        )
        calls = mailbox.append.call_args_list
        assert len(calls) == 2
        assert calls[0].args[:3] == ('"[Gmail]/Drafts"', r"(\Draft)", None)
        draft = BytesParser(policy=policy.default).parsebytes(calls[0].args[3])
        assert draft["To"] == "leader@example.com"
        assert "Dear Leader One," in draft.get_content()
        grouped_draft = BytesParser(policy=policy.default).parsebytes(
            calls[1].args[3]
        )
        assert grouped_draft["To"] == "LEADER@example.com, another@example.com"
        assert grouped_draft["Cc"] == "CAPTAIN@example.com, second@example.com"


def test_missing_drafts_folder_does_not_append(data, tmp_path):
    sender, messages = build_messages(data, "Route Confirmation")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAIL_USERNAME=compiler@example.com\nMAIL_PASSWORD=test-password\n",
        encoding="utf-8",
    )
    with (
        patch(
            "cho_cbc_management.generate_confirmation_emails.smtplib.SMTP_SSL"
        ),
        patch(
            "cho_cbc_management.generate_confirmation_emails.imaplib.IMAP4_SSL"
        ) as imap_factory,
    ):
        mailbox = imap_factory.return_value.__enter__.return_value
        mailbox.list.return_value = ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])
        with pytest.raises(ValueError, match="Drafts mailbox"):
            create_drafts(sender, messages, env_file)
        mailbox.append.assert_not_called()


def test_real_data_multi_sector_route_leader():
    data = json.loads(
        (DATA_DIR / "2026_routes.json").read_text(encoding="utf-8")
    )
    sender, messages = build_messages(data, "Route Confirmation")
    assert sender == data["compilers"][0]["email"]
    leader = next(
        message
        for message in messages
        if message.get_content().startswith("Dear Jim Childress,")
    )
    cc = {
        address.casefold()
        for _, address in getaddresses(leader.get_all("Cc", []))
    }
    assert {"jimchildress5@gmail.com", "guy.babineau@gmail.com"} <= cc
    assert "Route 2\nDescription:" in leader.get_content()
    assert "Saturday, December 19, 2026" in leader.get_content()
    assert (
        leader["Subject"]
        == "Charlottesville Christmas Bird Count Route Leaders"
    )


@pytest.mark.parametrize("value", ["2026-12-19", "December 19, 2026", "12/19/2026", "19 Dec 2026", "Dec 19"])
def test_count_date_accepts_common_formats(value):
    assert formatted_count_date({"count date": value}) == "Saturday, December 19, 2026"


@pytest.mark.parametrize("value", [None, "", "not a date", "2026-12-12", "2026-12-24", "2025-12-20"])
def test_invalid_count_date_logs_error_and_stops_before_drafts(data, value, caplog):
    data["count date"] = value
    with patch("cho_cbc_management.generate_confirmation_emails.smtplib.SMTP_SSL") as smtp:
        with pytest.raises(ValueError, match="Invalid count date"):
            build_messages(data, "Route Confirmation")
        smtp.assert_not_called()
    assert any(record.levelname == "ERROR" and "Invalid count date" in record.message for record in caplog.records)


def test_christmas_eve_on_saturday_uses_previous_saturday(current_year_2026):
    current_year_2026.today.return_value = date(2022, 1, 1)
    assert formatted_count_date({"count date": "December 17, 2022"}) == "Saturday, December 17, 2022"
    with pytest.raises(ValueError, match="Invalid count date"):
        formatted_count_date({"count date": "December 24, 2022"})


def test_invalid_date_exits_before_creating_drafts(data, tmp_path, caplog):
    data["count date"] = "2026-12-12"
    (tmp_path / "routes.json").write_text(json.dumps(data), encoding="utf-8")
    with (
        patch("cho_cbc_management.generate_confirmation_emails.DATA_DIR", tmp_path),
        patch.object(sys, "argv", ["drafts", "--email", "Route Confirmation", "--routes", "routes.json"]),
        patch("cho_cbc_management.generate_confirmation_emails.create_drafts") as create,
        pytest.raises(SystemExit) as exit_info,
    ):
        main()
    assert exit_info.value.code == 1
    create.assert_not_called()
    assert any(record.levelname == "ERROR" and "Invalid count date" in record.message for record in caplog.records)
