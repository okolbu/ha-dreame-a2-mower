import subprocess, shutil, pathlib, pytest

NODE = shutil.which("node")
HARNESS = pathlib.Path(__file__).parent / "wifi_overlay_key_harness.mjs"


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_wifi_overlay_key_harness():
    r = subprocess.run([NODE, str(HARNESS)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"node harness failed:\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout
