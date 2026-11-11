import argparse
import imaplib
import json
import logging
import re
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email import policy
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from pathlib import Path

from dateutil import parser as date_parser
from dotenv import dotenv_values

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LOGGER = logging.getLogger(__name__)


def validated_count_date(data):
    year = date.today().year
    christmas_eve = date(year, 12, 24)
    days_since_saturday = (christmas_eve.weekday() - 5) % 7 or 7
    expected = christmas_eve - timedelta(days=days_since_saturday)
    raw_date = data.get("count date")
    try:
        if not isinstance(raw_date, str) or not raw_date.strip():
            raise ValueError("Missing count date")
        count_date = date_parser.parse(
            raw_date, default=datetime(year, 1, 1)
        ).date()
        if count_date != expected:
            raise ValueError(
                f"Count date must be the last Saturday before Christmas Eve in {year}: {expected.isoformat()}"
            )
    except (ValueError, OverflowError) as error:
        LOGGER.error("Invalid count date %r: %s", raw_date, error)
        raise ValueError(f"Invalid count date: {error}") from error
    return count_date


def format_date(value):
    return f"{value:%A, %B} {value.day}, {value.year}"


def formatted_count_date(data):
    return format_date(validated_count_date(data))


def validated_rain_date(data, count_date):
    raw_date = data.get("rain date")
    try:
        if not isinstance(raw_date, str) or not raw_date.strip():
            raise ValueError("Missing rain date")
        rain_date = date_parser.parse(
            raw_date, default=datetime(count_date.year, 1, 1)
        ).date()
        expected = count_date + timedelta(days=1)
        if rain_date != expected:
            raise ValueError(
                f"Rain date must be the day after the count date: {expected.isoformat()}"
            )
    except (ValueError, OverflowError) as error:
        LOGGER.error("Invalid rain date %r: %s", raw_date, error)
        raise ValueError(f"Invalid rain date: {error}") from error
    return rain_date


def route_sectors(route):
    sectors = route.get("sectors", [])
    return sectors if isinstance(sectors, list) else [sectors]


def contact_name(person):
    return person.get("name", "").strip() or person.get("email", "").strip()


def contact_list(people):
    contacts = []
    seen = set()
    for person in people:
        name = contact_name(person)
        email = person.get("email", "").strip()
        key = (email or name).casefold()
        if key and key not in seen:
            seen.add(key)
            contacts.append(
                f"{name} ({email})" if name != email and email else name
            )
    return ", ".join(contacts) or "Open"


def recipient_list(people, label):
    recipients = {}
    for person in people:
        name = contact_name(person)
        email = person.get("email", "").strip()
        if name and not email:
            LOGGER.warning("%s %s has no email address", label, name)
        if email:
            recipients.setdefault(email.casefold(), person)
    return list(recipients.values())


def template_recipients(data, selection, label):
    captains = [
        person
        for sector in data.get("sector captains", [])
        for person in sector.get("names", [])
    ]
    routes = data.get("routes", [])
    leaders = [
        person for route in routes for person in route.get("leaders", [])
    ]
    participants = [
        person for route in routes for person in route.get("participants", [])
    ]
    additional = data.get("additional participants", [])
    groups = {
        "sector captains": captains,
        "route leaders": leaders,
        "route participants": participants,
        "additional participants": additional,
        "everyone": captains + leaders + participants + additional,
    }
    if not selection:
        return []
    selections = selection if isinstance(selection, list) else [selection]
    people = []
    for item in selections:
        if isinstance(item, dict):
            people.append(item)
        elif isinstance(item, str) and item.strip().casefold() in groups:
            people.extend(groups[item.strip().casefold()])
        elif isinstance(item, str) and "@" in item:
            people.append({"email": item.strip()})
        else:
            raise ValueError(f"Unsupported {label} recipient: {item!r}")
    return recipient_list(people, label)


def build_messages(data, template_name, compiler_email=None):
    count_date = validated_count_date(data)
    rain_date = validated_rain_date(data, count_date)
    templates = [
        template
        for template in data.get("emails", [])
        if template.get("name") == template_name
    ]
    if len(templates) != 1:
        raise ValueError(
            f"Expected exactly one email template named {template_name!r}"
        )
    template = templates[0]
    compilers = [
        compiler
        for compiler in data.get("compilers", [])
        if compiler.get("email", "").strip()
    ]
    if compiler_email:
        compilers = [
            compiler
            for compiler in compilers
            if compiler["email"].strip().casefold()
            == compiler_email.strip().casefold()
        ]
    if len(compilers) != 1:
        raise ValueError(
            "Select exactly one compiler using --compiler when needed"
        )
    compiler = compilers[0]
    sender = compiler["email"].strip()
    captains = {}
    for captain in data.get("sector captains", []):
        captains.setdefault(captain["route"], []).extend(
            captain.get("names", [])
        )
    routes = data.get("routes", [])
    sectors = set(captains)
    for route in routes:
        sectors.update(route_sectors(route))
        if not any(contact_name(person) for person in route.get("leaders", [])):
            LOGGER.warning("Route %s has no leader", route["number"])
    for sector in sorted(sectors):
        if not any(contact_name(person) for person in captains.get(sector, [])):
            LOGGER.warning("Sector %s has no captain", sector)

    groups = []
    announcement = template_name in (
        "Captain Announcement",
        "Participant Announcement",
    )
    if announcement:
        people = template_recipients(data, template.get("to"), "To")
        groups.append((people, [], None, []))
    elif template.get("to") == "sector captains":
        for sector in sorted(sectors):
            people = recipient_list(
                captains.get(sector, []), f"Sector {sector} captain"
            )
            sector_routes = [
                route for route in routes if sector in route_sectors(route)
            ]
            sector_routes.sort(
                key=lambda route, sector_number=sector: (
                    route_sectors(route)[0] != sector_number
                )
            )
            if people:
                groups.append((people, [], sector, sector_routes))
    elif template.get("to") == "route leaders":
        for route in routes:
            people = recipient_list(
                route.get("leaders", []), f"Route {route['number']} leader"
            )
            if people:
                route_captains = [
                    person
                    for sector in route_sectors(route)
                    for person in captains.get(sector, [])
                ]
                copies = recipient_list(
                    route_captains, f"Route {route['number']} captain"
                )
                groups.append((people, copies, None, [route]))
    else:
        raise ValueError(
            f"Unsupported template recipient group: {template.get('to')!r}"
        )

    template_cc = template_recipients(data, template.get("cc"), "Cc")
    template_bcc = template_recipients(data, template.get("bcc"), "Bcc")
    messages = []
    for people, copies, sector, group_routes in groups:
        message = EmailMessage()
        message["From"] = formataddr((compiler.get("name", "").strip(), sender))
        to_addresses = [person["email"].strip() for person in people]
        if to_addresses:
            message["To"] = ", ".join(to_addresses)
        seen_addresses = {address.casefold() for address in to_addresses}
        cc_addresses = []
        for person in copies + template_cc:
            address = person["email"].strip()
            if address.casefold() not in seen_addresses:
                seen_addresses.add(address.casefold())
                cc_addresses.append(address)
        if cc_addresses:
            message["Cc"] = ", ".join(cc_addresses)
        bcc_addresses = []
        for person in template_bcc:
            address = person["email"].strip()
            if address.casefold() not in seen_addresses:
                seen_addresses.add(address.casefold())
                bcc_addresses.append(address)
        if bcc_addresses:
            message["Bcc"] = ", ".join(bcc_addresses)
        if not (to_addresses or cc_addresses or bcc_addresses):
            continue
        message["Subject"] = template["subject"]
        paragraphs = []
        if not announcement:
            names = [
                contact_name(person).split(maxsplit=1)[0] for person in people
            ]
            greeting = (
                names[0]
                if len(names) == 1
                else f"{', '.join(names[:-1])} and {names[-1]}"
            )
            paragraphs.append(f"Dear {greeting},")
        website = (data.get("website") or "").strip()
        if sector is not None:
            sector_line = (
                f"You are identified as the captain of sector {sector}"
            )
            if website:
                sector_line += f" (Sector map: {website})"
            paragraphs.append(f"{sector_line}.")
        paragraphs.extend(
            re.sub(
                r"\{\s*rain date\s*\}",
                format_date(rain_date),
                template["message"].replace("{date}", format_date(count_date)),
            ).split("\n")
        )
        if sector is not None:
            paragraphs.append(f"Sector {sector} routes:")
        paragraphs.extend(
            format_route(route, captains) for route in group_routes
        )
        paragraphs.append(
            "\n".join(
                part
                for part in (
                    "Sincerely,",
                    compiler.get("name", "").strip(),
                    sender,
                )
                if part
            )
        )
        message.set_content("\n\n".join(paragraphs))
        if sector is not None and website:
            html_paragraphs = [
                f"<p>{escape(paragraph).replace(chr(10), '<br>')}</p>"
                for paragraph in paragraphs
            ]
            html_paragraphs[1] = (
                f"<p>You are identified as the captain of sector {escape(str(sector))} "
                f'(<a href="{escape(website, quote=True)}">Sector map</a>).</p>'
            )
            message.add_alternative(
                "<html><body>" + "\n".join(html_paragraphs) + "</body></html>",
                subtype="html",
            )
        messages.append(message)
    return sender, messages


