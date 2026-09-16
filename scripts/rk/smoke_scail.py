"""Smoke do SCAIL-2 14B fp8 nesta GPU: mede s/frame, que e a pendencia que trava a rota local.

Nao usa bench_anime.graph(): aquele grafo e SDXL (CheckpointLoaderSimple). Aqui o
grafo e montado do zero com os nos nativos do 0.34, so reusando run() para postar
e cronometrar.

    python smoke_scail.py            # 21 frames (carrega?) e depois 81 (numero real)
    python smoke_scail.py 81         # so um comprimento
"""
import os
import shutil
import sys
import time

sys.path.insert(0, r"C:\rk")
from bench_anime import run, INPUT_DIR
from gate import OUT

UNET = "wan2.1_14B_SCAIL_2_fp8_scaled.safetensors"
CLIP = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
VAE = "Wan2_1_VAE_bf16.safetensors"
CVIS = "clip_vision_h.safetensors"
LORA = "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"

W = int(os.environ.get("SCAIL_W", 512))   # 608x896 = rota do GIF (aspecto a 0,8% do alvo)
H = int(os.environ.get("SCAIL_H", 896))
SEED = int(os.environ.get("SCAIL_SEED", 20260907))
PREFIX = os.environ.get("SCAIL_PREFIX", "")   # vazio = nome antigo, scail_smoke_l<len>
_W_H_TRAINED = 512, 896    # resolucao treinada (README: 512p e 704p; H e W divisiveis por 32)
STEPS, CFG = 4, 1.0        # lightx2v distill: 4 steps, sem CFG
REF = "scail_ref.png"

POSITIVE = ("aparencia: 1boy, black hair, straw hat, red open vest, blue shorts, sandals, "
            "scar under left eye, anime screencap, flat cel shading. fundo: fundo branco liso.")
NEGATIVE = "worst quality, low quality, blurry, jpeg artifacts, photorealistic, 3d"

# SCAIL_POSITIVE no ambiente troca o positivo sem editar o arquivo (teste de acao no prompt)
POSITIVE = os.environ.get("SCAIL_POSITIVE", POSITIVE)


POSE = os.environ.get("SCAIL_POSE", "")   # nome de um .mp4 em ComfyUI/input; vazio = sem driver


def build(length):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": LORA, "strength_model": 1.0}},
        "3": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "wan"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": CVIS}},
        "6": {"class_type": "LoadImage", "inputs": {"image": REF}},
        "7": {"class_type": "CLIPVisionEncode", "inputs": {
            "clip_vision": ["5", 0], "image": ["6", 0], "crop": "none"}},
        "8": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": POSITIVE}},
        "9": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["3", 0], "text": NEGATIVE}},
        "10": {"class_type": "WanSCAILToVideo", "inputs": {
            "positive": ["8", 0], "negative": ["9", 0], "vae": ["4", 0],
            "width": W, "height": H, "length": length, "batch_size": 1,
            "reference_image": ["6", 0], "clip_vision_output": ["7", 0],
            "pose_strength": 1.0, "pose_start": 0.0, "pose_end": 1.0,
            "video_frame_offset": 0, "previous_frame_count": 5}},
        "11": {"class_type": "KSampler", "inputs": {
            "model": ["2", 0], "positive": ["10", 0], "negative": ["10", 1],
            "latent_image": ["10", 2], "seed": SEED, "steps": STEPS, "cfg": CFG,
            "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["4", 0]}},
        "13": {"class_type": "SaveImage", "inputs": {
            "images": ["12", 0], "filename_prefix": PREFIX or f"scail_smoke_l{length}"}},
    }
    if POSE:
        # o no trunca o driver ao `length` sozinho; o tooltip diz que ele reduz a metade da saida
        g["14"] = {"class_type": "LoadVideo", "inputs": {"file": POSE}}
        g["15"] = {"class_type": "GetVideoComponents", "inputs": {"video": ["14", 0]}}
        g["10"]["inputs"]["pose_video"] = ["15", 0]
    return g


def main():
    src = os.path.join(OUT, "luffy_h1_00001_.png")
    if not os.path.exists(src):
        sys.exit(f"referencia ausente: {src}")
    shutil.copy(src, os.path.join(INPUT_DIR, REF))

    lengths = [int(a) for a in sys.argv[1:]] or [21, 81]
    for L in lengths:
        print(f"--- length={L}, {W}x{H}, {STEPS} steps, cfg {CFG}, seed {SEED} ---", flush=True)
        t0 = time.perf_counter()
        ok, dt, imgs = run(build(L))
        if not ok:
            print(f"FALHOU em length={L} apos {time.perf_counter()-t0:.1f}s")
            return 1
        # `imgs` junta a saida de UI de TODOS os nos: com LoadVideo no grafo ele conta o
        # preview do video de entrada como se fosse quadro (medido: 22 para 21 pedidos).
        # O dono do dado e o SaveImage, entao conta-se o que ele escreveu em disco.
        pref = PREFIX or f"scail_smoke_l{L}"
        salvos = [f for f in imgs if f.startswith(pref)]
        print(f"OK  {len(salvos)} frames em {dt/60:.2f} min  =  {dt/L:.2f} s/frame  "
              f"(denominador: {L} pedidos, {len(salvos)} salvos por SaveImage, "
              f"{len(imgs) - len(salvos)} saidas de UI de outros nos)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
