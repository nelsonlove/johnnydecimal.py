"""Custom shell completion for JD IDs and category numbers."""

import click
from click.shell_completion import CompletionItem
from pathlib import Path


def get_jd_completions(ctx, param, incomplete):
    """
    Complete JD IDs and categories by both number and name.

    Number-based:
      "2" → areas (20-29), categories (20, 21, ...), IDs (26.01, ...)
      "26." → all IDs in category 26

    Name-based:
      "Rec" → "Recipes" (category 26)
      "Uns" → "Unsorted" (various IDs)
    """
    from johnnydecimal import api

    try:
        docs = Path.home() / "Documents"
        jd = api.get_system(docs)
    except Exception:
        return []

    completions = []
    inc = incomplete.lower()

    for area in jd.areas:
        area_str = f"{area._number:02d}"
        area_range = f"{area._number:02d}-{area._end_number:02d}"

        # Number-based: show area when input is empty or matches prefix
        if incomplete == "" or area_str.startswith(incomplete):
            completions.append(
                CompletionItem(area_str, help=f"[{area_range}] {area._name}")
            )

        # Name-based: match on area name
        if inc and area._name.lower().startswith(inc):
            completions.append(
                CompletionItem(area._name, help=f"area {area_range}")
            )

        for category in area.categories:
            cat_str = f"{category.number:02d}"

            # Number-based
            if cat_str.startswith(incomplete) or incomplete == "":
                completions.append(
                    CompletionItem(cat_str, help=category.name)
                )

            # Name-based
            if inc and category.name.lower().startswith(inc):
                completions.append(
                    CompletionItem(category.name, help=f"category {cat_str}")
                )

            for jd_id in category.ids:
                id_str = jd_id.id_str
                id_name = jd_id.name or "(meta)"

                # Number-based
                if id_str.startswith(incomplete):
                    completions.append(
                        CompletionItem(
                            id_str, help=f"{category.name} > {id_name}"
                        )
                    )

                # Name-based (only for named IDs)
                if inc and jd_id.name and jd_id.name.lower().startswith(inc):
                    completions.append(
                        CompletionItem(jd_id.name, help=f"id {id_str}")
                    )

    return completions


class JDIdType(click.ParamType):
    """Click parameter type with JD ID completion."""
    name = "jd_id"

    def shell_complete(self, ctx, param, incomplete):
        return get_jd_completions(ctx, param, incomplete)

    def convert(self, value, param, ctx):
        return value


JD_ID = JDIdType()