def format_route(route, captains):
    heading = f"Route {route['number']}"
    if route.get("name"):
        heading += f" - {route['name'].strip()}"
    lines = [heading]
    if route.get("description"):
        lines.append(f"Description: {route['description']}")
    lines.append(f"Route Leader(s): {contact_list(route.get('leaders', []))}")
    sectors = route_sectors(route)
    sector_captains = (
        "; ".join(
            f"Sector {sector}: {contact_list(captains.get(sector, []))}"
            for sector in sectors
        )
        or "Open"
    )
    lines.append(f"Sector Captain(s): {sector_captains}")
    if sectors:
        sector_labels = [f"{sectors[0]} (PRIMARY)"]
        sector_labels.extend(f"{sector} (Secondary)" for sector in sectors[1:])
        lines.append(f"Sectors: {', '.join(sector_labels)}")
    if route.get("notes"):
        lines.append(f"Notes: {route['notes']}")
    return "\n".join(lines)


def create_drafts(sender, messages, env_path):
    if not env_path.is_file():
        raise ValueError(f"Environment file not found: {env_path}")
    settings = dotenv_values(env_path)
    username = (settings.get("MAIL_USERNAME") or "").strip()
    password = settings.get("MAIL_PASSWORD") or ""
    if not username or not password:
        raise ValueError(
            "Set MAIL_USERNAME and MAIL_PASSWORD in the environment file"
        )
    if username.casefold() != sender.casefold():
        raise ValueError(
            f"Mail account {username} does not match compiler {sender}"
        )

    tls_context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, context=tls_context, timeout=30
    ) as smtp:
        smtp.login(username, password)

    with imaplib.IMAP4_SSL(
        "imap.gmail.com", 993, ssl_context=tls_context, timeout=30
    ) as mailbox:
        mailbox.login(username, password)
        status, folders = mailbox.list()
        if status != "OK":
            raise ValueError("Could not list Gmail mailboxes")
        draft_folder = None
        for folder in folders:
            match = re.match(
                rb'^\(([^)]*)\) (?:"(?:[^"\\]|\\.)*"|NIL) (.+)$', folder
            )
            if match and b"\\drafts" in match.group(1).lower().split():
                draft_folder = match.group(2).decode("ascii")
                break
        if draft_folder is None:
            raise ValueError("Could not find Gmail's Drafts mailbox")
        for message in messages:
            status, _ = mailbox.append(
                draft_folder,
                r"(\Draft)",
                None,
                message.as_bytes(policy=policy.SMTP),
            )
            if status != "OK":
                raise ValueError(f"Could not create draft for {message['To']}")
            print(
                f"Created draft for {message['To'] or 'undisclosed recipients'}"
            )


def main():
    logging.basicConfig(
        level=logging.WARNING, format="%(levelname)s: %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="Create Gmail confirmation drafts without sending them."
    )
    parser.add_argument(
        "--email", required=True, help="Email template name from the JSON file"
    )
    parser.add_argument(
        "--routes", required=True, help="JSON filename in the data directory"
    )
    parser.add_argument(
        "--compiler",
        help="Compiler email address, required when multiple compilers are listed",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="File containing MAIL_USERNAME and MAIL_PASSWORD",
    )
    args = parser.parse_args()
    if Path(args.routes).name != args.routes or args.routes in (".", ".."):
        parser.error("--routes must be a filename in the data directory")
    try:
        with (DATA_DIR / args.routes).open(encoding="utf-8") as routes_file:
            data = json.load(routes_file)
        sender, messages = build_messages(data, args.email, args.compiler)
        if not messages:
            print("No recipients with email addresses; no drafts created.")
            return
        create_drafts(sender, messages, args.env_file)
    except (OSError, ValueError, KeyError, imaplib.IMAP4.error) as error:
        parser.exit(1, f"Error: {error}\n")
