"""
Values from outside the app do not reach the page through innerHTML.

Run labels come from bulk import file names and scrape URLs, folder names come off disk
through /api/browse, the external URL is whatever somebody typed into the settings
form, and the signed in username comes from the identity provider. Written into innerHTML they are markup, so a label containing a script tag runs
every time somebody opens the run history or the log modal, long after whoever wrote the
label has gone. Each of those values goes into a child element with textContent instead,
which puts it on the page as text whatever it contains. It is the same reasoning as the
Apprise URL row, which assigns its URL as a property for the same reason.

This reads the shipped script rather than running it: there is no JavaScript test runner
here, and adding one for five call sites would cost more than it is worth. What it cannot
see is which element a value lands in, only that it lands in one by textContent. It covers
the values named in the fix, not every sink in the file; `cell.innerHTML = value` in the
run history table still takes server built markup, which is a separate change.
"""

import os
import re

import pytest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "static", "web_interface.js")

# The expressions the fix moved out of innerHTML, each one an outside value.
OUTSIDE_VALUES = [
    "folder.name",       # a directory name on disk, from /api/browse
    "label",             # the run label, on the delete confirmation
    "runLabel",          # the run label, on the log modal title
    "externalURL.value", # whatever has been typed into the external URL field
    "timestamp",         # the run timestamp, formatted onto the delete confirmation
    "data.username",     # the signed in user, from the identity provider or the login form
]


@pytest.fixture(scope="module")
def script():
    with open(SCRIPT, encoding="utf-8") as handle:
        return handle.read()


def _template_literals_assigned_to_inner_html(source):
    """Every template literal assigned straight to innerHTML, without its backticks."""
    templates = []
    for assignment in re.finditer(r"\.innerHTML\s*=\s*`", source):
        start = assignment.end()
        position = start
        depth = 0
        while position < len(source):
            character = source[position]
            if character == "\\":
                position += 2
                continue
            if source.startswith("${", position):
                depth += 1
                position += 2
                continue
            if character == "}" and depth:
                depth -= 1
            elif character == "`" and not depth:
                templates.append(source[start:position])
                break
            position += 1
    return templates


def _interpolations(template):
    """The expressions inside the ${...} of a template literal."""
    return re.findall(r"\$\{([^}]*)\}", template)


# A marker from the static shell of each site the fix touched.
FIXED_SITES = [
    "bi bi-folder",                 # the directory browser
    "You are about to delete run",  # the delete run confirmation
    "bi bi-file-earmark-text",      # the log modal title
    "as an allowed callback URL",   # the OIDC callback alert
    "Signed is as",                 # the signed in banner
]


@pytest.mark.unit
@pytest.mark.parametrize("marker", FIXED_SITES)
def test_the_scanner_reaches_every_site_the_fix_touched(script, marker):
    """A scanner that missed these would pass every test below without reading them."""
    templates = _template_literals_assigned_to_inner_html(script)

    assert any(marker in template for template in templates)


@pytest.mark.unit
def test_every_interpolation_in_every_template_is_read(script):
    """`[^}]*` stops at the first brace, so a nested one would hide what follows it."""
    for template in _template_literals_assigned_to_inner_html(script):
        assert len(_interpolations(template)) == template.count("${")


@pytest.mark.unit
@pytest.mark.parametrize("value", OUTSIDE_VALUES)
def test_no_outside_value_is_interpolated_into_innerhtml(script, value):
    pattern = re.compile(r"\b%s\b" % re.escape(value))
    offenders = [
        interpolation
        for template in _template_literals_assigned_to_inner_html(script)
        for interpolation in _interpolations(template)
        if pattern.search(interpolation)
    ]

    assert offenders == []


@pytest.mark.unit
@pytest.mark.parametrize("value", OUTSIDE_VALUES)
def test_every_outside_value_is_written_with_textcontent(script, value):
    """Moved out of innerHTML, each value still has to reach the page somewhere."""
    pattern = re.compile(r"\.textContent\s*=\s*[^;\n]*\b%s\b" % re.escape(value))

    assert pattern.search(script) is not None
