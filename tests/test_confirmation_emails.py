import csv
import json
import logging
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
    with patch(
        "cho_cbc_management.generate_confirmation_emails.date"
    ) as mocked_date:
        mocked_date.today.return_value = date(2026, 11, 11)
        mocked_date.side_effect = date
        yield mocked_date


@pytest.fixture(name="data")
def sample_data():
    return {
        "count date": "2026-12-19",
        "rain date": "2026-12-20",
        "compilers": [{"name": "Compiler", "email": "compiler@example.com"}],
        "emails": [
            {
                "name": "Sector Confirmation",
                "to": "sector captains",
                "subject": "Sectors",
                "message": "Hello\nCount on {date}; rain date {rain date}",
            },
            {
                "name": "Route Confirmation",
                "to": "route leaders",
                "subject": "Routes",
                "message": "Hello\nNext paragraph\nRain date { rain date}",
            },
            {
                "name": "Captain Announcement",
                "to": "sector captains",
                "subject": "Announcement",
                "message": "Dear Sector Captains,\nCount on {date}",
            },
            {
                "name": "Participant Announcement",
                "bcc": "everyone",
                "subject": "Announcement",
                "message": "Dear Participants,\nRain date {rain date}",
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
                "participants": [
                    {"name": "Participant", "email": "participant@example.com"},
                    {"email": " CAPTAIN@example.com "},
                    {"email": ""},
                ],
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
        "additional participants": [
            {"email": " EXTRA@example.com "},
            {"email": "participant@example.com"},
            {"email": ""},
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
    assert body.startswith("Dear Leader,\n\nHello\n\nNext paragraph")
    assert "Rain date Sunday, December 20, 2026" in body
    assert (
        "Route 1\nDescription: First description\nRoute Leader(s): Leader One (leader@example.com)\nSector Captain(s):"
        in body
    )
    assert "Sectors: 1 (PRIMARY), 2 (Secondary)" in body
    assert "Notes: First notes" in body
    assert "Route 2 - Second route" not in body
    assert body.strip().endswith("Sincerely,\nCompiler\ncompiler@example.com")
    assert not list(first.iter_attachments())
    assert messages[1]["To"] == "LEADER@example.com, another@example.com"
    assert messages[1]["Cc"] == "CAPTAIN@example.com, second@example.com"
    assert "Dear Leader and Another," in messages[1].get_content()
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
    assert "rain date Sunday, December 20, 2026" in body
    assert "{date}" not in body
    assert body.startswith(
        "Dear Captain and Leader,\n\nYou are identified as the captain of sector 1.\n\nHello"
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
    assert all(
        message.get_content()
        .strip()
        .endswith("Sincerely,\nCompiler\ncompiler@example.com")
        for message in messages
    )
    assert not list(messages[0].iter_attachments())
    assert all(message["Cc"] is None for message in messages)
    with pytest.raises(ValueError, match="template"):
        build_messages(data, "Unknown")
    data["compilers"].append(
        {"name": "Other Compiler", "email": "other@example.com"}
    )
    with pytest.raises(ValueError, match="compiler"):
        build_messages(data, "Sector Confirmation")
    assert (
        build_messages(data, "Sector Confirmation", "OTHER@example.com")[0]
        == "other@example.com"
    )
    _, selected_messages = build_messages(
        data, "Sector Confirmation", "OTHER@example.com"
    )
    assert (
        selected_messages[0]
        .get_content()
        .strip()
        .endswith("Sincerely,\nOther Compiler\nother@example.com")
    )


def test_sector_map_link_in_html_and_plain_text(data):
    data["website"] = "https://example.com/map?sector=1&view=routes"
    data["routes"][0]["description"] = "Woods <fields> & streams"
    _, messages = build_messages(data, "Sector Confirmation")
    message = BytesParser(policy=policy.default).parsebytes(
        messages[0].as_bytes()
    )
    plain = message.get_body(preferencelist=("plain",)).get_content()
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "Dear Captain and Leader," in plain
    assert "<p>Dear Captain and Leader,</p>" in html
    assert (
        "sector 1 (Sector map: https://example.com/map?sector=1&view=routes)."
        in plain
    )
    assert (
        'sector 1 (<a href="https://example.com/map?sector=1&amp;view=routes">Sector map</a>).'
        in html
    )
    assert "Description: Woods &lt;fields&gt; &amp; streams" in html
    assert "Sincerely,<br>Compiler<br>compiler@example.com" in html

    _, route_messages = build_messages(data, "Route Confirmation")
    assert route_messages[0].get_body(preferencelist=("html",)) is None


def test_real_data_sector_map_link():
    data = json.loads(
        (DATA_DIR / "2026_routes.json").read_text(encoding="utf-8")
    )
    _, messages = build_messages(data, "Sector Confirmation")
    html = messages[0].get_body(preferencelist=("html",)).get_content()
    assert f'<a href="{data["website"]}">Sector map</a>' in html


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


def test_greeting_name_whitespace_and_email_fallback(data):
    data["routes"][0]["leaders"] = [
        {"name": "  Anne-Marie O'Connor  ", "email": "anne@example.com"},
        {"name": "", "email": "other@example.com"},
    ]
    _, messages = build_messages(data, "Route Confirmation")
    body = messages[0].get_content()
    assert body.startswith("Dear Anne-Marie and other@example.com,")
    assert "Anne-Marie O'Connor (anne@example.com)" in body


def test_announcements_group_recipients_and_preserve_bcc(data):
    _, captain_messages = build_messages(data, "Captain Announcement")
    assert len(captain_messages) == 1
    captain = captain_messages[0]
    assert (
        captain["To"]
        == "captain@example.com, leader@example.com, second@example.com"
    )
    assert captain["Cc"] is None and captain["Bcc"] is None
    assert captain.get_content().startswith(
        "Dear Sector Captains,\n\nCount on Saturday, December 19, 2026"
    )
    assert (
        captain.get_content()
        .strip()
        .endswith("Sincerely,\nCompiler\ncompiler@example.com")
    )

    _, participant_messages = build_messages(data, "Participant Announcement")
    assert len(participant_messages) == 1
    draft = BytesParser(policy=policy.default).parsebytes(
        participant_messages[0].as_bytes(policy=policy.SMTP)
    )
    assert draft["To"] is None and draft["Cc"] is None
    bcc = [
        address.casefold()
        for _, address in getaddresses(draft.get_all("Bcc", []))
    ]
    assert bcc == [
        "captain@example.com",
        "leader@example.com",
        "second@example.com",
        "another@example.com",
        "participant@example.com",
        "extra@example.com",
    ]
    body = draft.get_content().replace("\r\n", "\n")
    assert body.startswith(
        "Dear Participants,\n\nRain date Sunday, December 20, 2026"
    )
    assert body.strip().endswith("Sincerely,\nCompiler\ncompiler@example.com")


def test_cc_and_bcc_are_supported_on_confirmations(data):
    template = data["emails"][1]
    template["cc"] = [
        "leader@example.com",
        "extra@example.com",
        "EXTRA@example.com",
    ]
    template["bcc"] = ["everyone", "extra@example.com", "private@example.com"]
    _, messages = build_messages(data, "Route Confirmation")
    first = messages[0]
    assert first["To"] == "leader@example.com"
    assert (
        first["Cc"]
        == "captain@example.com, second@example.com, extra@example.com"
    )
    assert (
        first["Bcc"]
        == "another@example.com, participant@example.com, private@example.com"
    )


def test_unsupported_copy_recipient_is_rejected(data):
    data["emails"][1]["bcc"] = "unknown group"
    with pytest.raises(ValueError, match="Unsupported Bcc recipient"):
        build_messages(data, "Route Confirmation")


def test_everyone_merges_audubon_csv_with_json_precedence(
    data, tmp_path, caplog
):
    data["routes"][0]["participants"].append(
        {"name": "  Missing   Person ", "email": ""}
    )
    csv_path = tmp_path / "participants.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=["First Name", "Last Name", "Email"]
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "First Name": " CAPTAIN ",
                    "Last Name": "one",
                    "Email": "old@example.com",
                },
                {
                    "First Name": "Missing",
                    "Last Name": "Person",
                    "Email": "found@example.com",
                },
                {
                    "First Name": "New",
                    "Last Name": "Person",
                    "Email": "new@example.com",
                },
                {
                    "First Name": "",
                    "Last Name": "",
                    "Email": "unnamed@example.com",
                },
                {"First Name": "No", "Last Name": "Email", "Email": ""},
                {
                    "First Name": "New",
                    "Last Name": "Person",
                    "Email": "NEW@example.com",
                },
            ]
        )
    with caplog.at_level(logging.INFO):
        _, messages = build_messages(
            data, "Participant Announcement", participants_csv=csv_path
        )
    addresses = [
        address.casefold()
        for _, address in getaddresses(messages[0].get_all("Bcc", []))
    ]
    assert {
        "captain@example.com",
        "found@example.com",
        "new@example.com",
        "unnamed@example.com",
    } <= set(addresses)
    assert "old@example.com" not in addresses
    assert len(addresses) == len(set(addresses))
    assert (
        "Using Audubon CSV email for Missing   Person (missing from JSON)"
        in caplog.text
    )
    assert data["routes"][0]["participants"][-1]["email"] == ""


def test_ambiguous_csv_addresses_are_not_assigned_to_json_name(
    data, tmp_path, caplog
):
    data["additional participants"].append({"name": "Shared Name", "email": ""})
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "First Name,Last Name,Email\nShared,Name,first@example.com\nShared,Name,second@example.com\n",
        encoding="utf-8",
    )
    _, messages = build_messages(
        data, "Participant Announcement", participants_csv=csv_path
    )
    addresses = {
        address.casefold()
        for _, address in getaddresses(messages[0].get_all("Bcc", []))
    }
    assert {"first@example.com", "second@example.com"} <= addresses
    assert "Multiple Audubon CSV emails match Shared Name" in caplog.text
    assert "Using Audubon CSV email for Shared Name" not in caplog.text


def test_csv_is_used_only_for_everyone_and_validates_columns(data, tmp_path):
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "Name,Email\nExample,person@example.com\n", encoding="utf-8"
    )
    _, messages = build_messages(
        data, "Captain Announcement", participants_csv=csv_path
    )
    assert len(messages) == 1
    with pytest.raises(ValueError, match="First Name, Last Name, and Email"):
        build_messages(
            data, "Participant Announcement", participants_csv=csv_path
        )


