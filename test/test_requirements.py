from ansible_builder.requirements import sanitize_requirements


def test_combine_entries():
    assert sanitize_requirements([
        'foo>1.0',
        'foo>=2.0'
    ]) == ['foo>1.0,>=2.0']


def test_remove_unwanted_requirements():
    assert sanitize_requirements([
        'foo',
        'ansible',
        'bar',
        'pytest',
        'bar',
        'zoo'
    ]) == [
        'foo',
        'bar',
        'zoo'
    ]


def test_skip_bad_formats():
    """A single incorrectly formatted requirement should warn, but not block other reqs"""
    assert sanitize_requirements([
        'foo',
        'zizzer zazzer zuzz',  # not okay
        'bar'
    ]) == ['foo', 'bar']
