"""Tests for src/ingestion/markdown.html_to_markdown."""

from __future__ import annotations

import pytest

from src.ingestion.markdown import html_to_markdown


# ---------------------------------------------------------------------------
# Plain-text passthrough
# ---------------------------------------------------------------------------


def test_plain_text_returned_unchanged():
    assert html_to_markdown("No HTML here.") == "No HTML here."


def test_empty_string_returns_empty():
    assert html_to_markdown("") == ""


def test_whitespace_only_returns_empty():
    assert html_to_markdown("   ") == ""


# ---------------------------------------------------------------------------
# Paragraph and block elements
# ---------------------------------------------------------------------------


def test_p_tags_produce_paragraph_breaks():
    result = html_to_markdown("<p>First paragraph.</p><p>Second paragraph.</p>")
    assert "First paragraph." in result
    assert "Second paragraph." in result
    assert "\n\n" in result


def test_div_tags_produce_paragraph_breaks():
    result = html_to_markdown("<div>Block one.</div><div>Block two.</div>")
    assert "Block one." in result
    assert "Block two." in result


def test_br_tag_produces_newline():
    result = html_to_markdown("Line one.<br>Line two.")
    assert "Line one." in result
    assert "Line two." in result
    assert "\n" in result


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------


def test_h1_converted_to_markdown_heading():
    result = html_to_markdown("<h1>Top Level</h1>")
    assert result == "# Top Level"


def test_h2_converted_to_markdown_heading():
    result = html_to_markdown("<h2>Section</h2>")
    assert result == "## Section"


def test_h3_converted_to_markdown_heading():
    result = html_to_markdown("<h3>Subsection</h3>")
    assert result == "### Subsection"


# ---------------------------------------------------------------------------
# Inline formatting
# ---------------------------------------------------------------------------


def test_strong_converted_to_bold():
    result = html_to_markdown("<strong>bold text</strong>")
    assert "**bold text**" in result


def test_b_converted_to_bold():
    result = html_to_markdown("<b>bold</b>")
    assert "**bold**" in result


def test_em_converted_to_italic():
    result = html_to_markdown("<em>italic text</em>")
    assert "*italic text*" in result


def test_i_converted_to_italic():
    result = html_to_markdown("<i>italic</i>")
    assert "*italic*" in result


def test_code_converted_to_backtick():
    result = html_to_markdown("<code>some_function()</code>")
    assert "`some_function()`" in result


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def test_unordered_list_converted():
    html = "<ul><li>Alpha</li><li>Beta</li><li>Gamma</li></ul>"
    result = html_to_markdown(html)
    assert "- Alpha" in result
    assert "- Beta" in result
    assert "- Gamma" in result


def test_ordered_list_converted():
    html = "<ol><li>First</li><li>Second</li></ol>"
    result = html_to_markdown(html)
    assert "1. First" in result
    assert "2. Second" in result


# ---------------------------------------------------------------------------
# Skipped tags (content discarded)
# ---------------------------------------------------------------------------


def test_script_content_discarded():
    result = html_to_markdown("<p>Visible.</p><script>alert('xss')</script>")
    assert "alert" not in result
    assert "Visible." in result


def test_style_content_discarded():
    result = html_to_markdown("<style>.foo { color: red; }</style><p>Text.</p>")
    assert "color" not in result
    assert "Text." in result


def test_nav_content_discarded():
    result = html_to_markdown("<nav><a href='/'>Home</a></nav><p>Article.</p>")
    assert "Home" not in result
    assert "Article." in result


# ---------------------------------------------------------------------------
# Entity decoding
# ---------------------------------------------------------------------------


def test_html_entities_decoded():
    result = html_to_markdown("<p>Caf&eacute; &amp; Co.</p>")
    assert "Café" in result
    assert "&" in result


def test_numeric_entity_decoded():
    result = html_to_markdown("<p>&#8212;em dash</p>")
    assert "—" in result


# ---------------------------------------------------------------------------
# Whitespace normalisation
# ---------------------------------------------------------------------------


def test_excess_blank_lines_collapsed():
    html = "<p>One.</p>\n\n\n\n<p>Two.</p>"
    result = html_to_markdown(html)
    assert "\n\n\n" not in result


def test_trailing_whitespace_stripped_per_line():
    result = html_to_markdown("<p>  spaces  </p>")
    for line in result.splitlines():
        assert line == line.rstrip()


# ---------------------------------------------------------------------------
# Realistic article snippet
# ---------------------------------------------------------------------------


def test_realistic_article_snippet():
    html = """
    <article>
      <h2>High Press Tactics</h2>
      <p>Teams using a <strong>high press</strong> have seen improved results.</p>
      <ul>
        <li>Immediate pressure on the ball carrier</li>
        <li>Compact defensive shape</li>
      </ul>
      <script>trackingPixel();</script>
    </article>
    """
    result = html_to_markdown(html)

    assert "## High Press Tactics" in result
    assert "**high press**" in result
    assert "- Immediate pressure on the ball carrier" in result
    assert "- Compact defensive shape" in result
    assert "trackingPixel" not in result


# ---------------------------------------------------------------------------
# Anchor tags (text preserved, URL dropped to save tokens)
# ---------------------------------------------------------------------------


def test_anchor_text_preserved():
    result = html_to_markdown('<a href="https://example.com">Click here</a>')
    assert "Click here" in result


def test_anchor_href_not_included():
    result = html_to_markdown('<a href="https://example.com/very-long-url">Link</a>')
    assert "https://example.com/very-long-url" not in result