def test_incomplete_and_ambiguous_names_do_not_discard_csv_addresses(
    data, tmp_path, caplog
):
    data["additional participants"].extend(
        [
            {"name": "Two Words", "email": "json@example.com"},
            {"name": "Shared Person", "email": "first-json@example.com"},
            {"name": "Shared Person", "email": "second-json@example.com"},
        ]
    )
    csv_path = tmp_path / "participants.csv"
    csv_path.write_text(
        "First Name,Last Name,Email\n,Two Words,incomplete@example.com\nShared,Person,csv@example.com\n",
        encoding="utf-8",
    )
    _, messages = build_messages(
        data, "Participant Announcement", participants_csv=csv_path
    )
    addresses = {
        address.casefold()
        for _, address in getaddresses(messages[0].get_all("Bcc", []))
    }
    assert {
        "json@example.com",
        "incomplete@example.com",
        "first-json@example.com",
        "second-json@example.com",
        "csv@example.com",
    } <= addresses
    assert "Multiple JSON emails match Shared Person" in caplog.text


def test_cli_participant_csv_parameter(data, tmp_path, caplog):
    data["additional participants"].append({"name": "New Person", "email": ""})
    (tmp_path / "routes.json").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "participants.csv").write_text(
        "First Name,Last Name,Email\nNew,Person,new@example.com\n",
        encoding="utf-8",
    )
    with (
        caplog.at_level(logging.INFO),
        patch(
            "cho_cbc_management.generate_confirmation_emails.DATA_DIR", tmp_path
        ),
        patch.object(
            sys,
            "argv",
            [
                "drafts",
                "--email",
                "Participant Announcement",
                "--routes",
                "routes.json",
                "--participants",
                "participants.csv",
            ],
        ),
        patch(
            "cho_cbc_management.generate_confirmation_emails.create_drafts"
        ) as create,
    ):
        main()
    draft = create.call_args.args[1][0]
    assert "new@example.com" in draft["Bcc"]
    assert "Using Audubon CSV email for New Person" in caplog.text


