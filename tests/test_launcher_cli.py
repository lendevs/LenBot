"""`len-bot --help` must not build the frontend or start first-run setup (audit G-1)."""
import pytest

from len_bot.next import launcher


@pytest.mark.parametrize('argv,code', [(['--help'], 0), (['-h'], 0), (['--version'], 0), (['--bogus'], 2)])
def test_help_and_version_exit_before_launching(tmp_path, monkeypatch, capsys, argv, code):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, 'run', lambda **_: pytest.fail('help must not launch the host'))
    with pytest.raises(SystemExit) as stopped:
        launcher.main(argv)
    assert stopped.value.code == code
    out = capsys.readouterr()
    if argv == ['--help']:
        assert 'usage: len-bot' in out.out and '实例根目录' in out.out
    if argv == ['--version']:
        assert out.out.startswith('LenBot ')
    assert list(tmp_path.iterdir()) == []


def test_empty_directory_names_the_root_before_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, 'run', lambda **_: 0)
    with pytest.raises(SystemExit):
        launcher.main([])
    assert str(tmp_path) in capsys.readouterr().out
    (tmp_path / 'lenbot.config.json').write_text('{}')
    with pytest.raises(SystemExit):
        launcher.main([])
    assert capsys.readouterr().out == ''


def test_container_entry_parses_help_too(monkeypatch, capsys):
    monkeypatch.setattr(launcher, 'run', lambda **_: pytest.fail('help must not launch the host'))
    with pytest.raises(SystemExit) as stopped:
        launcher.container_main(['--help'])
    assert stopped.value.code == 0 and 'lenbot-container' in capsys.readouterr().out
