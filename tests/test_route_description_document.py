import json
import subprocess
import sys

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Inches

from cho_cbc_management.generate_route_description_document import (
    DATA_DIR,
    generate_document,
)


def test_report_sections_leaders_and_secondary_order(tmp_path):
    data = {
        "description": "Test routes",
        "website": "https://example.com/circle",
        "sector captains": [
            {
                "route": 1,
                "names": [{"name": "Captain", "email": "captain@example.com"}],
            },
            {"route": 2, "names": [{"name": "", "email": ""}]},
            {"route": 4, "names": [{"name": "Captain only", "email": ""}]},
        ],
        "routes": [
            {
                "number": 10,
                "name": "Shared",
                "sectors": [2, 1, 3],
                "leaders": [],
                "description": "Shared description",
            },
            {
                "number": 11,
                "sectors": 1,
                "leaders": [
                    {
                        "name": "Leader",
                        "email": "leader@example.com",
                        "comment": "Leader note",
                    }
                ],
                "participants": [
                    {"name": "Participant One", "email": "one@example.com"},
                    {"name": "Participant Two", "comment": "Participant note"},
                    {"name": "", "email": ""},
                ],
                "description": "Primary description",
                "notes": "Route note",
            },
            {
                "number": 12,
                "sectors": 3,
                "leaders": [{"name": "Route leader", "email": ""}],
                "description": "Route-only sector",
            },
        ],
    }
    output = tmp_path / "reports" / "test.docx"
    generate_document(data, output)
    document = Document(output)
    paragraphs = document.paragraphs
    text = [paragraph.text for paragraph in paragraphs]
    assert "Sector Captain: Captain (captain@example.com)" in text
    assert "Sector 3" in text
    assert "Sector 4" in text
    assert "Route Leader: Leader (leader@example.com) - Leader note" in text
    leader_index = text.index(
        "Route Leader: Leader (leader@example.com) - Leader note"
    )
    assert text[leader_index + 1 : leader_index + 4] == [
        "Route Participants: Participant One (one@example.com)",
        "Route Participants: Participant Two - Participant note",
        "Primary description",
    ]
    assert "Notes: Route note" in text
    assert "Shared description" in text
    assert text.index("Route 11") < text.index(
        "Route 10 - Shared (Secondary; PRIMARY: Sector 2)"
    )
    assert "Route 10 - Shared (PRIMARY; Secondary: Sector 1, Sector 3)" in text
    link = paragraphs[1].hyperlinks[0]
    assert link.text == "Audubon circle description and Map"
    assert link.address == data["website"]
    in_route = False
    for paragraph in paragraphs:
        if paragraph.style.name == "Heading 1":
            in_route = False
        elif paragraph.style.name == "Heading 2":
            in_route = True
        if in_route:
            assert paragraph.paragraph_format.left_indent == Inches(0.5)
    open_runs = [
        run
        for paragraph in paragraphs
        for run in paragraph.runs
        if run.text == "Open"
    ]
    assert len(open_runs) == 5
    assert all(
        run.bold and run.font.highlight_color == WD_COLOR_INDEX.YELLOW
        for run in open_runs
    )


def test_real_data_report_and_cli(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "cho_cbc_management.generate_route_description_document",
            "--routes",
            "2026_routes.json",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    output = tmp_path / "reports" / "2026_routes.docx"
    assert str(output) in result.stdout
    document = Document(output)
    text = [paragraph.text for paragraph in document.paragraphs]
    data = json.loads(
        (DATA_DIR / "2026_routes.json").read_text(encoding="utf-8")
    )
    assert all(f"Sector {number}" in text for number in range(1, 9))
    assert "Route 2 (PRIMARY; Secondary: Sector 6)" in text
    assert "Route 2 (Secondary; PRIMARY: Sector 5)" in text
    assert "Route Participants: Kim Kozella (kckozella@gmail.com)" in text
    assert (
        "Route Participants: Sandy DiCarlo (sdicarlo1@outlook.com) - Does not wish to be leader"
        in text
    )
    assert sum(
        paragraph.style.name == "Heading 2" for paragraph in document.paragraphs
    ) == sum(
        len(route["sectors"]) if isinstance(route["sectors"], list) else 1
        for route in data["routes"]
    )