def test_real_audubon_csv_prefers_json_address():
    data = json.loads(
        (DATA_DIR / "2026_routes.json").read_text(encoding="utf-8")
    )
    csv_path = DATA_DIR / "participants-2026-VACA.csv"
    if not csv_path.is_file():
        pytest.skip("Audubon participant export is not present")
    with csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
        participant = next(
            row
            for row in csv.DictReader(csv_file)
            if row["First Name"].casefold() == "allen"
            and row["Last Name"].casefold() == "hale"
        )
    captain = next(
        person
        for sector in data["sector captains"]
        for person in sector["names"]
        if person.get("name", "").strip().casefold() == "allen hale"
    )
    _, messages = build_messages(
        data, "Participant Announcement", participants_csv=csv_path
    )
    addresses = {
        address.casefold()
        for _, address in getaddresses(messages[0].get_all("Bcc", []))
    }
    assert captain["email"].strip().casefold() in addresses
    assert participant["Email"].strip().casefold() not in addresses


def test_real_announcement_recipients():
    data = json.loads(
        (DATA_DIR / "2026_routes.json").read_text(encoding="utf-8")
    )
    captains = [
        person
        for sector in data["sector captains"]
        for person in sector["names"]
    ]
    leaders = [
        person for route in data["routes"] for person in route["leaders"]
    ]
    participants = [
        person for route in data["routes"] for person in route["participants"]
    ]
    everyone = (
        captains + leaders + participants + data["additional participants"]
    )
    expected = {
        person["email"].strip().casefold()
        for person in everyone
        if person.get("email", "").strip()
    }
    _, captain_messages = build_messages(data, "Captain Announcement")
    assert len(captain_messages) == 1
    actual_captains = {
        address.casefold()
        for _, address in getaddresses(captain_messages[0].get_all("To", []))
    }
    assert actual_captains == {
        person["email"].strip().casefold()
        for person in captains
        if person.get("email", "").strip()
    }
    _, participant_messages = build_messages(data, "Participant Announcement")
    assert len(participant_messages) == 1
    bcc = [
        address.casefold()
        for _, address in getaddresses(
            participant_messages[0].get_all("Bcc", [])
        )
    ]
    assert set(bcc) == expected
    assert len(bcc) == len(expected)
    assert participant_messages[0]["To"] is None


