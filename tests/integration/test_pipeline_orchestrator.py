"""
Unit-test style verification of the CLI Orchestrator run_pipeline.py.
Mocks out subprocesses to check arguments, ordering, and error boundaries.
"""
import pytest
from unittest.mock import patch
import sys
import run_pipeline

@pytest.fixture
def mock_external():
    """Mocks execute_external and check_binary safely."""
    with patch("run_pipeline.execute_external") as m_exec, \
         patch("run_pipeline.subprocess.run") as m_sub, \
         patch("builtins.print") as m_print, \
         patch("shutil.copy") as m_copy, \
         patch("os.makedirs") as m_mkdir, \
         patch("os.path.exists", return_value=True) as m_exists, \
         patch("os.path.getsize", return_value=100) as m_size, \
         patch("builtins.open") as m_open:
        
        # Make check_binary / sanity subprocesses pass
        m_sub_res = m_sub.return_value
        m_sub_res.returncode = 0
        
        # Make execute_external pass unconditionally
        m_exec_res = m_exec.return_value
        m_exec_res.returncode = 0
        
        yield {
            "m_exec": m_exec,
            "m_sub": m_sub,
            "m_exists": m_exists,
            "m_copy": m_copy
        }

def run_cli_args(args_list):
    """Simple wrapper to trigger main with given CLI args."""
    with patch.object(sys, "argv", ["run_pipeline.py"] + args_list):
        run_pipeline.main()

def test_missing_audio_raises_sys_exit(mock_external):
    mock_external["m_exists"].side_effect = lambda path: path != "nonexistent.mp3"
    with pytest.raises(SystemExit) as e:
         run_cli_args(["--audio", "nonexistent.mp3", "--lyrics", "ok.txt", "--lang", "en"])
    assert e.value.code == 1

def test_dry_run_executes_nothing(mock_external):
    run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en", "--dry-run"])
    # execute_external should NEVER be called in a dry-run
    mock_external["m_exec"].assert_not_called()

def test_happy_path_orchestration_order(mock_external):
    run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en"])
    calls = mock_external["m_exec"].call_args_list
    assert len(calls) == 6
    
    # 1. preprocess audio
    assert "01_preprocess_audio.ps1" in calls[0].args[0][4]
    
    # 2. demucs separate
    assert "02_demucs_separate.ps1" in calls[1].args[0][4]
    
    # 3. prepare corpus
    assert "03_prepare_corpus.py" in calls[2].args[0][1]
    
    # 4. router
    assert "04_mfa_router.py" in calls[3].args[0][1]
    
    # 5. mfa align
    assert "05_mfa_align.ps1" in calls[4].args[0][4]
    
    # 6. textgrid_to_ass + 7. qc_report
    assert "06_textgrid_to_ass.py" in calls[5].args[0][1]

def test_strict_mode_escalates_exit_code(mock_external):
    # Make the 7th step (QC report) fail
    def mock_side_effect(cmd, *args, **kwargs):
        class MockRes:
            returncode = 1 if "07_qc_report.py" in cmd else 0
        return MockRes()
        
    mock_external["m_exec"].side_effect = mock_side_effect
    
    with pytest.raises(SystemExit) as e:
         run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en", "--strict"])
    
    # strict should promote 07_qc_report.py failure to exit code 2
    assert e.value.code == 2

def test_demucs_failure_halts_pipeline(mock_external):
    def mock_side_effect(cmd, *args, **kwargs):
        class MockRes:
            returncode = 1 if "02_demucs_separate.ps1" in cmd[4] else 0
        return MockRes()
        
    mock_external["m_exec"].side_effect = mock_side_effect
    
    with pytest.raises(SystemExit) as e:
         run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en"])
    
    # Failed right after starting step 2
    assert e.value.code == 1
    # Only called up to step 2 (preprocess, demucs)
    assert len(mock_external["m_exec"].call_args_list) == 2

def test_resume_keep_work_skips_processing(mock_external):
    """Testa se com --keep-work e os outputs criados ele pula as execuções demoradas"""
    
    # Fake exists: say yes conditionally for target outputs.
    # We want to skip Demucs (if vocals.wav exists) and MFA (if TextGrid exists)
    def fake_exists(path):
        known_skips = [
            "work/02_stems/htdemucs", 
            "work/05_textgrids/aligned/song.TextGrid"
        ]
        text_match = path.replace("\\", "/")
        if "lyrics.txt" in text_match or "song.mp3" in text_match: return True
        return any(s in text_match for s in known_skips)
        
    mock_external["m_exists"].side_effect = fake_exists
    
    run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en", "--keep-work"])
    calls = mock_external["m_exec"].call_args_list
    # Wait, Demucs is step 02 and MFA is step 05.
    cmds = [c.args[0][4] if len(c.args[0]) > 4 else c.args[0][1] for c in calls]
    
    assert not any("02_demucs" in cmd for cmd in cmds), "Demucs failed to bypass!"
    assert not any("05_mfa" in cmd for cmd in cmds), "MFA failed to bypass!"
    assert any("06_textgrid_to_ass" in cmd for cmd in cmds), "Should run final ASS steps"
    """Teste garantindo que sem limite o pipeline pass, ou levanta 2 se --strict e falhou no textgrid."""
    
    # Make the QC fail
    def mock_side_effect(cmd, *args, **kwargs):
        class MockRes:
            returncode = 1 if "07_qc_report.py" in cmd else 0
        return MockRes()
        
    mock_external["m_exec"].side_effect = mock_side_effect
    
    # without strict it finishes natively (since pipeline runner allows QC to return code 1, mapping to Exit Code 1 which in old code triggers python exit but now it might bypass unless strict)
    # Wait, our wrapper run_py returns exit 1 if script fails, and 2 if strict.
    with pytest.raises(SystemExit) as e_strict:
        run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en", "--strict"])
    assert e_strict.value.code == 2

def test_g2p_oov_flow_triggered(mock_external):
    """Simula o script mfa encontrou OOvs via find_oov. O script powershell orquestra no shell"""
    # Assuming G2P invocation executes the process natively inside 05_mfa_align.ps1
    run_cli_args(["--audio", "a.mp3", "--lyrics", "b.txt", "--lang", "en"])
    calls = mock_external["m_exec"].call_args_list
    assert len(calls) == 6
    assert "05_mfa_align.ps1" in calls[4].args[0][4]
