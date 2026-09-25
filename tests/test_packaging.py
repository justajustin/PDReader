from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_packaging_files_exist():
    root = _root()
    spec = (root / "PDReader.spec").read_text(encoding="utf-8")
    assert "web" in spec
    assert "app-icon.ico" in spec
    assert "console=False" in spec
    assert 'name="PDReader"' in spec
    assert "pypdfium2" in spec
    iss = (root / "scripts" / "PDReader.iss").read_text(encoding="utf-8")
    assert "PDReader.exe" in iss
    assert "PrivilegesRequired=lowest" in iss
    assert "PDReaderSetup" in iss
    assert "DisableDirPage=no" in iss or "DisableDirPage" not in iss
    assert "LZMAUseSeparateProcess=yes" in iss
    assert "SolidCompression=no" in iss
    assert "StatusExtractFiles" in iss
    assert "SetupPackageVersion" in iss
    assert "installed_version.json" in iss
    assert "###PDREADER_VERSION###" in iss
    assert "taskkill.exe" in iss
    assert "CloseApplications=no" in iss
    assert "InitializeSetup" in iss
    readme = (root / "scripts" / "installer-readme.txt").read_text(encoding="utf-8")
    assert "PowerPoint" in readme
    assert "PDReader" in readme
    assert "不要强制结束" in readme
    assert "原来的安装目录" in readme
    assert "PDF学习助手" not in readme
    assert "PPT 学习伴侣" not in readme
    script = (root / "scripts" / "build_installer.ps1").read_text(encoding="utf-8")
    assert "PyInstaller" in script
    assert "PDReaderSetup.spec" in script
    assert (root / "PDReaderSetup.spec").is_file()
    assert (root / "src" / "ppt_study" / "windows_installer.py").is_file()
    assert (root / "web" / "app-icon.ico").is_file()
