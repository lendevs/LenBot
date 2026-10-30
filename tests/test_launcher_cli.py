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


def test_container_entry_also_warns_in_an_empty_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(launcher, 'run', lambda **_: 0)
    with pytest.raises(SystemExit):
        launcher.container_main([])
    assert str(tmp_path) in capsys.readouterr().out


def test_container_volume_is_migrated_once_and_refuses_newer_data(tmp_path, monkeypatch):
    from len_bot.next.maintenance import upgrade
    root = tmp_path / 'instance'
    root.mkdir()
    monkeypatch.setattr(upgrade, 'installed_release', lambda: '0.2.0')
    calls = []
    monkeypatch.setattr(upgrade, 'upgrade_instance', lambda path, snapshot: calls.append(snapshot))
    launcher.migrate_container_volume(root)
    assert upgrade.recorded_release(root) == '0.2.0' and calls == []
    (root / 'lenbot.config.json').write_text('{}')
    launcher.migrate_container_volume(root)
    assert calls == []
    (root / upgrade.RELEASE_RECORD).write_text('{"version": "0.1.0"}')
    launcher.migrate_container_volume(root)
    snapshot, = calls
    assert snapshot.parent == tmp_path / 'backups'
    (root / upgrade.RELEASE_RECORD).write_text('{"version": "0.3.0"}')
    with pytest.raises(SystemExit, match='0.3.0'):
        launcher.migrate_container_volume(root)


def test_migration_moves_only_an_official_task_image_to_the_new_version(tmp_path):
    import json
    path = tmp_path / 'lenbot.config.json'
    for image, expected in [('ghcr.io/lendevs/lenbot-worker:0.1.0', 'ghcr.io/lendevs/lenbot-worker:0.2.0'),
                            ('lendevs/lenbot-worker@sha256:' + '0' * 64, 'lendevs/lenbot-worker:0.2.0'),
                            ('lenbot-worker:local', 'lenbot-worker:local')]:
        path.write_text(json.dumps({'worker': {'sandbox': 'docker', 'image': image}}))
        launcher.follow_release_worker(tmp_path, '0.2.0')
        assert json.loads(path.read_text())['worker']['image'] == expected
    path.write_text(json.dumps({'worker': None}))
    launcher.follow_release_worker(tmp_path, '0.2.0')
