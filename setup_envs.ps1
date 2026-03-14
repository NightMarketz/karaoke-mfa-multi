Write-Host "Instalando Demucs Env..."
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" create -n demucs_env python=3.11 -y
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" run -n demucs_env python -m pip install -U pip
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" run -n demucs_env pip install demucs
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" run -n demucs_env demucs --help

Write-Host "Instalando MFA Env..."
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" create -n mfa_env python=3.11 -y
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" install -n mfa_env -c conda-forge montreal-forced-aligner -y
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" run -n mfa_env mfa --help

Write-Host "Teste Infra:"
& "C:\Users\Lu\miniforge3\Scripts\conda.exe" --version
ffmpeg -version
