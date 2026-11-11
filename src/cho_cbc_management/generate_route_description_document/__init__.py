import argparse
import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, RGBColor

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def add_leaders(document, leaders, title):
    named_leaders = [
        leader for leader in leaders if leader.get("name", "").strip()
    ]
    if not named_leaders:
        paragraph = document.add_paragraph(f"{title}: ")
        open_run = paragraph.add_run("Open")
        open_run.bold = True
        open_run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    for leader in named_leaders:
        name = leader["name"].strip()
        email = leader.get("email", "").strip()
        paragraph = document.add_paragraph(f"{title}: {name}")
        if email:
            paragraph.add_run(f" ({email})")
        if leader.get("comment"):
            paragraph.add_run(f" - {leader['comment'].strip()}")


def route_sectors(route):
    sectors = route.get("sectors", [])
    return sectors if isinstance(sectors, list) else [sectors]


def generate_document(data, output_path):
    document = Document()
    document.add_heading(data.get("description") or "Route Descriptions", 0)
    if data.get("website"):
        paragraph = document.add_paragraph()
        relationship_id = paragraph.part.relate_to(
            data["website"], RELATIONSHIP_TYPE.HYPERLINK, is_external=True
        )
        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), relationship_id)
        link_run = paragraph.add_run("Audubon circle description and Map")
        link_run.font.color.rgb = RGBColor(0, 0, 255)
        link_run.font.underline = True
        hyperlink.append(link_run.element)
        paragraph._p.append(hyperlink)  # pylint: disable=protected-access
    captains = {
        captain["route"]: captain for captain in data.get("sector captains", [])
    }
    routes = data.get("routes", [])
    sector_numbers = set(captains)
    for route in routes:
        sector_numbers.update(route_sectors(route))

    for number in sorted(sector_numbers):
        document.add_heading(f"Sector {number}", level=1)
        add_leaders(
            document,
            captains.get(number, {}).get("names", []),
            "Sector Captain",
        )

        sector_routes = [
            route for route in routes if number in route_sectors(route)
        ]
        sector_routes.sort(
            key=lambda route, sector_number=number: (
                route_sectors(route)[0] != sector_number
            )
        )
        for route in sector_routes:
            first_route_paragraph = len(document.paragraphs)
            memberships = route_sectors(route)
            heading = f"Route {route['number']}"
            if route.get("name"):
                heading += f" - {route['name'].strip()}"
            if len(memberships) > 1:
                if memberships[0] == number:
                    secondary_sectors = ", ".join(
                        f"Sector {sector}" for sector in memberships[1:]
                    )
                    heading += f" (PRIMARY; Secondary: {secondary_sectors})"
                else:
                    heading += f" (Secondary; PRIMARY: Sector {memberships[0]})"
            document.add_heading(heading, level=2)
            add_leaders(document, route.get("leaders", []), "Route Leader")
            participants = [
                participant
                for participant in route.get("participants", [])
                if participant.get("name", "").strip()
            ]
            if participants:
                add_leaders(document, participants, "Route Participants")
            if route.get("description"):
                document.add_paragraph(route["description"])
            if route.get("notes"):
                document.add_paragraph(f"Notes: {route['notes']}")
            for paragraph in document.paragraphs[first_route_paragraph:]:
                paragraph.paragraph_format.left_indent = Inches(0.5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a route description document."
    )
    parser.add_argument(
        "--routes", required=True, help="JSON filename in the data directory"
    )
    args = parser.parse_args()
    if Path(args.routes).name != args.routes or args.routes in (".", ".."):
        parser.error("--routes must be a filename in the data directory")
    input_path = DATA_DIR / args.routes
    with input_path.open(encoding="utf-8") as routes_file:
        data = json.load(routes_file)
    output_path = Path.cwd() / "reports" / f"{input_path.stem}.docx"
    generate_document(data, output_path)
    print(f"Created {output_path}")
