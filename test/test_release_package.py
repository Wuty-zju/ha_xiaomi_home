# -*- coding: utf-8 -*-
"""Release packaging checks using real, disposable Git repositories."""
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile
import pytest

pytestmark = pytest.mark.github


def builder():
    source = Path(__file__).parent.parent / 'script/build_release.py'
    spec = importlib.util.spec_from_file_location('build_release', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_archive


@pytest.fixture(name='release_repo')
def release_repo_fixture(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q', str(repo)], check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Synthetic'],
                   check=True)
    subprocess.run(['git', '-C', str(repo), 'config', 'user.email',
                    'synthetic@example.invalid'], check=True)
    component = repo / 'custom_components/xiaomi_home'
    component.mkdir(parents=True)
    (component / 'manifest.json').write_text(json.dumps({
        'domain': 'xiaomi_home', 'version': 'v0.5.1'}))
    (component / 'sensor.py').write_text('# synthetic source\n')
    (repo / 'LICENSE.md').write_text('Synthetic license notice\n')
    (repo / 'LegalNotice.md').write_text('Synthetic legal notice\n')
    subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'test fixture'],
                   check=True)
    return repo


def test_reproducible_fixed_commit_and_hacs_layout(release_repo, tmp_path):
    build = builder()
    first, second = tmp_path / 'first.zip', tmp_path / 'second.zip'
    metadata = build(release_repo, 'HEAD', 'v0.5.1', first)
    # Untracked/modified working files are not part of the selected commit.
    component = release_repo / 'custom_components/xiaomi_home'
    (component / 'private.txt').write_text('synthetic untracked data')
    (component / 'sensor.py').write_text('# modified after commit\n')
    other = build(release_repo, metadata['sha'], 'v0.5.1', second)
    assert metadata == other
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        assert set(archive.namelist()) == {
            'manifest.json', 'sensor.py', 'LICENSE.md', 'LegalNotice.md'}
        assert archive.read('sensor.py') == b'# synthetic source\n'
        assert json.loads(archive.read('manifest.json'))['version'] == 'v0.5.1'
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0)
                   for info in archive.infolist())


@pytest.mark.parametrize('tag', ['0.5.1', 'vv0.5.1', 'v0.5.2'])
def test_invalid_or_mismatched_tag(release_repo, tmp_path, tag):
    with pytest.raises(ValueError):
        builder()(release_repo, 'HEAD', tag, tmp_path / 'bad.zip')


def test_output_is_never_overwritten(release_repo, tmp_path):
    output = tmp_path / 'existing.zip'
    output.write_bytes(b'synthetic existing asset')
    with pytest.raises(FileExistsError):
        builder()(release_repo, 'HEAD', 'v0.5.1', output)
    assert output.read_bytes() == b'synthetic existing asset'


@pytest.mark.parametrize('relative_path', [
    'LICENSE.md', 'LegalNotice.md',
    'custom_components/xiaomi_home/manifest.json'])
def test_missing_required_file(release_repo, tmp_path, relative_path):
    subprocess.run(['git', '-C', str(release_repo), 'rm', relative_path],
                   check=True, capture_output=True)
    subprocess.run(['git', '-C', str(release_repo), 'commit', '-qm',
                    'remove required fixture'], check=True)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        builder()(release_repo, 'HEAD', 'v0.5.1', tmp_path / 'bad.zip')


@pytest.mark.parametrize('filename', ['runtime.key', 'runtime.cert',
                                      'output.zip', '__pycache__/sensor.pyc'])
def test_tracked_runtime_material_is_rejected(release_repo, tmp_path, filename):
    unsafe = release_repo / 'custom_components/xiaomi_home' / filename
    unsafe.parent.mkdir(exist_ok=True)
    unsafe.write_text('synthetic forbidden material')
    subprocess.run(['git', '-C', str(release_repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(release_repo), 'commit', '-qm',
                    'add forbidden fixture'], check=True)
    with pytest.raises(ValueError):
        builder()(release_repo, 'HEAD', 'v0.5.1', tmp_path / 'bad.zip')


def test_conflicting_component_notice_is_rejected(release_repo, tmp_path):
    notice = release_repo / 'custom_components/xiaomi_home/LICENSE.md'
    notice.write_text('synthetic conflicting notice')
    subprocess.run(['git', '-C', str(release_repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(release_repo), 'commit', '-qm',
                    'add conflicting notice'], check=True)
    with pytest.raises(ValueError):
        builder()(release_repo, 'HEAD', 'v0.5.1', tmp_path / 'bad.zip')


def test_symlinks_are_not_packaged(release_repo, tmp_path):
    link = release_repo / 'custom_components/xiaomi_home/unsafe-link'
    link.symlink_to('/synthetic/outside')
    subprocess.run(['git', '-C', str(release_repo), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(release_repo), 'commit', '-qm',
                    'add synthetic symlink'], check=True)
    with pytest.raises(ValueError):
        builder()(release_repo, 'HEAD', 'v0.5.1', tmp_path / 'bad.zip')
