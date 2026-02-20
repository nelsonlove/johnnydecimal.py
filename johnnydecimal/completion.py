"""Custom shell completion for JD IDs and category numbers."""

import click
from click.shell_completion import CompletionItem
from pathlib import Path


def get_jd_completions(ctx, param, incomplete):
    """
    Complete JD IDs and categories.
    
    - "2" → areas (20-29), categories (20, 21, ..., 26), IDs (26.01, ...)
    - "26" → category 26, plus all 26.xx IDs
    - "26." → all IDs in category 26
    - "26.0" → matching IDs (26.01, 26.02, ...)
    """
    from johnnydecimal import api
    
    try:
        docs = Path.home() / "Documents"
        jd = api.get_system(docs)
    except Exception:
        return []
    
    completions = []
    
    for area in jd.areas:
        # Complete area ranges (e.g. "20-29")
        area_prefix = str(area._number // 10)  # "2" for 20-29
        if incomplete == "" or area_prefix.startswith(incomplete):
            # Only show areas when input is very short (0-1 chars)
            if len(incomplete) <= 1:
                completions.append(
                    CompletionItem(
                        f"{area._number:02d}", help=area._name
                    )
                )
        
        for category in area.categories:
            cat_str = f"{category.number:02d}"
            
            # Complete category numbers
            if cat_str.startswith(incomplete) or incomplete == "":
                completions.append(
                    CompletionItem(cat_str, help=category.name)
                )
            
            # Complete IDs within matching categories
            for jd_id in category.ids:
                id_str = jd_id.id_str
                
                if id_str.startswith(incomplete):
                    # Disambiguate: prepend category name for generic ID names
                    id_name = jd_id.name or "(meta)"
                    help_text = f"{category.name} > {id_name}"
                    
                    completions.append(
                        CompletionItem(
                            id_str, help=help_text
                        )
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
