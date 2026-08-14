"""The shipped example config has to be usable as a starting config.json.

Nothing reads config.json.example at runtime, so a syntax error in it stays invisible
until somebody copies it to config.json to set the tool up, and then it fails at the
first load with a message about the file they just copied rather than the file they
copied it from. It was unparseable for a long stretch, so it is checked here.
"""

import json
import os
import shutil

import pytest

from core.config import Config

EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "config", "config.json.example")


@pytest.mark.unit
def test_the_example_config_is_valid_json():
    with open(EXAMPLE, encoding="utf-8") as example:
        json.load(example)


@pytest.mark.unit
def test_the_example_config_loads_as_a_config(tmp_path):
    """Copied into place as config.json, it has to survive a load rather than raising."""
    config_path = tmp_path / "config.json"
    shutil.copyfile(EXAMPLE, config_path)

    config = Config(str(config_path))
    config.load()

    assert config.apprise_urls == []
    assert config.schedules == []