def test_bcc_only_draft_is_saved_without_printing_recipients(
    data, tmp_path, capsys
):
    sender, messages = build_messages(data, "Participant Announcement")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "MAIL_USERNAME=compiler@example.com\nMAIL_PASSWORD=test-password\n",
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
        mailbox = imap_factory.return_value.__enter__.return_value
        mailbox.list.return_value = (
            "OK",
            [b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"'],
        )
        mailbox.append.return_value = ("OK", [b"created"])
        create_drafts(sender, messages, env_file)
        draft = BytesParser(policy=policy.default).parsebytes(
            mailbox.append.call_args.args[3]
        )
        assert draft["To"] is None
        assert "participant@example.com" in draft["Bcc"]
        smtp = smtp_factory.return_value.__enter__.return_value
        smtp.sendmail.assert_not_called()
        smtp.send_message.assert_not_called()
    assert (
        capsys.readouterr().out == "Created draft for undisclosed recipients\n"
    )


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
        assert "Dear Leader," in draft.get_content()
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
        if message.get_content().startswith("Dear Jim,")
    )
    cc = {
        address.casefold()
        for _, address in getaddresses(leader.get_all("Cc", []))
    }
    assert {"jimchildress5@gmail.com", "guy.babineau@gmail.com"} <= cc
    assert "Route 2\nDescription:" in leader.get_content()
    assert "Saturday, December 19, 2026" in leader.get_content()
    assert "Sunday, December 20, 2026" in leader.get_content()
    assert (
        leader["Subject"]
        == "Charlottesville Christmas Bird Count Route Leaders"
    )


@pytest.mark.parametrize(
    "value",
    ["2026-12-19", "December 19, 2026", "12/19/2026", "19 Dec 2026", "Dec 19"],
)
def test_count_date_accepts_common_formats(value):
    assert (
        formatted_count_date({"count date": value})
        == "Saturday, December 19, 2026"
    )


@pytest.mark.parametrize(
    "value", [None, "", "not a date", "2026-12-12", "2026-12-24", "2025-12-20"]
)
def test_invalid_count_date_logs_error_and_stops_before_drafts(
    data, value, caplog
):
    data["count date"] = value
    with patch(
        "cho_cbc_management.generate_confirmation_emails.smtplib.SMTP_SSL"
    ) as smtp:
        with pytest.raises(ValueError, match="Invalid count date"):
            build_messages(data, "Route Confirmation")
        smtp.assert_not_called()
    assert any(
        record.levelname == "ERROR" and "Invalid count date" in record.message
        for record in caplog.records
    )


def test_christmas_eve_on_saturday_uses_previous_saturday(current_year_2026):
    current_year_2026.today.return_value = date(2022, 1, 1)
    assert (
        formatted_count_date({"count date": "December 17, 2022"})
        == "Saturday, December 17, 2022"
    )
    with pytest.raises(ValueError, match="Invalid count date"):
        formatted_count_date({"count date": "December 24, 2022"})


def test_invalid_date_exits_before_creating_drafts(data, tmp_path, caplog):
    data["count date"] = "2026-12-12"
    (tmp_path / "routes.json").write_text(json.dumps(data), encoding="utf-8")
    with (
        patch(
            "cho_cbc_management.generate_confirmation_emails.DATA_DIR", tmp_path
        ),
        patch.object(
            sys,
            "argv",
            [
                "drafts",
                "--email",
                "Route Confirmation",
                "--routes",
                "routes.json",
            ],
        ),
        patch(
            "cho_cbc_management.generate_confirmation_emails.create_drafts"
        ) as create,
        pytest.raises(SystemExit) as exit_info,
    ):
        main()
    assert exit_info.value.code == 1
    create.assert_not_called()
    assert any(
        record.levelname == "ERROR" and "Invalid count date" in record.message
        for record in caplog.records
    )


@pytest.mark.parametrize(
    "value",
    ["2026-12-20", "December 20, 2026", "12/20/2026", "20 Dec 2026", "Dec 20"],
)
def test_rain_date_accepts_common_formats(data, value):
    data["rain date"] = value
    _, messages = build_messages(data, "Sector Confirmation")
    assert "rain date Sunday, December 20, 2026" in messages[0].get_content()


@pytest.mark.parametrize(
    "value", [None, "", "not a date", "2026-12-19", "2026-12-21", "2025-12-20"]
)
def test_invalid_rain_date_exits_before_creating_drafts(
    data, value, tmp_path, caplog
):
    data["rain date"] = value
    (tmp_path / "routes.json").write_text(json.dumps(data), encoding="utf-8")
    with (
        patch(
            "cho_cbc_management.generate_confirmation_emails.DATA_DIR", tmp_path
        ),
        patch.object(
            sys,
            "argv",
            [
                "drafts",
                "--email",
                "Route Confirmation",
                "--routes",
                "routes.json",
            ],
        ),
        patch(
            "cho_cbc_management.generate_confirmation_emails.create_drafts"
        ) as create,
        pytest.raises(SystemExit) as exit_info,
    ):
        main()
    assert exit_info.value.code == 1
    create.assert_not_called()
    assert any(
        record.levelname == "ERROR" and "Invalid rain date" in record.message
        for record in caplog.records
    )
