from ansible_builder.cli import run, sys
from contextlib import contextmanager

import os
import pytest

from unittest import mock


@pytest.fixture
def cli_mock():
    @contextmanager
    def rf(args):
        with mock.patch.object(sys, 'argv', args):
            with pytest.raises(SystemExit):
                yield
    return rf


def test_custom_image(exec_env_definition_file, tmpdir, cli_mock):
    content = {'version': 1}
    path = str(exec_env_definition_file(content=content))

    args = ['ansible-builder', 'build', '-f', path, '-b', 'my-custom-image', '-c', str(tmpdir)]
    with cli_mock(args):
        run()

    with open(os.path.join(str(tmpdir), 'Containerfile')) as f:
        assert 'FROM my-custom-image' in f.read()
