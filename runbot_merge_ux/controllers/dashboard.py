##############################################################################
# For copyright and license notices, see __manifest__.py file in module root
# directory
##############################################################################

import collections
from itertools import chain

from odoo.addons.runbot_merge.controllers import dashboard
from odoo.tools import file_open
from PIL import Image, ImageDraw, ImageFont

# Import classes from the original module
Cell = dashboard.Cell
Line = dashboard.Line
Lines = dashboard.Lines
Text = dashboard.Text
Checkbox = dashboard.Checkbox
Decoration = dashboard.Decoration
BG = dashboard.BG
TEXT = dashboard.TEXT
SUCCESS = dashboard.SUCCESS
ERROR = dashboard.ERROR
HORIZONTAL_PADDING = dashboard.HORIZONTAL_PADDING
VERTICAL_PADDING = dashboard.VERTICAL_PADDING
blend = dashboard.blend
lighten = dashboard.lighten


# Monkey patch render_full_table to add bump_policy visualization
_original_render_full_table = dashboard.render_full_table


def render_full_table_with_bump_policy(pr, branches, repos, batches):  # noqa: C901
    """Extended version of render_full_table that includes bump_policy information"""

    with file_open("web/static/fonts/google/Open_Sans/Open_Sans-Regular.ttf", "rb") as f:
        font = ImageFont.truetype(f, size=16, layout_engine=0)
        f.seek(0)
        supfont = ImageFont.truetype(f, size=13, layout_engine=0)
    with file_open("web/static/fonts/google/Open_Sans/Open_Sans-Bold.ttf", "rb") as f:
        bold = ImageFont.truetype(f, size=16, layout_engine=0)
    with file_open("web/static/src/libs/fontawesome/fonts/fontawesome-webfont.ttf", "rb") as f:
        icons = ImageFont.truetype(f, size=16, layout_engine=0)

    rowheights = collections.defaultdict(int)
    colwidths = collections.defaultdict(int)
    cells = {}
    for b in chain([None], branches):
        for r in chain([None], repos):
            opacity = 1.0 if b is None or b.active else 0.5
            current_row = b == pr.target
            background = BG["info"] if current_row or r == pr.repository else BG[None]

            if b is None:  # first row
                cell = Cell(Text("" if r is None else r.name, bold, TEXT), background)
            elif r is None:  # first column
                cell = Cell(Text(b.name, font, blend(TEXT, opacity, over=background)), background)
            elif current_row:
                ps = batches[r, b]
                bgcolor = lighten(BG[ps["state"]], by=-0.05) if pr in ps["pr_ids"] else BG[ps["state"]]
                background = blend(bgcolor, opacity, over=background)
                foreground = blend((39, 110, 114), opacity, over=background)
                success = blend(SUCCESS, opacity, over=background)
                error = blend(ERROR, opacity, over=background)

                boxes = {
                    False: Checkbox(False, icons, foreground, success, error),
                    True: Checkbox(True, icons, foreground, success, error),
                    None: Checkbox(None, icons, foreground, success, error),
                }
                prs = []
                attached = True
                for p in ps["prs"]:
                    pr = p["pr"]
                    attached = attached and p["attached"]

                    if pr.staging_id:
                        sub = ": is staged"
                    elif pr.error:
                        sub = ": staging failed"
                    else:
                        sub = ""

                    lines = [
                        Line(
                            [
                                Text(
                                    f"#{p['number']}{sub}",
                                    font,
                                    foreground,
                                    decoration=Decoration.STRIKETHROUGH if p["closed"] else Decoration(0),
                                )
                            ]
                        ),
                    ]

                    # Show bump status for merged PRs
                    if pr.state == "merged" and pr.bump_status:
                        status_color = success if pr.bump_status == "success" else error
                        lines.append(
                            Line(
                                [
                                    Text(
                                        f"  Bump status: {pr.bump_status}",
                                        supfont,
                                        status_color,
                                    )
                                ]
                            )
                        )

                    # no need for details if closed or in error
                    if pr.state not in ("merged", "closed", "error") and not pr.staging_id:
                        if pr.draft:
                            lines.append(Line([boxes[False], Text("is in draft", font, error)]))

                        # Standard validations
                        lines.extend(
                            [
                                Line(
                                    [
                                        boxes[bool(pr.squash or pr.merge_method)],
                                        Text(
                                            "merge method: {}".format(
                                                "single" if pr.squash else (pr.merge_method or "missing")
                                            ),
                                            font,
                                            foreground if pr.squash or pr.merge_method else error,
                                        ),
                                    ]
                                ),
                                Line(
                                    [
                                        boxes[bool(pr.reviewed_by)],
                                        Text(
                                            "Reviewed" if pr.reviewed_by else "Not Reviewed",
                                            font,
                                            foreground if pr.reviewed_by else error,
                                        ),
                                    ]
                                ),
                            ]
                        )

                        # Add bump_policy check if the field exists
                        bump_text = f": {pr.bump_policy}" if pr.bump_policy else ""
                        lines.append(
                            Line(
                                [
                                    boxes[bool(pr.bump_policy)],
                                    Text(
                                        f"Bump policy{bump_text}",
                                        font,
                                        foreground if pr.bump_policy else error,
                                    ),
                                ]
                            )
                        )
                        # Show specific modules if defined
                        if pr.bump_modules:
                            lines.append(
                                Line(
                                    [
                                        Text(
                                            f"  modules: {pr.bump_modules}",
                                            supfont,
                                            foreground,
                                        )
                                    ]
                                )
                            )

                        # CI check
                        lines.append(
                            Line(
                                [
                                    boxes[pr.batch_id.skipchecks or pr.status == "success"],
                                    Text(
                                        "CI",
                                        font,
                                        foreground if pr.batch_id.skipchecks or pr.status == "success" else error,
                                    ),
                                ]
                            )
                        )

                        if not pr.batch_id.skipchecks:
                            import json

                            statuses = json.loads(pr.statuses_full)
                            for ci in pr.repository.status_ids._for_pr(pr):
                                if (status := statuses.get(ci.context.strip())) is None:
                                    if ci.prs != "required":
                                        continue
                                    status = {"state": "pending"}
                                color = foreground
                                match status["state"]:
                                    case "error" | "failure":
                                        color = error
                                        box = boxes[False]
                                    case "success":
                                        box = boxes[True]
                                    case _:
                                        box = boxes[None]

                                lines.append(
                                    Line(
                                        [
                                            Text(" - ", font, color),
                                            box,
                                            Text(f"{ci.repo_id.name}: {ci.context}", font, color),
                                        ]
                                    )
                                )
                    prs.append(Lines(lines))
                cell = Cell(Line(prs), background, attached)
            else:
                ps = batches[r, b]
                bgcolor = lighten(BG[ps["state"]], by=-0.05) if pr in ps["pr_ids"] else BG[ps["state"]]
                background = blend(bgcolor, opacity, over=background)
                foreground = blend((39, 110, 114), opacity, over=background)

                line = []
                attached = True
                for p in ps["prs"]:
                    line.append(
                        Text(
                            f"#{p['number']}",
                            font,
                            foreground,
                            decoration=Decoration.STRIKETHROUGH if p["closed"] else Decoration(0),
                        )
                    )
                    attached = attached and p["attached"]
                    for attribute in filter(
                        None,
                        [
                            "error" if p["pr"].error else "",
                            "" if p["checked"] else "missing statuses",
                            "" if p["reviewed"] else "missing r+",
                            "" if p["attached"] else "detached",
                            "staged" if p["pr"].staging_id else "ready" if p["pr"]._ready else "",
                        ],
                    ):
                        color = SUCCESS if attribute in ("staged", "ready") else ERROR
                        line.append(Text(f" {attribute}", supfont, blend(color, opacity, over=background)))
                    line.append(Text(" ", font, foreground))
                cell = Cell(Line(line), background, attached)

            cells[r, b] = cell
            rowheights[b] = max(rowheights[b], cell.height)
            colwidths[r] = max(colwidths[r], cell.width)

    im = Image.new("RGB", (sum(colwidths.values()), sum(rowheights.values())), "white")
    # no need to set the font here because every text element has its own
    draw = ImageDraw.Draw(im, "RGB")
    top = 0
    for b in chain([None], branches):
        left = 0
        for r in chain([None], repos):
            cell = cells[r, b]

            # for a given cell, we first print the background, then the text, then
            # the borders
            # need to subtract 1 because pillow uses inclusive rect coordinates
            right = left + colwidths[r] - 1
            bottom = top + rowheights[b] - 1
            draw.rectangle(
                (left, top, right, bottom),
                cell.background,
            )
            # draw content adding padding
            cell.content.draw(draw, left=left + HORIZONTAL_PADDING, top=top + VERTICAL_PADDING)
            # draw bottom-right border
            draw.line(
                [
                    (left, bottom),
                    (right, bottom),
                    (right, top),
                ],
                fill=(172, 176, 170),
            )
            if not cell.attached:
                # overdraw previous cell's bottom border
                draw.line([(left, top - 1), (right - 1, top - 1)], fill=ERROR)

            left += colwidths[r]
        top += rowheights[b]

    return im


# Apply the monkey patch
dashboard.render_full_table = render_full_table_with_bump_policy
